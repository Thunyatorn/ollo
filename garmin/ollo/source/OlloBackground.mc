import Toybox.Background;
import Toybox.Communications;
import Toybox.Lang;
import Toybox.System;

// Runs while ollo is closed, at most every 5 minutes (Garmin's limit). If an alert is waiting for this caregiver it
// asks the watch to open ollo; the watch shows the prompt with a vibration, and the open app then buzzes properly.
(:background)
class OlloBackground extends System.ServiceDelegate {

    function initialize() {
        ServiceDelegate.initialize();
    }

    function onTemporalEvent() as Void {
        var url = OlloConfig.serverUrl();
        var code = OlloConfig.pairingCode();
        if (url == null || code == null) {
            Background.exit(null);
            return;
        }
        Communications.makeWebRequest(url + "/watch/state", null, {
            :method => Communications.HTTP_REQUEST_METHOD_GET,
            :headers => OlloConfig.headers(code, false),
            :responseType => Communications.HTTP_RESPONSE_CONTENT_TYPE_JSON
        }, method(:onState));
    }

    function onState(responseCode as Number, data as Dictionary or String or Null) as Void {
        if (responseCode == 200 && data instanceof Dictionary && (data as Dictionary)["buzz"] != null) {
            if (Background has :requestApplicationWake) {
                Background.requestApplicationWake("ollo: an alert needs you");
            }
        }
        Background.exit(null);
    }
}
