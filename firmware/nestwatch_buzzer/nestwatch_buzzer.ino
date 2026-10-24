// Ollo wrist buzzer (ESP32). Spec: CLUADE.md "Wrist buzzer and local alarm".
//
// It talks only to the vision service on the daycare network, over a WebSocket at ws://SERVER_HOST:SERVER_PORT/buzzer,
// so it keeps working when the internet is down. Protocol (JSON):
//   us -> server : {"type":"hello","buzzer_id":..,"battery":0.82}   {"type":"ack","buzzer_id":..,"alert_id":..}
//   server -> us : {"type":"buzz","alert_id":..,"severity":"high"|"medium"}   {"type":"stop","alert_id":..,"owner":..}   {"type":"ping"}
// One button: a tap acknowledges the alert being shown (most urgent, then oldest); the next one then comes up.
// The server re-sends every open alert after a reconnect, so a Wi-Fi blip or battery swap loses nothing.
//
// Libraries (Arduino Library Manager): "WebSockets" by Markus Sattler (links2004), "ArduinoJson" by Benoit Blanchon (v7).
// Board: any ESP32 dev board (Arduino core for ESP32 v3.x).

#include <WiFi.h>
#include <WebSocketsClient.h>
#include <ArduinoJson.h>
#include "config.h"

// ---- wiring (change to match your board) ---------------------------------------------------------------------
const int PIN_MOTOR   = 25;   // vibration motor through an NPN transistor (with a flyback diode across the motor)
const int PIN_BUTTON  = 27;   // big button to GND; internal pull-up
const int PIN_LED_R   = 16;   // RGB LED, common cathode, each leg through a resistor
const int PIN_LED_G   = 17;
const int PIN_BATTERY = 35;   // battery through a 100k/100k divider (ADC1 pin, works while Wi-Fi is on)

WebSocketsClient ws;

// ---- alert queue ------------------------------------------------------------------------------------------------
struct Pending { String id; bool high; };
const int MAX_PENDING = 8;
Pending pending[MAX_PENDING];
int pendingCount = 0;

enum State { IDLE, ALERT_HIGH, ALERT_MEDIUM, TAKEN, DISCONNECTED };
State state = DISCONNECTED;
unsigned long stateSince = 0;
bool everConnected = false;

void setState(State s) { state = s; stateSince = millis(); }

void showFront() {
  if (pendingCount == 0) { setState(IDLE); return; }
  setState(pending[0].high ? ALERT_HIGH : ALERT_MEDIUM);
}

void addPending(const String& id, bool high) {
  for (int i = 0; i < pendingCount; i++) if (pending[i].id == id) return;           // already queued
  if (pendingCount == MAX_PENDING) pendingCount--;                                  // full: drop the newest medium/last
  // keep high alerts in front of medium ones, oldest first within each group
  int pos = pendingCount;
  if (high) { pos = 0; while (pos < pendingCount && pending[pos].high) pos++; }
  for (int i = pendingCount; i > pos; i--) pending[i] = pending[i - 1];
  pending[pos] = { id, high };
  pendingCount++;
}

bool removePending(const String& id) {
  for (int i = 0; i < pendingCount; i++) {
    if (pending[i].id == id) {
      for (int j = i; j < pendingCount - 1; j++) pending[j] = pending[j + 1];
      pendingCount--;
      return true;
    }
  }
  return false;
}

// ---- outputs ----------------------------------------------------------------------------------------------------
void led(int r, int g) { analogWrite(PIN_LED_R, r); analogWrite(PIN_LED_G, g); }

// Patterns are computed from the time in the current state, so nothing blocks the WebSocket.
void updateOutputs() {
  unsigned long t = millis() - stateSince;
  bool motor = false;
  switch (state) {
    case IDLE:         motor = false;              led(0, (t % 2000) < 150 ? 120 : 0); break;     // slow green blink
    case ALERT_HIGH:   motor = (t % 1000) < 700;   led((t % 300) < 150 ? 255 : 0, (t % 300) < 150 ? 90 : 0); break;   // long pulses, fast orange
    case ALERT_MEDIUM: motor = (t % 600) < 200;    led((t % 1200) < 600 ? 255 : 0, (t % 1200) < 600 ? 90 : 0); break; // short pulses, slow orange
    case TAKEN:        motor = false;              led(0, 255); if (t > 4000) showFront(); break;   // green, then back to idle
    case DISCONNECTED: motor = everConnected && t < 1200; led(255, 0); break;                     // one long buzz, red
  }
  digitalWrite(PIN_MOTOR, motor ? HIGH : LOW);
}

