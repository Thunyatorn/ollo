"""Every tunable number in one place. Defaults are the MATH.md section 14 start values; tune them on real footage."""
from dataclasses import dataclass


@dataclass
class TrackerConfig:
    sigma_a: float = 1.0           # process noise intensity, m/s^2 (MATH 3.2)
    init_vel_sigma: float = 1.0    # velocity uncertainty of a brand-new track, m/s (MATH 3.6)
    speed_cap: float = 3.0         # nobody in a playroom is faster; larger means a bad match (MATH 3.6)
    gate: float = 13.82            # chi-squared, 2 dof, 99.9% (MATH 4.3). 99% (9.21) split people into duplicate tracks
    confirm_hits: int = 3          # tentative -> confirmed after this many hits ...
    confirm_window: int = 5        # ... within this many frames (MATH 4.4)
    lost_timeout: float = 2.0      # confirmed track unmatched this long becomes lost (s)
    reid_window: float = 3.0       # a new track near a lost one within this time takes its ID (s)
    reid_distance: float = 1.0     # ... and within this distance (m) (MATH 4.5)


@dataclass
class PoseConfig:
    weights: str = "../weights/yolo26s-pose.pt"   # small model: 16 ms on this laptop's GPU, no duplicate boxes in the sample photo. A config value: yolo27 later is one line (MATH 12)
    device: str = "auto"           # auto = Apple GPU (mps) if there is one, else cpu
    imgsz: int = 640
    conf: float = 0.25             # person detection confidence for tracking
    blur_conf: float = 0.1         # lower bar used to decide who to blur (see PoseModel.infer_all)
    kp_floor: float = 0.3          # a keypoint below this is treated as missing, not as a point (MATH 2)


@dataclass
class PipelineConfig:
    sigma_px: float = 2.0                     # foot-point error in pixels; becomes meters through the Jacobian (MATH 1.8, 3.3)
    foot_sigma_m: tuple = (("ankles", 0.10), ("one_ankle", 0.15), ("box_bottom", 0.25))   # extra floor noise by foot quality
    room_margin_m: float = 0.5                # a foot mapped farther than this outside the room is a bad detection
    horizon_s: float = 3.0                    # (MATH 6)
    evidence_samples: int = 200
    shrink_c: float = 0.5                     # (MATH 6.4)
    cusum_k: float = 0.3                      # (MATH 7.5)
    cusum_h: float = 0.2
    cusum_cooldown_s: float = 60.0


@dataclass
class EvidenceConfig:
    dir: str = "evidence"          # clips/ and keyframes/ go under here (never leaves this computer except key frames to the worker)
    fps: float = 15.0
    seconds_before: float = 5.0
    seconds_after: float = 5.0
    width: int = 640               # frames are shrunk to this width after blurring
    keyframes: int = 3
    jpeg_quality: int = 80
    retention_days: float = 7.0    # clips older than this are deleted (MATH 9.3; your call)
    blur_conf: float = 0.1         # blur anyone the pose model is even slightly sure about; tracking uses the stricter 0.25
    head_floor: float = 0.17       # head box is never smaller than this fraction of the person's box height (children have big heads)
    trail_frames: int = 3          # also blur where heads were in the last frames, to cover motion and model latency
    face_model: str = "../weights/face_detection_yunet_2023mar.onnx"   # a second, independent check: blur any face it sees, pose or no pose
    face_thr: float = 0.25         # more sensitive than any check we run on the result (0.3), so the check cannot find what the blur skipped
    blur_cells: int = 4            # blocks across the blurred region. 8 was NOT enough: a face detector still found faces (MATH 9.2). 6 hides them, 4 is the safe default
    face_expand: float = 1.5       # grow each detected face box by this factor
