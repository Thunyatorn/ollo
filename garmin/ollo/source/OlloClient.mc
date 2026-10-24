import Toybox.Attention;
import Toybox.Communications;
import Toybox.Lang;
import Toybox.System;
import Toybox.Timer;
import Toybox.WatchUi;

// Talks to the ollo worker while the app is open: checks every 3 s, buzzes for a waiting alert (long pulses for high,
// short for medium, the same patterns as the wrist buzzer) and sends "I'm on it" / "I can't respond".
class OlloClient {

    var state = null;            // the last /watch/state answer (a Dictionary)
    var message = "Connecting";  // shown when there is no state to show
    var flash = null;            // a short reply after a button press, e.g. "You have it"
    var selected = 0;            // which alert is on screen

    hidden var _timer;
    hidden var _busy = false;
    hidden var _lastBuzzId = null;
    hidden var _lastBuzzAt = 0;
    hidden var _flashUntil = 0;

    function initialize() {
        _timer = new Timer.Timer();
    }

    function start() as Void {
        poll();
        _timer.start(method(:poll), 3000, true);
    }

    function stop() as Void {
        _timer.stop();
    }

    function poll() as Void {
        if (_busy) {
            return;
        }
        var url = OlloConfig.serverUrl();
        var code = OlloConfig.pairingCode();
        if (url == null || code == null) {
            message = "Add the server and\npairing code in settings";
            WatchUi.requestUpdate();
            return;
        }
        _busy = true;
        Communications.makeWebRequest(url + "/watch/state", null, {
            :method => Communications.HTTP_REQUEST_METHOD_GET,
            :headers => OlloConfig.headers(code, false),
            :responseType => Communications.HTTP_RESPONSE_CONTENT_TYPE_JSON
        }, method(:onState));
    }

    function onState(responseCode as Number, data as Dictionary or String or Null) as Void {
        _busy = false;
        if (responseCode == 200 && data instanceof Dictionary) {
            state = data;
            message = "";
            buzzIfNeeded();
        } else {
            message = describe(responseCode);
        }
        WatchUi.requestUpdate();
    }

    function describe(responseCode as Number) as String {
        if (responseCode == 401) {
            return "Code not known.\nPair the watch again.";
        }
        if (responseCode == 429) {
            return "Too many tries.\nWait a minute.";
        }
        if (responseCode == -104) {
            return "No phone connection.\nOpen Garmin Connect.";
        }
        if (responseCode < 0) {
            return "Cannot reach ollo\n(" + responseCode + ")";
        }
        return "ollo error " + responseCode;
    }

    function alerts() as Array {
        if (state == null) {
            return [];
        }
        var list = state["alerts"];
        return list instanceof Array ? list as Array : [];
    }

    function current() {
        var list = alerts();
        if (list.size() == 0) {
            return null;
        }
        if (selected >= list.size() || selected < 0) {
            selected = 0;
        }
        return list[selected];
    }

    function next(step as Number) as Void {
        var n = alerts().size();
        if (n > 0) {
            selected = (selected + step + n) % n;
            WatchUi.requestUpdate();
        }
    }

    // A new waiting alert buzzes at once; the same one again every 10 s (high) or 20 s (medium) until someone has it.
    function buzzIfNeeded() as Void {
        var buzz = state["buzz"];
        var list = alerts();
        if (buzz == null || list.size() == 0) {
            _lastBuzzId = null;
            return;
        }
        var high = buzz.equals("high");
        var id = list[0]["id"];
        var now = System.getTimer();
        if (_lastBuzzId == null || !_lastBuzzId.equals(id) || now - _lastBuzzAt >= (high ? 10000 : 20000)) {
            if (_lastBuzzId == null || !_lastBuzzId.equals(id)) {
                selected = 0;                                  // jump to the new alert
            }
            _lastBuzzId = id;
            _lastBuzzAt = now;
            vibrate(high);
        }
    }

    function vibrate(high as Boolean) as Void {
        if (!(Attention has :vibrate)) {
            return;
        }
        if (high) {
            Attention.vibrate([new Attention.VibeProfile(100, 700), new Attention.VibeProfile(0, 300),
                               new Attention.VibeProfile(100, 700), new Attention.VibeProfile(0, 300),
                               new Attention.VibeProfile(100, 700)]);
        } else {
            Attention.vibrate([new Attention.VibeProfile(70, 200), new Attention.VibeProfile(0, 400),
                               new Attention.VibeProfile(70, 200)]);
        }
    }

    function flashText() {
        return (flash != null && System.getTimer() < _flashUntil) ? flash : null;
    }

    function act(decision as String) as Void {
        var alert = current();
        var url = OlloConfig.serverUrl();
        var code = OlloConfig.pairingCode();
        if (alert == null || url == null || code == null) {
            return;
        }
        if (!alert["waiting"]) {
            show("Already handled");
            return;
        }
        Communications.makeWebRequest(url + "/watch/act", { "alert_id" => alert["id"], "decision" => decision }, {
            :method => Communications.HTTP_REQUEST_METHOD_POST,
            :headers => OlloConfig.headers(code, true),
            :responseType => Communications.HTTP_RESPONSE_CONTENT_TYPE_JSON
        }, method(:onAct));
        show("Sending");
    }

    function onAct(responseCode as Number, data as Dictionary or String or Null) as Void {
        if (responseCode == 200 && data instanceof Dictionary) {
            show((data as Dictionary)["say"]);
            _lastBuzzId = null;
        } else {
            show(responseCode == 409 ? "Not recorded" : describe(responseCode));
        }
        poll();
    }

    function show(text) as Void {
        flash = text;
        _flashUntil = System.getTimer() + 4000;
        WatchUi.requestUpdate();
    }
}
