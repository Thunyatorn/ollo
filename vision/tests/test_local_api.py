import os
import threading
import time
import cv2
import numpy as np
import pytest
import ultralytics
from fastapi.testclient import TestClient
from nestwatch_vision.buzzers import BuzzerHub
from nestwatch_vision.calibration import fit_homography, to_floor
from nestwatch_vision.config import EvidenceConfig, PoseConfig
from nestwatch_vision.evidence import EvidenceRecorder
from nestwatch_vision.local_api import Control, Latest, VisionContext, create_app

ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "weights")
FACE_W, POSE_W = os.path.join(ROOT, "face_detection_yunet_2023mar.onnx"), os.path.join(ROOT, "yolo26s-pose.pt")
ASSETS = os.path.join(os.path.dirname(ultralytics.__file__), "assets")
LOCAL = ("127.0.0.1", 50000)
IMG6 = np.array([[100, 100], [500, 120], [560, 400], [60, 380], [300, 110], [310, 390]], float)
FLOOR6 = to_floor(fit_homography(IMG6[:4], [[0, 0], [4, 0], [4, 3], [0, 3]]), IMG6)


@pytest.fixture
def world(tmp_path):
    """A context like main.py builds, with a thread standing in for the camera loop."""
    applied, tags, reported = [], {12: None}, []
    control, stop = Control(), threading.Event()

    def loop():
        while not stop.is_set():
            control.run_pending(); time.sleep(0.005)
    threading.Thread(target=loop, daemon=True).start()

    def tag(tid, name):
        if tid in tags:
            tags[tid] = name
            return True
        return False
    rec = EvidenceRecorder(EvidenceConfig(face_model=FACE_W, dir=str(tmp_path / "ev")))
    ctx = VisionContext("cam1", control, Latest(), BuzzerHub(), rec, set_homography=applied.append, tag_adult=tag,
                        report_tag=lambda t, c: reported.append((t, c)), health=lambda: {"fps": 12.0, "spacetime_online": True})
    yield ctx, TestClient(create_app(ctx), client=LOCAL), applied, tags, reported
    stop.set(); rec.stop()


def test_health(world):
    ctx, c, *_ = world
    r = c.get("/health")
    assert r.status_code == 200 and r.json() == {"camera": "cam1", "fps": 12.0, "spacetime_online": True}


def test_requests_from_outside_the_local_network_are_refused(world):
    ctx, _, *_ = world
    outsider = TestClient(create_app(ctx), client=("8.8.8.8", 50000))
    assert outsider.get("/health").status_code == 403
    with pytest.raises(Exception):
        with outsider.websocket_connect("/buzzer") as ws:
            ws.send_json({"type": "hello", "buzzer_id": "x"}); ws.receive_json()
    for ip in ("192.168.1.20", "10.0.0.7", "172.20.1.1", "::1"):
        assert TestClient(create_app(ctx), client=(ip, 1)).get("/health").status_code == 200


def test_only_pages_on_the_local_network_may_call_it_from_a_browser(world):
    _, c, *_ = world
    ok = c.get("/health", headers={"Origin": "http://127.0.0.1:5173"})
    assert ok.headers.get("access-control-allow-origin") == "http://127.0.0.1:5173"
    assert c.get("/health", headers={"Origin": "http://192.168.1.30:5173"}).headers.get("access-control-allow-origin")
    assert "access-control-allow-origin" not in c.get("/health", headers={"Origin": "https://evil.example"}).headers


# ---- snapshot ----------------------------------------------------------------------------------
def test_snapshot_waits_for_a_frame_and_knows_its_camera(world):
    _, c, *_ = world
    assert c.get("/snapshot/cam1").status_code == 503
    assert c.get("/snapshot/cam9").status_code == 404


@pytest.mark.skipif(not (os.path.exists(FACE_W) and os.path.exists(POSE_W)), reason="model files not downloaded")
def test_snapshot_is_full_size_and_has_no_recognisable_face(world):
    from tests.test_evidence import surviving
    from nestwatch_vision.pose import PoseModel
    ctx, c, *_ = world
    img = cv2.imread(os.path.join(ASSETS, "zidane.jpg"))
    ctx.latest.set(img, PoseModel(PoseConfig(weights=POSE_W, device="cpu")).infer_all(img), 1.0)
    r = c.get("/snapshot/cam1")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    snap = cv2.imdecode(np.frombuffer(r.content, np.uint8), cv2.IMREAD_COLOR)
    assert snap.shape == img.shape                                     # same pixels as the pipeline: clicks map 1:1
    assert surviving(img, snap) == []                                  # and no face survives


def test_no_snapshot_at_all_when_the_blur_is_unavailable(world):
    ctx, *_ = world
    ctx.recorder = None
    ctx.latest.set(np.zeros((48, 64, 3), np.uint8), [], 0.0)
    r = TestClient(create_app(ctx), client=LOCAL).get("/snapshot/cam1")
    assert r.status_code == 503 and "unblurred" in r.text


