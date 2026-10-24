import Toybox.Graphics;
import Toybox.Lang;
import Toybox.WatchUi;

// One screen: the alert that needs you (what, which child, where, what happens next), or "All clear".
// Colours follow the dashboard: red for high, amber for medium, blue for low, sage when all is well.
class OlloView extends WatchUi.View {

    hidden var _client;

    function initialize(client) {
        View.initialize();
        _client = client;
    }

    function onShow() as Void {
        _client.start();
    }

    function onHide() as Void {
        _client.stop();
    }

    function colour(sev) as Number {
        if (sev != null && sev.equals("high")) {
            return 0xE07A6B;
        }
        if (sev != null && sev.equals("medium")) {
            return 0xD8B17A;
        }
        if (sev != null && sev.equals("low")) {
            return 0x8FB3D9;
        }
        return 0xBBC9AA;
    }

    function onUpdate(dc as Graphics.Dc) as Void {
        var w = dc.getWidth();
        var h = dc.getHeight();
        var cx = w / 2;
        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_BLACK);
        dc.clear();
        var centre = Graphics.TEXT_JUSTIFY_CENTER | Graphics.TEXT_JUSTIFY_VCENTER;

        var flash = _client.flashText();
        var alert = _client.current();
        var state = _client.state;

        if (state == null || (alert == null && _client.message.length() > 0)) {
            dc.setColor(0xBBC9AA, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, h * 0.30, Graphics.FONT_MEDIUM, "ollo", centre);
            dc.setColor(0xD1D5DB, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, h * 0.58, Graphics.FONT_XTINY, _client.message, centre);
            return;
        }

        if (alert == null) {
            dc.setColor(0xBBC9AA, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, h * 0.38, Graphics.FONT_MEDIUM, "All clear", centre);
            dc.setColor(0x9AA3AD, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, h * 0.58, Graphics.FONT_XTINY, "Paired as " + state["me"], centre);
            if (flash != null) {
                dc.drawText(cx, h * 0.74, Graphics.FONT_XTINY, flash, centre);
            }
            return;
        }

        var sev = alert["sev"];
        var c = colour(sev);
        var waiting = alert["waiting"];

        // a coloured ring around the edge while the alert is waiting
        if (waiting) {
            dc.setColor(c, Graphics.COLOR_TRANSPARENT);
            dc.setPenWidth(6);
            dc.drawCircle(cx, h / 2, (w < h ? w : h) / 2 - 4);
            dc.setPenWidth(1);
        }

        var count = _client.alerts().size();
        dc.setColor(c, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, h * 0.17, Graphics.FONT_XTINY,
            sev.toUpper() + (count > 1 ? "  " + (_client.selected + 1) + "/" + count : ""), centre);

        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, h * 0.34, Graphics.FONT_SMALL, alert["what"], centre);
        var where = alert["where"];
        var place = "Child " + alert["child"] + ((where != null && where.length() > 0) ? " - " + where : "");
        dc.drawText(cx, h * 0.48, Graphics.FONT_XTINY, place, centre);

        dc.setColor(0x9AA3AD, Graphics.COLOR_TRANSPARENT);
        var status;
        if (!waiting) {
            status = "Handled by " + alert["owner"];
        } else if (alert["next_in"] != null && alert["next"] != null) {
            status = alert["next"] + " in " + alert["next_in"] + "s";
        } else {
            status = "Needs you";
        }
        dc.drawText(cx, h * 0.60, Graphics.FONT_XTINY, status, centre);

        if (flash != null) {
            dc.setColor(0xBBC9AA, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, h * 0.76, Graphics.FONT_XTINY, flash, centre);
        } else if (waiting) {
            dc.setColor(0xD8B17A, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, h * 0.74, Graphics.FONT_XTINY, "START: I'm on it", centre);
            dc.setColor(0x7C858E, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, h * 0.84, Graphics.FONT_XTINY, "Hold UP: more", centre);
        }
    }
}
