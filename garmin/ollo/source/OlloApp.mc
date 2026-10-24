import Toybox.Application;
import Toybox.Background;
import Toybox.Lang;
import Toybox.System;
import Toybox.Time;
import Toybox.WatchUi;

// ollo on a Garmin watch: buzzes when an alert needs this caregiver and acknowledges it with one press.
// Open, it checks the worker every 3 s (OlloClient). Closed, Garmin allows a background check at most every
// 5 minutes (OlloBackground), which asks the watch to open ollo when an alert is waiting.
(:background)
class OlloApp extends Application.AppBase {

    function initialize() {
        AppBase.initialize();
    }

    function onStart(state) {
    }

    function onStop(state) {
    }

    function getInitialView() {
        if (Background has :registerForTemporalEvent) {
            Background.registerForTemporalEvent(new Time.Duration(5 * 60));
        }
        var client = new OlloClient();
        return [new OlloView(client), new OlloDelegate(client)];
    }

    function getServiceDelegate() {
        return [new OlloBackground()];
    }

    function onSettingsChanged() {
        WatchUi.requestUpdate();
    }
}
