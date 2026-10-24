import numpy as np
import pytest
from nestwatch_vision.calibration import CalibrationError, calibrate, fit_homography, jacobian, to_floor

# MATH.md section 1.5
IMG = np.array([[100, 100], [500, 120], [560, 400], [60, 380]], float)
FLOOR = np.array([[0, 0], [4, 0], [4, 3], [0, 3]], float)


def test_math_md_worked_example():
    H = fit_homography(IMG, FLOOR)
    expected = np.array([[0.01065, 0.00152, -1.21736], [-0.00073, 0.01450, -1.37778], [-0.00009, 0.00097, 1.0]])
    assert np.allclose(H, expected, atol=6e-6)
    assert np.allclose(to_floor(H, IMG), FLOOR, atol=1e-9)           # markers land exactly
    assert np.allclose(to_floor(H, (330, 250)), (2.20668, 1.65501), atol=1e-4)


def test_recovers_random_homographies_without_noise():
    rng = np.random.default_rng(0)
    for _ in range(50):
        Ht = np.eye(3) + rng.normal(0, 0.15, (3, 3))
        Ht[2, :2] *= 0.001                                          # mild perspective, like a real camera
        src = rng.uniform(0, 600, (8, 2))
        dst = to_floor(Ht, src)
        H = fit_homography(src, dst)
        test = rng.uniform(0, 600, (20, 2))
        assert np.allclose(to_floor(H, test), to_floor(Ht, test), atol=1e-8)


def test_matches_opencv():
    cv2 = pytest.importorskip("cv2")
    H = fit_homography(IMG, FLOOR)
    Hc, _ = cv2.findHomography(IMG, FLOOR)
    pts = np.array([[200, 200], [330, 250], [450, 350]], float)
    assert np.allclose(to_floor(H, pts), to_floor(Hc, pts), atol=1e-6)


def test_collinear_markers_rejected():
    with pytest.raises(CalibrationError):
        fit_homography([[0, 0], [100, 0], [200, 0], [300, 5]], FLOOR)


def test_four_points_cannot_catch_a_misclick_and_we_say_so():
    r = calibrate(IMG + [30, 0], FLOOR)             # sloppy clicks on all four
    assert r.rms_m < 1e-9 and r.holdout_m is None
    assert any("zero by construction" in w for w in r.warnings)


def test_six_points_with_one_bad_click_is_caught():
    pts_img = np.array([[100, 100], [500, 120], [560, 400], [60, 380], [300, 110], [310, 390]], float)
    H = fit_homography(IMG, FLOOR)
    pts_floor = to_floor(H, pts_img)
    clean = calibrate(pts_img + np.random.default_rng(1).normal(0, 1, pts_img.shape), pts_floor)
    assert clean.ok and clean.rms_m < 0.05
    bad_img = pts_img.copy()
    bad_img[4] += [40, -25]                          # one wild click
    bad = calibrate(bad_img, pts_floor)
    assert not bad.ok and bad.bad_point == 4


def test_noise_experiment_matches_math_md():
    """MATH 1.8: 1 px click noise on 4 points gives about 1 cm error at the middle of the room."""
    rng = np.random.default_rng(0)
    Ht = fit_homography(IMG, FLOOR)
    truth = to_floor(Ht, (330, 250))
    errs = [np.linalg.norm(to_floor(fit_homography(IMG + rng.normal(0, 1, (4, 2)), FLOOR), (330, 250)) - truth) for _ in range(1000)]
    assert 0.006 < np.sqrt(np.mean(np.square(errs))) < 0.016


def test_jacobian_matches_finite_difference():
    H = fit_homography(IMG, FLOOR)
    for px in [(80, 390), (330, 250), (120, 105)]:
        J = jacobian(H, px)
        h = 1e-4
        num = np.c_[(to_floor(H, (px[0] + h, px[1])) - to_floor(H, (px[0] - h, px[1]))) / (2 * h),
                    (to_floor(H, (px[0], px[1] + h)) - to_floor(H, (px[0], px[1] - h))) / (2 * h)]
        assert np.allclose(J, num, atol=1e-7)
    # about 1 cm per pixel, coarser far from the camera (MATH 1.8 table)
    near = np.linalg.svd(jacobian(H, (80, 390)))[1].max()
    far = np.linalg.svd(jacobian(H, (120, 105)))[1].max()
    assert 0.007 < near < 0.0095 and 0.012 < far < 0.0145 and far > near


def _six():
    img6 = np.vstack([IMG, [[300, 110], [310, 390]]])          # two check points at the wall midpoints
    return img6, to_floor(fit_homography(IMG, FLOOR), img6)


def test_normal_click_noise_is_not_rejected():
    rng = np.random.default_rng(10)
    img6, flr6 = _six()
    ok = np.mean([calibrate(img6 + rng.normal(0, 1, img6.shape), flr6).ok for _ in range(200)])
    assert ok >= 0.97                                           # 1 px of click noise passes


def test_one_wild_click_is_flagged_and_blamed_with_six_points():
    rng = np.random.default_rng(11)
    img6, flr6 = _six()
    flagged = blamed = n = 0
    for i in range(6):
        for _ in range(60):
            bad = img6 + rng.normal(0, 1, img6.shape)
            a = rng.uniform(0, 2 * np.pi)
            bad[i] += 40 * np.array([np.cos(a), np.sin(a)])      # 40 px = roughly 40 cm on the floor
            r = calibrate(bad, flr6)
            n += 1
            flagged += not r.ok
            blamed += (not r.ok) and r.bad_point == i
    assert flagged / n >= 0.97 and blamed / n >= 0.88


def test_five_points_may_flag_trouble_but_never_guess_which_point():
    """Five points have only one spare point, so a bad click is caught only about half the time (stress test:
    35% at 20 px, 58% at 40 px). When it is caught we must say so honestly and not name a point."""
    rng = np.random.default_rng(12)
    img6, flr6 = _six()
    flagged = 0
    for k in range(100):
        bad = img6[:5] + rng.normal(0, 1, (5, 2))
        bad[k % 5] += 40 * np.array([np.cos(k), np.sin(k)])
        r = calibrate(bad, flr6[:5])
        if not r.ok:
            flagged += 1
            assert r.bad_point is None and any("sixth point" in w for w in r.warnings)
    assert 10 <= flagged <= 95        # sometimes caught, not always: the reason the UI asks for 6 points
