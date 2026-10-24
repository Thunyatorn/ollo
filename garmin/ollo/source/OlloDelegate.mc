import Toybox.Lang;
import Toybox.WatchUi;

// Buttons and touch: START (or a tap) = I'm on it, the menu (hold UP) = I'm on it / I can't respond,
// UP and DOWN (or swipes) = the other open alerts, BACK = leave ollo.
class OlloDelegate extends WatchUi.BehaviorDelegate {

    hidden var _client;

    function initialize(client) {
        BehaviorDelegate.initialize();
        _client = client;
    }

    function onSelect() as Boolean {
        _client.act("acknowledge");
        return true;
    }

    function onMenu() as Boolean {
        var alert = _client.current();
        if (alert == null || !alert["waiting"]) {
            return true;
        }
        var menu = new WatchUi.Menu2({ :title => "This alert" });
        menu.addItem(new WatchUi.MenuItem("I'm on it", null, :acknowledge, null));
        menu.addItem(new WatchUi.MenuItem("I can't respond", "Tell the next person now", :decline, null));
        WatchUi.pushView(menu, new OlloMenuDelegate(_client), WatchUi.SLIDE_UP);
        return true;
    }

    function onNextPage() as Boolean {
        _client.next(1);
        return true;
    }

    function onPreviousPage() as Boolean {
        _client.next(-1);
        return true;
    }
}

class OlloMenuDelegate extends WatchUi.Menu2InputDelegate {

    hidden var _client;

    function initialize(client) {
        Menu2InputDelegate.initialize();
        _client = client;
    }

    function onSelect(item as WatchUi.MenuItem) as Void {
        _client.act(item.getId() == :decline ? "decline" : "acknowledge");
        WatchUi.popView(WatchUi.SLIDE_DOWN);
    }
}
