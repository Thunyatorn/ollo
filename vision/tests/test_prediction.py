import numpy as np
from nestwatch_vision.prediction import zone_evidence

STAIRS = [(2.8, 1.9), (4, 1.9), (4, 3), (2.8, 3)]
RNG = lambda: np.random.default_rng(0)


def ev(pos, vel, sigma_v, sigma_p=0.09, n=3000, shrink_c=0.0):
    x = np.array([*pos, *vel], float)
    P = np.diag([sigma_p ** 2, sigma_p ** 2, sigma_v ** 2, sigma_v ** 2])
    return zone_evidence(x, P, STAIRS, n=n, rng=RNG(), shrink_c=shrink_c)


def test_math_md_6_2_table():
    """The pure hit fraction, shrinkage off."""
    close = lambda got, want: abs(got - want) < 0.06
    assert close(ev((1.8, 2.4), (0.45, 0), 0.10).e, 0.85)         # heading straight at it, good velocity estimate
    assert close(ev((1.8, 2.4), (0.45, 0), 0.15).e, 0.70)
    assert close(ev((1.8, 2.4), (0.45, 0), 0.25).e, 0.52)         # worse estimate, honestly lower
    assert close(ev((0.3, 2.4), (1.2, 0), 0.25).e, 0.65)          # fast child from 2.5 m away
    assert close(ev((2.2, 2.4), (0.2, 0), 0.25).e, 0.42)          # slow child, 0.6 m away
    assert close(ev((1.8, 1.2), (0.45, 0), 0.25).e, 0.10)         # passing parallel
    assert ev((1.0, 0.6), (-0.3, -0.2), 0.25).e == 0.0            # walking away
    assert ev((1.8, 0.5), (0, 0), 0.25).e < 0.01                  # standing far away


def test_standing_at_the_edge_no_longer_reads_as_a_threat():
    """MATH 6.2 noted 0.30 for a child standing next to the edge, from velocity noise alone. The ramp removes it."""
    assert ev((2.5, 2.4), (0, 0), 0.25).e < 0.02
    assert ev((2.5, 2.4), (0.03, 0.02), 0.25).e < 0.02            # a drift of 3 cm/s is noise too


def test_shrinkage_quiets_noise_level_velocity_but_keeps_a_real_walk():
    """MATH 6.4. A standing child's velocity estimate is noise of about the size of its own sigma."""
    noise = dict(pos=(2.5, 2.4), vel=(0.2, 0.0), sigma_v=0.23)    # speed barely above its own uncertainty, 0.3 m from the zone
    assert ev(**noise).e > 0.4                                    # without shrinkage it looks like a threat
    assert ev(**noise, shrink_c=0.5).e < 0.15                     # with it, mostly not
    walk = dict(pos=(1.8, 2.4), vel=(0.45, 0.0), sigma_v=0.15)
    assert ev(**walk, shrink_c=0.5).e > 0.55                      # a clear walk toward the zone stays evident (0.70 unshrunk)
    assert ev(**walk, shrink_c=0.5).e < ev(**walk).e + 0.02       # shrinkage never adds evidence


def test_already_inside_is_certain():
    r = ev((3.2, 2.4), (0, 0), 0.25)
    assert r.inside and r.e == 1.0 and r.entry_s == 0.0


def test_entry_time_is_reported_for_the_countdown():
    r = ev((1.8, 2.4), (0.45, 0), 0.10, shrink_c=0.5)
    assert abs(r.entry_s - 1.0 / 0.45) < 1e-6                     # MATH 5.3 worked example, unaffected by shrinkage
    assert ev((0.3, 2.4), (0.45, 0), 0.10).entry_s is None        # 2.5 m away at 0.45 m/s: beyond the 3 s horizon


def test_closer_means_more_evidence_and_a_better_estimate_means_more_evidence():
    near, far = ev((2.3, 2.4), (0.45, 0), 0.15).e, ev((1.5, 2.4), (0.45, 0), 0.15).e
    assert near > far
    assert ev((1.8, 2.4), (0.45, 0), 0.05).e > ev((1.8, 2.4), (0.45, 0), 0.25).e
