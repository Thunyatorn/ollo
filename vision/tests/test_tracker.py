import numpy as np
from nestwatch_vision.tracker import Detection, Tracker

DT, SM = 1 / 8, 0.12
R = np.eye(2) * SM ** 2


def dets(points, rng, drop=()):
    return [Detection(np.asarray(p) + rng.normal(0, SM, 2), R, {"truth": i}) for i, p in enumerate(points) if i not in drop]


def run(paths, rng, drop_frames=None, extra=None, tracker=None):
    """paths: list of functions t -> (x, y). Returns {truth index: set of track ids seen}, tracker."""
    tr = tracker or Tracker()
    ids = {i: [] for i in range(len(paths))}
    for k in range(int(10 / DT)):
        t = k * DT
        pts = [p(t) for p in paths]
        drop = (drop_frames or {}).get(k, ())
        detections = dets(pts, rng, drop)
        if extra and k in extra:
            detections.append(Detection(np.asarray(extra[k]), R, {"truth": "ghost"}))
        for track in tr.step(detections, t):
            if track.visible and "truth" in track.meta and track.meta["truth"] != "ghost":
                ids[track.meta["truth"]].append(track.id)
    return ids, tr


def _crossing(angle_deg, speed, delay=0.0):
    """Two people whose straight paths cross at (2.0, 1.5); person B arrives `delay` seconds after A."""
    a = np.radians(angle_deg / 2)
    v = np.array([np.cos(a), np.sin(a)]) * speed
    w = np.array([np.cos(a), -np.sin(a)]) * speed
    c, tc = np.array([2.0, 1.5]), 3.0
    return [lambda t: tuple(c + (t - tc) * v), lambda t: tuple(c + (t - tc - delay) * w)]


def _swapped(paths, seed, t_before=1.8, t_after=6.5):
    """True if the two people exchanged IDs for good (a one-frame mix-up while they overlap does not count)."""
    rng = np.random.default_rng(seed)
    tr, pre, post = Tracker(), {}, {}
    for k in range(int((t_after + 1.0) / DT)):
        t = k * DT
        out = tr.step(dets([p(t) for p in paths], rng), t)
        ids = {x.meta["truth"]: x.id for x in out if x.visible}
        if abs(t - t_before) < DT / 2:
            pre = ids
        if abs(t - t_after) < DT / 2:
            post = ids
    if len(pre) < 2 or len(post) < 2:
        return None
    return pre[0] == post[1] and pre[1] == post[0]


def test_single_walker_keeps_one_id_and_never_splits_into_duplicates():
    paths = [lambda t: (0.5 + 0.4 * t, 1.5 + 0.2 * np.sin(t))]
    for seed in range(60):
        rng = np.random.default_rng(seed)
        tr, seen = Tracker(), set()
        for k in range(int(10 / DT)):
            out = tr.step(dets([paths[0](k * DT)], rng), k * DT)
            assert len(out) <= 1                                   # never two tracks for one person
            seen |= {x.id for x in out}
        assert len(seen) == 1                                      # the gate used to split people (MATH 4.3)


def test_crossing_swap_rates_stay_within_the_measured_limits():
    """Two people reaching the same spot at the same instant cannot always be told apart (MATH 4.6).
    Measured over 40 seeds: 0% at 90 deg and 1.0 m/s, 5% at 60 deg and 1.0, 12% at 90 deg and 0.5, 30% at 60 deg and 0.5.
    These limits fail if tracking gets worse; they do not claim crossings are solved."""
    for angle, speed, limit in [(90, 1.0, 0.08), (60, 1.0, 0.15), (90, 0.5, 0.25), (60, 0.5, 0.45)]:
        res = [r for r in (_swapped(_crossing(angle, speed), s) for s in range(40)) if r is not None]
        assert len(res) >= 35
        assert np.mean(res) <= limit, (angle, speed, np.mean(res))


