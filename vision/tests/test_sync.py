import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from nestwatch_vision.sync import SpacetimeHttp, SpacetimeSink, rows

# a SQL reply shaped like the real one (captured from the local server and trimmed)
SQL_REPLY = {"schema": {"elements": [
    {"name": {"some": "id"}, "algebraic_type": {"String": []}},
    {"name": {"some": "polygon"}, "algebraic_type": {"Array": {"Product": {"elements": [
        {"name": {"some": "x"}, "algebraic_type": {"F64": []}}, {"name": {"some": "y"}, "algebraic_type": {"F64": []}}]}}}},
    {"name": {"some": "schedule"}, "algebraic_type": {"Product": {"elements": [
        {"name": {"some": "named"}, "algebraic_type": {"Sum": {"variants": [
            {"name": {"some": "some"}, "algebraic_type": {"String": []}}, {"name": {"some": "none"}, "algebraic_type": {"Product": {"elements": []}}}]}}},
        {"name": {"some": "start_min"}, "algebraic_type": {"Sum": {"variants": [
            {"name": {"some": "some"}, "algebraic_type": {"U16": []}}, {"name": {"some": "none"}, "algebraic_type": {"Product": {"elements": []}}}]}}}]}}}]},
    "rows": [["z_1", [[2.8, 1.9], [4.0, 1.9], [4.0, 3.0]], [[1, []], [0, 540]]]]}


def test_sql_rows_decode_options_products_and_arrays():
    (r,) = rows(SQL_REPLY)
    assert r == {"id": "z_1", "polygon": [{"x": 2.8, "y": 1.9}, {"x": 4.0, "y": 1.9}, {"x": 4.0, "y": 3.0}],
                 "schedule": {"named": None, "start_min": 540}}


class Fake:
    """A stand-in for Spacetime that records what it receives and can be told to fail."""
    def __init__(self):
        self.calls, self.mode = [], "ok"                      # ok | down | reject
        fake = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"])).decode()
                if fake.mode == "reject":
                    self.send_response(400); self.end_headers(); self.wfile.write(b"bad args"); return
                fake.calls.append((self.path.rsplit("/", 1)[-1], json.loads(body) if body.startswith(("[", "{")) else body, self.headers["Authorization"]))
                self.send_response(200); self.end_headers()

            def log_message(self, *a):
                pass
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def client(self):
        return SpacetimeHttp(f"http://127.0.0.1:{self.port}", "db", "TOKEN", timeout=1.0)

    def stop(self):
        self.srv.shutdown(); self.srv.server_close()


def test_sink_sends_exactly_what_the_reducers_expect():
    f = Fake()
    sink = SpacetimeSink(f.client(), retry_delay=0.05)
    sink.positions("main", [{"trackId": "t1", "kind": "child", "label": "1", "x": 1.0, "y": 2.0, "vx": 0.1, "vy": 0.0, "visible": True}])
    sink.event("t1", "zone_entry_predicted", "z_1", "high", 2.2, "evt_1")
    sink.event("t2", "zone_entry", "z_1", "high", None, "evt_2")
    assert sink.flush()
    sink.stop(); f.stop()
    by = {}
    for name, body, auth in f.calls:
        by.setdefault(name, []).append(body)
        assert auth == "Bearer TOKEN"
    assert by["update_positions"] == [["main", [["t1", "child", "1", 1.0, 2.0, 0.1, 0.0, True]]]]
    assert by["report_event"] == [["t1", "zone_entry_predicted", "z_1", "high", {"some": 2.2}, "evt_1"],
                                  ["t2", "zone_entry", "z_1", "high", {"none": []}, "evt_2"]]      # order kept


def test_events_wait_out_a_dead_server_and_arrive_in_order_when_it_returns():
    f = Fake()
    f.mode = "down"
    f.srv.shutdown()                                           # stop answering (connections now fail or hang)
    f.srv.server_close()
    client = SpacetimeHttp(f"http://127.0.0.1:{f.port}", "db", "T", timeout=0.3)
    sink = SpacetimeSink(client, retry_delay=0.05)
    for i in range(3):
        sink.event(f"t{i}", "zone_entry", "z", "high", None, f"e{i}")
    time.sleep(0.4)
    assert sink.pending() == 3 and not sink.online and sink.errors > 0       # kept, not lost
    g = Fake()                                                  # the server comes back (on a new port: point the client at it)
    client.base = f"http://127.0.0.1:{g.port}/v1/database/db"
    assert sink.flush(3.0)
    sink.stop(); g.stop()
    assert [c[1][0] for c in g.calls if c[0] == "report_event"] == ["t0", "t1", "t2"]
    assert sink.online


def test_a_call_the_server_refuses_is_dropped_so_it_cannot_block_the_queue():
    f = Fake()
    f.mode = "reject"
    sink = SpacetimeSink(f.client(), retry_delay=0.05)
    sink.event("bad", "zone_entry", "z", "high", None, "e0")
    time.sleep(0.3)
    assert sink.pending() == 0                                  # dropped after the refusal
    f.mode = "ok"
    sink.event("good", "zone_entry", "z", "high", None, "e1")
    assert sink.flush(2.0)
    sink.stop(); f.stop()
    assert [c[1][0] for c in f.calls if c[0] == "report_event"] == ["good"]


def test_only_the_newest_positions_are_kept_when_sending_is_slow():
    f = Fake()
    sink = SpacetimeSink(f.client(), retry_delay=0.05)
    sink._cv.acquire()                                          # hold the sender while three batches pile up
    for i in range(3):
        sink._positions = ("main", [{"trackId": f"t{i}", "kind": "child", "label": str(i), "x": 0, "y": 0, "vx": 0, "vy": 0, "visible": True}])
    sink._cv.notify(); sink._cv.release()
    assert sink.flush(2.0)
    sink.stop(); f.stop()
    sent = [c[1][1][0][0] for c in f.calls if c[0] == "update_positions"]
    assert sent == ["t2"]                                       # stale batches were replaced, not queued


def test_unsent_clips_lists_events_still_waiting():
    import requests

    class Down:
        def call(self, reducer, args):
            raise requests.ConnectionError("down")
    sink = SpacetimeSink(Down(), retry_delay=0.05)
    sink.event("t1", "zone_entry", "z_1", "high", None, "evt_1_t1")
    sink.reducer("camera_health", ["cam1", "online"])
    import time
    time.sleep(0.1)
    assert sink.unsent_clips() == {"evt_1_t1"}
    sink.stop()
