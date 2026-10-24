# Ollo wrist buzzer (ESP32)

Vibrates when the vision service tells it to and acknowledges with one button. It talks only to the vision service on
the daycare network, so it keeps working without internet.

## Parts
ESP32 dev board, small vibration motor + NPN transistor (e.g. 2N2222) + 1 kOhm base resistor + flyback diode,
one large push button, an RGB LED (common cathode) with resistors, a single-cell LiPo with a charger board, and a
100k/100k divider from the battery to GPIO 35. Pins are at the top of `nestwatch_buzzer.ino`.

## Build
1. Arduino IDE (or arduino-cli) with the ESP32 core v3.x.
2. Libraries: "WebSockets" (Markus Sattler) and "ArduinoJson" (Benoit Blanchon, v7).
3. Copy `config.example.h` to `config.h` and fill in Wi-Fi, the vision computer's address and the buzzer id
   (the same id as on the dashboard's Caregivers page).
4. Start the vision service with `--host 0.0.0.0` so the buzzer can reach it.

## Behaviour (spec table)
| State | Vibration | Light | Button |
| --- | --- | --- | --- |
| Idle | off | slow green blink | nothing |
| High alert | long pulses | fast orange | acknowledges |
| Medium alert | short pulses | slow orange | acknowledges |
| Someone else took it | stops | green | nothing |
| Disconnected | one long buzz | red | retries |

Several alerts at once: the most urgent and oldest is shown; each tap acknowledges one and the next comes up.
Without hardware, the vision service serves the same behaviour in a browser at `/buzzer-sim?id=buzzer-maria`.