# ---- calibrate ---------------------------------------------------------------------------------
def test_a_good_calibration_is_returned_and_applied(world):
    _, c, applied, *_ = world
    r = c.post("/calibrate/cam1", json={"image_points": IMG6.tolist(), "floor_points": FLOOR6.tolist()})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] and body["reprojection_error"] < 1e-6 and len(body["homography"]) == 3
    assert len(applied) == 1 and np.allclose(applied[0], np.array(body["homography"]))     # the pipeline got it


def test_a_bad_click_is_refused_named_and_not_applied(world):
    _, c, applied, *_ = world
    bad = IMG6.copy(); bad[4] += [40, -25]
    r = c.post("/calibrate/cam1", json={"image_points": bad.tolist(), "floor_points": FLOOR6.tolist()})
    assert r.status_code == 422 and r.json()["bad_point"] == 4 and r.json()["warnings"]
    assert applied == []


def test_bad_calibration_input_is_rejected_clearly(world):
    ctx, c, applied, *_ = world
    line = [[0, 0], [100, 0], [200, 0], [300, 5]]
    assert c.post("/calibrate/cam1", json={"image_points": line, "floor_points": [[0, 0], [4, 0], [4, 3], [0, 3]]}).status_code == 422
    assert c.post("/calibrate/cam1", json={"image_points": [[1, 2]], "floor_points": [[1, 2]]}).status_code == 422
    assert c.post("/calibrate/cam1", json={"image_points": "nope", "floor_points": []}).status_code == 422
    ctx.latest.set(np.zeros((480, 640, 3), np.uint8), [], 0.0)
    far = IMG6.copy(); far[0] = [900, 100]                              # outside a 640 x 480 picture
    assert c.post("/calibrate/cam1", json={"image_points": far.tolist(), "floor_points": FLOOR6.tolist()}).status_code == 422
    assert c.post("/calibrate/cam2", json={"image_points": IMG6.tolist(), "floor_points": FLOOR6.tolist()}).status_code == 404
    assert applied == []


# ---- tag an adult ------------------------------------------------------------------------------
def test_tagging_an_adult_runs_on_the_camera_loop_and_tells_spacetime(world):
    _, c, _, tags, reported = world
    r = c.post("/tag-adult", json={"track_id": "t12", "caregiver_id": "c_maria", "caregiver_name": "Maria"})
    assert r.status_code == 200 and tags[12] == "Maria" and reported == [("t12", "c_maria")]
    assert c.post("/tag-adult", json={"track_id": "t99", "caregiver_id": "c_maria", "caregiver_name": "Maria"}).status_code == 404
    assert c.post("/tag-adult", json={"track_id": "abc", "caregiver_id": "c", "caregiver_name": "M"}).status_code == 422
    assert reported == [("t12", "c_maria")]


# ---- clips and key frames ----------------------------------------------------------------------
def test_clips_are_served_with_seeking_and_names_cannot_escape(world):
    ctx, c, *_ = world
    path = os.path.join(ctx.recorder.clips_dir, "evt_100_t4.mp4")
    open(path, "wb").write(b"\x00" * 5000)
    open(os.path.join(ctx.recorder.keyframes_dir, "evt_100_t4_2.jpg"), "wb").write(b"\xff\xd8jpeg")
    r = c.get("/clips/evt_100_t4")
    assert r.status_code == 200 and r.headers["content-type"] == "video/mp4" and len(r.content) == 5000
    part = c.get("/clips/evt_100_t4", headers={"Range": "bytes=100-199"})
    assert part.status_code == 206 and len(part.content) == 100        # a browser can seek in the clip
    assert c.get("/keyframes/evt_100_t4/2").status_code == 200
    for bad in ["evt_999_t1", "..%2F..%2Fetc%2Fpasswd", "evt_100_t4.mp4", "evt_100_t4%00"]:
        assert c.get(f"/clips/{bad}").status_code == 404
    assert c.get("/keyframes/evt_100_t4/0").status_code == 404 and c.get("/keyframes/evt_100_t4/3").status_code == 404


def test_buzzer_websocket_is_wired(world):
    ctx, c, *_ = world
    with c.websocket_connect("/buzzer") as ws:
        ws.send_json({"type": "hello", "buzzer_id": "buzzer-maria", "battery": 0.7})
        end = time.time() + 2
        while ctx.hub.connected() != ["buzzer-maria"] and time.time() < end:
            time.sleep(0.01)
        assert ctx.hub.send("buzzer-maria", {"type": "buzz", "alert_id": "a_1", "severity": "high"})
        assert ws.receive_json()["type"] == "buzz"
