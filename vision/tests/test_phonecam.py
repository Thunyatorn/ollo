import threading
import time

import cv2
import numpy as np
from fastapi.testclient import TestClient

from nestwatch_vision.capture import LiveSource
from nestwatch_vision.phonecam import PhoneFeed, create_phone_app, ensure_cert

CODE = "pair123"


def jpeg(n=0, size=(120, 160)):
    img = np.full((*size, 3), 40, np.uint8)
    img[0, 0, 0] = n
    return cv2.imencode(".jpg", img)[1].tobytes()


def client():
    feed = PhoneFeed()
    return TestClient(create_phone_app(feed, CODE)), feed


def test_frame_needs_the_pairing_code():
    c, feed = client()
    assert c.post("/phone-frame", content=jpeg()).status_code == 403
    assert c.post("/phone-frame", content=jpeg(), headers={"x-pair-code": "nope"}).status_code == 403
    assert feed.received == 0
    r = c.post("/phone-frame", content=jpeg(), headers={"x-pair-code": CODE})
    assert r.status_code == 204 and feed.received == 1


def test_bad_uploads_are_refused():
    c, feed = client()
    h = {"x-pair-code": CODE}
    assert c.post("/phone-frame", content=b"hello", headers=h).status_code == 400
    assert c.post("/phone-frame", content=b"\xff\xd8not really a jpeg", headers=h).status_code == 400
    assert c.post("/phone-frame", content=b"\xff\xd8" + b"0" * 1_600_000, headers=h).status_code == 413
    assert feed.received == 0


def test_page_is_served_without_a_code():
    c, _ = client()
    r = c.get("/phone-cam")
    assert r.status_code == 200 and "getUserMedia" in r.text and r.headers["cache-control"] == "no-store"


def test_feed_gives_the_newest_frame_and_times_out_quietly():
    feed = PhoneFeed()
    assert feed.read(timeout=0.05) == (False, None)
    a, b = np.zeros((2, 2, 3), np.uint8), np.ones((2, 2, 3), np.uint8)
    feed.push(a); feed.push(b)                                         # a slow reader skips to the newest
    ok, img = feed.read(0.05)
    assert ok and img is b and feed.read(timeout=0.05) == (False, None)


def test_live_source_over_a_phone_feed_goes_offline_and_comes_back():
    c, feed = client()
    src = LiveSource("phone", open_fn=lambda: feed, reconnect_delay=0.05, offline_after=0.3).start()
    events = []

    def phone(n, gap):
        for i in range(n):
            c.post("/phone-frame", content=jpeg(i), headers={"x-pair-code": CODE})
            time.sleep(gap)
    t = threading.Thread(target=lambda: (phone(8, 0.05), time.sleep(0.6), phone(8, 0.05)))
    t.start()
    got = []
    for f in src.watch(lambda: events.append("offline"), lambda: events.append("online"), timeout=0.3):
        got.append(f.index)
        if len(got) >= 12:
            break
    src.stop(); t.join()
    assert events == ["offline", "online"] and got == sorted(set(got))


def test_certificate_is_reused_and_remade_for_a_new_address(tmp_path):
    from cryptography import x509
    d = str(tmp_path)
    cert1, key1 = ensure_cert(d, ["10.0.8.40"])
    pem1 = open(cert1, "rb").read()
    assert ensure_cert(d, ["10.0.8.40"]) == (cert1, key1) and open(cert1, "rb").read() == pem1      # same file, not remade
    cert2, _ = ensure_cert(d, ["10.0.8.77"])                                                        # the laptop moved networks
    san = x509.load_pem_x509_certificate(open(cert2, "rb").read()).extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert {"10.0.8.77", "127.0.0.1"} <= {str(i) for i in san.get_values_for_type(x509.IPAddress)}
    assert oct(__import__("os").stat(key1).st_mode & 0o777) == "0o600"
