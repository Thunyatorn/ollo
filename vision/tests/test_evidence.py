import gc
import os
import shutil
import subprocess
import time
import weakref
import cv2
import numpy as np
import pytest
import ultralytics
from nestwatch_vision import evidence
from nestwatch_vision.config import EvidenceConfig, PoseConfig
from nestwatch_vision.evidence import EvidenceRecorder, HeadTrail, head_box, pixelate
from nestwatch_vision.pose import Person

ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "weights")
POSE_W, FACE_W = os.path.join(ROOT, "yolo26s-pose.pt"), os.path.join(ROOT, "face_detection_yunet_2023mar.onnx")
ASSETS = os.path.join(os.path.dirname(ultralytics.__file__), "assets")
have_models = pytest.mark.skipif(not (os.path.exists(POSE_W) and os.path.exists(FACE_W)), reason="model files not downloaded")


def kp(**over):
    k = np.zeros((17, 3))
    for i, v in over.items():
        k[int(i)] = v
    return k


def person(box=(100, 100, 220, 500), **kps):
    return Person(np.array(box, float), 0.9, kp(**kps))


def detect(img, thr=0.3):
    """(x, y, w, h, score) for every face YuNet finds, at a threshold more sensitive than the usual 0.6."""
    det = cv2.FaceDetectorYN.create(FACE_W, "", (img.shape[1], img.shape[0]), thr, 0.3, 5000)
    _, f = det.detect(img)
    return [] if f is None else [(*(float(v) for v in x[:4]), float(x[14])) for x in f]


def iou(a, b):
    x1, y1, x2, y2 = max(a[0], b[0]), max(a[1], b[1]), min(a[0] + a[2], b[0] + b[2]), min(a[1] + a[3], b[1] + b[3])
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    return inter / (a[2] * a[3] + b[2] * b[3] - inter)


def clear_faces(img):
    return [f for f in detect(img, 0.3) if f[4] >= 0.6]            # the faces nobody would dispute in the original


def detail(a, n=16):
    """Energy left above a 16 x 16 grid: eyes, nose, mouth live here. (A Laplacian is fooled: pixel blocks make sharp edges of their own.)"""
    g = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY).astype(float)
    h, w = g.shape
    up = cv2.resize(cv2.resize(g, (n, n), interpolation=cv2.INTER_AREA), (w, h), interpolation=cv2.INTER_LINEAR)
    return float(np.mean((g - up) ** 2))


def surviving(original, blurred, scale=None):
    """Original faces that are still found in the blurred picture (a detection in the same place at a similar size),
    or that kept more than 5% of their fine detail (measured: 4 blocks keep at most 1.3%, 8 blocks keep 12%). Huge detections hovering over a blurred blob do not count: that is
    the detector imagining a face, not a face surviving."""
    scale = blurred.shape[1] / original.shape[1] if scale is None else scale     # the saved picture is 640 wide
    after = detect(blurred, 0.3)
    bad = []
    for (x, y, w, h, s) in clear_faces(original):
        box = (x * scale, y * scale, w * scale, h * scale)
        found = any(iou(box, d) > 0.3 and 0.5 < (d[2] * d[3]) / (box[2] * box[3]) < 2.0 for d in after)
        x1, y1, x2, y2 = (int(max(0, v)) for v in (box[0], box[1], box[0] + box[2], box[1] + box[3]))
        o = cv2.resize(original, (blurred.shape[1], blurred.shape[0]), interpolation=cv2.INTER_AREA)[y1:y2, x1:x2]
        kept = detail(blurred[y1:y2, x1:x2]) / max(detail(o), 1e-9)
        if found or kept > 0.05:
            bad.append((x, y, w, h, round(s, 2), found, round(kept, 3)))
    return bad


# ---- where the blur goes -----------------------------------------------------------------------
def test_head_box_is_centered_on_the_head_and_sized_from_the_ears():
    p = person(**{"3": (150, 130, 0.9), "4": (190, 130, 0.9), "0": (170, 135, 0.9)})
    x1, y1, x2, y2 = head_box(p, (720, 1280))
    assert abs((x1 + x2) / 2 - 170) < 3 and abs((y1 + y2) / 2 - 131) < 3
    assert (x2 - x1) == pytest.approx(1.25 * max(1.8 * 40, 0.17 * 400), abs=2)          # ears 40 px apart: 72; the floor is 68


def test_head_box_never_shrinks_below_a_childs_head_size():
    p = person(box=(100, 100, 220, 500), **{"0": (160, 140, 0.9)})                       # only the nose is visible
    x1, y1, x2, y2 = head_box(p, (720, 1280))
    assert (x2 - x1) >= 1.25 * 0.17 * 400 - 2


