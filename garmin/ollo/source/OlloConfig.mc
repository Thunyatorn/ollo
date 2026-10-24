import Toybox.Application;
import Toybox.Communications;
import Toybox.Lang;

// The two settings (server address and pairing code) and the request headers, shared by the app and the background check.
(:background)
module OlloConfig {

    function setting(key as String) as String? {
        var value = Application.Properties.getValue(key);
        if (value == null || !(value instanceof String)) {
            return null;
        }
        var text = value as String;
        return text.length() == 0 ? null : text;
    }

    // "https://example.ngrok-free.dev/" -> "https://example.ngrok-free.dev"
    function serverUrl() as String? {
        var url = setting("ServerUrl");
        if (url == null) {
            return null;
        }
        while (url.length() > 0 && url.substring(url.length() - 1, url.length()).equals("/")) {
            url = url.substring(0, url.length() - 1);
        }
        return url;
    }

    function pairingCode() as String? {
        return setting("PairingCode");
    }

    // ngrok-skip-browser-warning: the free ngrok address otherwise answers some requests with a warning page
    function headers(code as String, withJson as Boolean) as Dictionary {
        var h = { "X-Watch-Key" => code, "ngrok-skip-browser-warning" => "1" };
        if (withJson) {
            h["Content-Type"] = Communications.REQUEST_CONTENT_TYPE_JSON;
        }
        return h;
    }
}
