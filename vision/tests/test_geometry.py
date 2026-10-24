import numpy as np
import pytest
from shapely.geometry import Point, Polygon as SPoly
from nestwatch_vision.geometry import distance_to_polygon, entry_times, points_in_polygon, signed_distance, time_to_entry

STAIRS = [(2.8, 1.9), (4, 1.9), (4, 3), (2.8, 3)]


def test_point_in_polygon_matches_shapely():
    rng = np.random.default_rng(0)
    for _ in range(30):
        # random simple polygon: points sorted by angle around a center
        ang = np.sort(rng.uniform(0, 2 * np.pi, 7))
        rad = rng.uniform(0.5, 2, 7)
        poly = np.c_[2 + rad * np.cos(ang), 1.5 + rad * np.sin(ang)]
        pts = rng.uniform(-1, 5, (200, 2))
        sp = SPoly(poly)
        assert np.array_equal(points_in_polygon(pts, poly), [sp.contains(Point(p)) for p in pts])


def test_distance_and_sign_match_shapely():
    rng = np.random.default_rng(1)
    pts = rng.uniform(0, 5, (100, 2))
    sp = SPoly(STAIRS)
    d = distance_to_polygon(pts, STAIRS)
    assert np.allclose(d, [sp.exterior.distance(Point(p)) for p in pts], atol=1e-9)
    s = signed_distance(pts, STAIRS)
    assert np.array_equal(s < 0, [sp.contains(Point(p)) for p in pts])


def test_time_to_entry_math_md_example():
    # MATH 5.3: child at (1.8, 2.4) moving (0.45, 0) m/s toward the stairs
    assert time_to_entry((1.8, 2.4), (0.45, 0), STAIRS) == pytest.approx(1.0 / 0.45)


def test_time_to_entry_cases():
    assert time_to_entry((3.2, 2.4), (0.3, 0.1), STAIRS) == 0.0            # already inside
    assert time_to_entry((1.0, 0.6), (-0.3, -0.2), STAIRS) == np.inf       # walking away
    assert time_to_entry((1.8, 1.2), (0.45, 0), STAIRS) == np.inf          # passing parallel, never enters
    assert time_to_entry((1.8, 2.4), (0, 0), STAIRS) == np.inf             # standing still


def test_time_to_entry_agrees_with_stepping_the_path():
    rng = np.random.default_rng(2)
    P = rng.uniform(0, 4, (300, 2))
    V = rng.uniform(-1, 1, (300, 2))
    t = entry_times(P, V, STAIRS)
    for p, v, ti in zip(P, V, t):
        steps = np.arange(0, 6, 0.002)
        path = p + steps[:, None] * v
        hit = points_in_polygon(path, STAIRS)
        first = steps[np.argmax(hit)] if hit.any() else np.inf
        if np.isinf(ti):
            assert not hit.any()
        else:
            assert abs(first - ti) < 0.01 or ti > 6


def test_vectorized_equals_scalar():
    P = np.array([[1.8, 2.4], [3.2, 2.4], [1.0, 0.6]])
    V = np.array([[0.45, 0], [0.3, 0.1], [-0.3, -0.2]])
    assert np.array_equal(entry_times(P, V, STAIRS), [time_to_entry(p, v, STAIRS) for p, v in zip(P, V)])