def test_without_any_head_keypoint_the_top_of_the_person_is_blurred():
    p = person(box=(100, 100, 220, 500))
    assert head_box(p, (720, 1280)) == (100, 100, 220, 220)                              # top 30% of the box


def test_head_box_stays_inside_the_picture():
    p = person(box=(-10, -5, 60, 300), **{"0": (5, 3, 0.9)})
    x1, y1, x2, y2 = head_box(p, (240, 320))
    assert x1 >= 0 and y1 >= 0 and x2 <= 320 and y2 <= 240


def test_pixelate_leaves_only_eight_by_eight_blocks():
    rng = np.random.default_rng(0)
    out = pixelate(rng.integers(0, 255, (80, 80, 3), dtype=np.uint8))
    blocks = {tuple(out[i * 10, j * 10]) for i in range(8) for j in range(8)}
    assert all((out[i * 10:(i + 1) * 10, j * 10:(j + 1) * 10] == out[i * 10, j * 10]).all() for i in range(8) for j in range(8))   # flat inside each block
    assert len(blocks) <= 64


def test_blurred_region_keeps_almost_no_detail_and_nothing_else_changes():
    rng = np.random.default_rng(1)
    img = rng.integers(0, 255, (200, 300, 3), dtype=np.uint8)
    p = person(box=(100, 20, 200, 190), **{"0": (150, 45, 0.9), "1": (140, 40, 0.9), "2": (160, 40, 0.9)})
    x1, y1, x2, y2 = head_box(p, img.shape)
    out = HeadTrail(1).blur(img, [(x1, y1, x2, y2)])
    assert detail(out[y1:y2, x1:x2]) < 0.02 * detail(img[y1:y2, x1:x2])                  # 98% of the fine detail is gone
    mask = np.ones(img.shape[:2], bool); mask[y1:y2, x1:x2] = False
    assert (out[mask] == img[mask]).all()                                                # everywhere else is untouched
    assert out is not img and (img != out).any()                                         # the caller's frame was not modified


# ---- real faces ----------------------------------------------------------------------------------
@have_models
@pytest.mark.parametrize("name", ["zidane.jpg", "bus.jpg"])
def test_real_faces_do_not_survive_the_blur(name):
    from nestwatch_vision.pose import PoseModel
    img = cv2.imread(os.path.join(ASSETS, name))
    people = PoseModel(PoseConfig(weights=POSE_W, device="cpu")).infer_all(img)
    assert len(clear_faces(img)) >= 2                                                     # the test photo really has clear faces
    rec = EvidenceRecorder(EvidenceConfig(face_model=FACE_W, dir=f"out/ev_face_{name}"))
    out = rec.blurred(img, people)
    rec.stop()
    assert surviving(img, out) == [], f"{name}: a face survived the blur"
    changed = (cv2.absdiff(cv2.resize(img, (out.shape[1], out.shape[0]), interpolation=cv2.INTER_AREA), out).sum(axis=2) > 0).mean()
    assert changed < (0.4 if name == "zidane.jpg" else 0.15)                               # heads, not the whole picture (zidane is a close-up of two heads)


@have_models
def test_the_face_detector_blurs_a_person_the_pose_model_never_saw():
    """The pose model finds no one in this call (people=[]), yet the faces must still be blurred: the face detector is the safety net."""
    img = cv2.imread(os.path.join(ASSETS, "zidane.jpg"))
    rec = EvidenceRecorder(EvidenceConfig(face_model=FACE_W, dir="out/ev_face_nopose"))
    out = rec.blurred(img, [])
    rec.stop()
    assert surviving(img, out) == []


def test_recording_refuses_to_start_without_a_face_detector(tmp_path):
    with pytest.raises(FileNotFoundError):
        EvidenceRecorder(EvidenceConfig(face_model=str(tmp_path / "missing.onnx"), dir=str(tmp_path / "ev")))


# ---- the buffer never holds a raw frame, and fails closed --------------------------------------
def test_the_recorder_keeps_no_reference_to_the_raw_frame():
    rec = EvidenceRecorder(EvidenceConfig(face_model=FACE_W, dir="out/ev_test_ref"))
    raw = np.full((240, 320, 3), 77, np.uint8)
    ref = weakref.ref(raw)
    assert rec.add(raw, 0.0, [])
    del raw
    gc.collect()
    assert ref() is None                                                                  # nothing in the recorder keeps the raw picture alive
    rec.stop()