def test_people_who_reach_the_crossing_at_different_times_are_never_swapped():
    res = [r for r in (_swapped(_crossing(60, 0.5, delay=1.5), s, t_after=7.0) for s in range(40)) if r is not None]
    assert len(res) >= 35 and not any(res)


def test_one_frame_ghost_never_becomes_a_track():
    rng = np.random.default_rng(4)
    ids, tr = run([lambda t: (1.0, 1.0)], rng, extra={20: (3.0, 2.0), 50: (0.5, 2.5), 80: (3.5, 0.5)})
    assert len({t.id for t in tr.tracks}) == 1                # only the real person exists
    assert len(set(ids[0])) == 1


def test_short_dropouts_keep_the_id():
    rng = np.random.default_rng(5)
    drop = {k: (0,) for k in list(range(20, 24)) + list(range(50, 53))}      # 0.5 s and 0.4 s gaps
    ids, _ = run([lambda t: (0.5 + 0.3 * t, 1.5)], rng, drop_frames=drop)
    assert len(set(ids[0])) == 1


def test_lost_after_two_seconds_and_reported():
    rng = np.random.default_rng(6)
    tr = Tracker()
    for k in range(30):                                       # 3.75 s of being seen
        tr.step(dets([(1.0, 1.0)], rng), k * DT)
    lost_at = None
    for k in range(30, 80):                                   # then gone
        tr.step([], k * DT)
        if tr.newly_lost and lost_at is None:
            lost_at = (k - 29) * DT
    assert lost_at is not None and 2.0 < lost_at <= 2.0 + DT + 1e-9
    assert not [t for t in tr.tracks if t.status == "confirmed"]


def test_reappearing_person_gets_old_id_and_adult_tag_back():
    rng = np.random.default_rng(7)
    tr = Tracker()
    for k in range(30):
        tr.step(dets([(1.0, 1.0)], rng), k * DT)
    original = tr.tracks[0]
    original.tag = "Maria"
    oid = original.id
    for k in range(30, 52):                                   # unseen for 2.75 s: lost
        tr.step([], k * DT)
    assert not tr.tracks and tr.lost
    for k in range(52, 62):                                   # back, 0.5 m from where she vanished
        tracks = tr.step(dets([(1.5, 1.0)], rng), k * DT)
    assert len(tracks) == 1 and tracks[0].id == oid and tracks[0].tag == "Maria"


def test_far_away_reappearance_is_a_new_person():
    rng = np.random.default_rng(8)
    tr = Tracker()
    for k in range(30):
        tr.step(dets([(1.0, 1.0)], rng), k * DT)
    oid = tr.tracks[0].id
    for k in range(30, 52):
        tr.step([], k * DT)
    for k in range(52, 62):
        tracks = tr.step(dets([(3.5, 2.5)], rng), k * DT)
    assert len(tracks) == 1 and tracks[0].id != oid


def test_velocity_is_estimated_and_speed_capped():
    errs = []
    for seed in range(40):
        rng = np.random.default_rng(seed)
        tr = Tracker()
        for k in range(80):
            tracks = tr.step(dets([(0.5 + 0.4 * k * DT, 1.0)], rng), k * DT)
            if k >= 40:                                               # after it has settled
                errs.append(tracks[0].vel - np.array([0.4, 0.0]))
    errs = np.array(errs)
    assert np.all(np.abs(errs.mean(axis=0)) < 0.03)                   # unbiased
    assert np.sqrt((errs ** 2).mean()) < 0.35                         # MATH 3.5: velocity sigma about 0.25 m/s
    t2 = Tracker()
    for k in range(10):                                               # a wildly jumping detection must not make a 20 m/s track
        t2.step([Detection(np.array([0.5 + 2.0 * k * DT, 1.0]), R)], k * DT)
    assert all(t.speed <= t2.cfg.speed_cap + 1e-9 for t in t2.tracks)