float batteryLevel() {
  // Divider halves the voltage; a single-cell LiPo is roughly 3.3 V empty and 4.2 V full.
  float v = analogReadMilliVolts(PIN_BATTERY) * 2 / 1000.0;
  float level = (v - 3.3) / (4.2 - 3.3);
  return level < 0 ? 0 : (level > 1 ? 1 : level);
}

// ---- messages ---------------------------------------------------------------------------------------------------
void sendJson(JsonDocument& doc) { String s; serializeJson(doc, s); ws.sendTXT(s); }

void sendHello() {
  JsonDocument doc;
  doc["type"] = "hello"; doc["buzzer_id"] = BUZZER_ID; doc["battery"] = batteryLevel();
  sendJson(doc);
}

void onMessage(const char* text) {
  JsonDocument doc;
  if (deserializeJson(doc, text)) return;                                           // ignore anything malformed
  const char* type = doc["type"] | "";
  if (strcmp(type, "buzz") == 0) {
    addPending(String((const char*)(doc["alert_id"] | "")), strcmp(doc["severity"] | "", "high") == 0);
    showFront();
  } else if (strcmp(type, "stop") == 0) {
    bool hadAlerts = pendingCount > 0;
    removePending(String((const char*)(doc["alert_id"] | "")));
    if (hadAlerts && pendingCount == 0) setState(TAKEN); else if (pendingCount) showFront();
  }
  // "ping" needs no answer: receiving it is the keep-alive
}

void onEvent(WStype_t type, uint8_t* payload, size_t length) {
  switch (type) {
    case WStype_CONNECTED:
      everConnected = true;
      pendingCount = 0;                                // the server re-sends every open alert to a new connection
      sendHello();
      setState(IDLE);
      break;
    case WStype_DISCONNECTED:
      if (state != DISCONNECTED) setState(DISCONNECTED);
      break;
    case WStype_TEXT:
      onMessage((const char*)payload);
      break;
    default:
      break;
  }
}

// ---- button -----------------------------------------------------------------------------------------------------
void handleButton() {
  static bool last = HIGH;
  static unsigned long changedAt = 0;
  bool now = digitalRead(PIN_BUTTON);
  if (now != last && millis() - changedAt > 40) {      // 40 ms debounce
    changedAt = millis();
    last = now;
    if (now == LOW) {                                  // pressed
      if (pendingCount > 0 && ws.isConnected()) {
        JsonDocument doc;
        doc["type"] = "ack"; doc["buzzer_id"] = BUZZER_ID; doc["alert_id"] = pending[0].id;
        sendJson(doc);
        removePending(pending[0].id);                  // the next alert (if any) comes up at once
        if (pendingCount) showFront(); else setState(TAKEN);      // green for a moment: it went through
      } else if (!ws.isConnected()) {
        WiFi.reconnect();                              // a tap while disconnected retries the connection
      }
    }
  }
}

// ---- main ---------------------------------------------------------------------------------------------------------
void setup() {
  pinMode(PIN_MOTOR, OUTPUT);
  pinMode(PIN_BUTTON, INPUT_PULLUP);
  pinMode(PIN_LED_R, OUTPUT);
  pinMode(PIN_LED_G, OUTPUT);
  analogReadResolution(12);
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  ws.begin(SERVER_HOST, SERVER_PORT, "/buzzer");
  ws.onEvent(onEvent);
  ws.setReconnectInterval(2000);                       // retry every 2 s when the computer or Wi-Fi is away
  setState(DISCONNECTED);
}

void loop() {
  ws.loop();
  handleButton();
  updateOutputs();
  static unsigned long lastHello = 0;
  if (ws.isConnected() && millis() - lastHello > 60000) { sendHello(); lastHello = millis(); }   // battery report each minute
}