def test_if_blurring_fails_the_frame_is_dropped_not_saved(monkeypatch):
    rec = EvidenceRecorder(EvidenceConfig(face_model=FACE_W, dir="out/ev_test_fail"))
    assert rec.add(np.zeros((240, 320, 3), np.uint8), 0.0, [])
    monkeypatch.setattr(HeadTrail, "blur", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert rec.add(np.ones((240, 320, 3), np.uint8) * 200, 1.0, []) is False
    assert rec.buffered_frames == 1 and rec.dropped_unblurred == 1                       # the failed frame is simply absent
    rec.stop()


def test_buffer_holds_only_a_few_seconds_and_stays_small():
    cfg = EvidenceConfig(face_model=FACE_W, dir="out/ev_test_ring", width=640)
    rec = EvidenceRecorder(cfg)
    rng = np.random.default_rng(2)
    base = cv2.resize(cv2.imread(os.path.join(ASSETS, "bus.jpg")), (1280, 720))
    for i in range(15 * 40):                                                              # 40 s of frames at 15 fps
        rec.add(base, i / 15, [])
    window = cfg.seconds_before + cfg.seconds_after + 1.0
    assert rec.buffered_frames <= int(window * 15) + 2
    assert rec.buffered_bytes < 20e6                                                      # compressed: about 6 MB, not the 104 MB of raw frames
    rec.stop()


# ---- clips and key frames ------------------------------------------------------------------------
def _ffprobe(path, entry):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", entry, "-of", "default=nw=1:nk=1", path],
                         capture_output=True, text=True).stdout.strip()
    return out


@have_models
def test_an_alert_produces_a_blurred_h264_clip_and_three_keyframes(tmp_path):
    from nestwatch_vision.pose import PoseModel
    cfg = EvidenceConfig(face_model=FACE_W, dir=str(tmp_path / "ev"))
    rec = EvidenceRecorder(cfg)
    img = cv2.imread(os.path.join(ASSETS, "zidane.jpg"))
    people = PoseModel(PoseConfig(weights=POSE_W, device="cpu")).infer_all(img)
    for i in range(15 * 14):                                                              # 14 s of the same photo at 15 fps
        t = i / 15
        rec.add(img, t, people)
        rec.tick(t)
        if i == 15 * 6:
            assert rec.trigger("evt_6000_t4", t)
    assert rec.wait(20.0) and rec.written == ["evt_6000_t4"]
    clip = tmp_path / "ev" / "clips" / "evt_6000_t4.mp4"
    assert clip.exists() and not list((tmp_path / "ev" / "clips").glob("*.part*"))       # whole, no half-written leftovers
    if shutil.which("ffprobe"):
        assert _ffprobe(str(clip), "stream=codec_name") == "h264"                         # plays in a browser
        assert 8.0 < float(_ffprobe(str(clip), "format=duration") or 0) < 12.0            # about 5 s before and 5 s after
        assert int(_ffprobe(str(clip), "stream=width")) == 640
    keys = sorted((tmp_path / "ev" / "keyframes").glob("evt_6000_t4_*.jpg"))
    assert len(keys) == 3
    for k in keys:
        frame = cv2.imread(str(k))
        assert frame is not None and surviving(img, frame) == []                           # every saved picture: faces gone
    cap = cv2.VideoCapture(str(clip)); ok, first = cap.read(); cap.release()
    assert ok and surviving(img, first) == []                                              # and so is the video
    rec.stop()


def test_clip_names_cannot_escape_the_folder(tmp_path):
    rec = EvidenceRecorder(EvidenceConfig(face_model=FACE_W, dir=str(tmp_path)))
    for bad in ["../../etc/passwd", "evt_1_t2/../../x", "evt_1_t2.mp4", "", "evt__t2", "a b"]:
        assert rec.trigger(bad, 0.0) is False
    assert rec.trigger("evt_12345_t7", 0.0) is True
    rec.stop()


def test_old_clips_are_deleted_and_new_ones_kept(tmp_path):
    rec = EvidenceRecorder(EvidenceConfig(face_model=FACE_W, dir=str(tmp_path), retention_days=7))
    old, new = tmp_path / "clips" / "evt_1_t1.mp4", tmp_path / "keyframes" / "evt_2_t1_1.jpg"
    old.write_bytes(b"x"); new.write_bytes(b"x")
    ten_days_ago = time.time() - 10 * 86400
    os.utime(old, (ten_days_ago, ten_days_ago))
    assert rec.cleanup() == 1 and not old.exists() and new.exists()
    rec.stop()
