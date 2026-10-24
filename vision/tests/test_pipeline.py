"""The whole M1-M3 chain on simulated children: noisy detections -> tracker -> zone evidence -> CUSUM.
Limits are set just outside what was measured over 150 runs per scenario at the default settings
(k=0.3, h=0.2, shrink 0.5, sigma_a=1.0, 8 Hz, 12 cm measurement noise)."""
import numpy as np
from scripts.scenarios import INFORMATIONAL, NON_THREATS, threat
from scripts.sim_pipeline import simulate

N = 60


def test_children_heading_at_the_stairs_are_alerted_before_they_arrive():
    res = [simulate(threat(s), s) for s in range(N)]
    entered = [(f, e) for f, e in res if e is not None]
    lead = [e - f for f, e in entered if f is not None and f < e]
    assert len(entered) >= 50                                   # the scripted children really do reach the stairs
    assert len(lead) / len(entered) >= 0.97                     # measured 133/133
    assert np.median(lead) >= 1.0                               # measured 1.25 s of warning
    assert np.percentile(lead, 10) >= 0.5                       # measured 0.75 s; the honest floor is about half a second


def test_children_who_are_not_a_threat_do_not_set_off_the_alert():
    for name, make in NON_THREATS.items():
        alarms = sum(simulate(make(s), s)[0] is not None for s in range(N))
        assert alarms <= 3, f"{name}: {alarms}/{N} false alarms"      # measured 0 to 1 per 150


def test_standing_right_at_the_edge_alerts_sometimes_by_design():
    """A child 10 to 30 cm from the stairs edge is arguably worth an alert. Measured 25% of 12-second runs.
    This pins the behaviour so a change is noticed, whichever way it moves."""
    for name, make in INFORMATIONAL.items():
        rate = sum(simulate(make(s), s)[0] is not None for s in range(N)) / N
        assert 0.05 <= rate <= 0.5, (name, rate)
