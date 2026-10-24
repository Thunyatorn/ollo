import numpy as np
from nestwatch_vision import kalman

DT, SA, SM = 1 / 8, 1.0, 0.15
R = np.eye(2) * SM ** 2


def steady_state():
    x, P = np.zeros(4), np.diag([SM ** 2, SM ** 2, 1, 1])
    for _ in range(300):
        x, P = kalman.predict(x, P, DT, SA)
        S = kalman.HM @ P @ kalman.HM.T + R
        K = P @ kalman.HM.T @ np.linalg.inv(S)
        P = (np.eye(4) - K @ kalman.HM) @ P
    return P, K


def test_steady_state_matches_math_md_3_5():
    P, K = steady_state()
    assert np.sqrt(P[0, 0]) == np.float64(np.sqrt(P[0, 0])) and abs(np.sqrt(P[0, 0]) - 0.091) < 0.002
    assert abs(np.sqrt(P[2, 2]) - 0.247) < 0.003
    assert abs(K[0, 0] - 0.366) < 0.003 and abs(K[2, 0] - 0.664) < 0.005


def test_joseph_update_keeps_covariance_symmetric_and_positive():
    x, P = np.zeros(4), np.diag([0.02, 0.02, 1, 1])
    rng = np.random.default_rng(0)
    for _ in range(500):
        x, P = kalman.predict(x, P, DT, SA)
        x, P, _ = kalman.update(x, P, rng.normal(0, 0.15, 2), R)
    assert np.allclose(P, P.T, atol=1e-12) and np.all(np.linalg.eigvalsh(P) > 0)


def test_filter_is_statistically_consistent():
    """Simulate a person from exactly the model the filter assumes; NIS should average 2 and NEES 4 (MATH 3.6)."""
    rng = np.random.default_rng(1)
    F, Q = kalman.F_matrix(DT), kalman.Q_matrix(DT, SA)
    Lq = np.linalg.cholesky(Q + 1e-12 * np.eye(4))
    nis, nees, pos_err = [], [], []
    for _ in range(300):
        x_true = np.array([2.0, 1.5, 0.3, -0.2])
        x = x_true + rng.normal(0, [SM, SM, 1, 1])                      # start from a consistent guess
        P = np.diag([SM ** 2, SM ** 2, 1.0, 1.0])
        for k in range(120):
            x_true = F @ x_true + Lq @ rng.normal(size=4)
            z = x_true[:2] + rng.normal(0, SM, 2)
            x, P = kalman.predict(x, P, DT, SA)
            x, P, n = kalman.update(x, P, z, R)
            if k >= 40:                                                 # after it has settled
                e = x_true - x
                nees.append(float(e @ np.linalg.inv(P) @ e))
                nis.append(n)
                pos_err.append(np.linalg.norm(e[:2]))
    assert abs(np.mean(nis) - 2.0) < 0.1
    assert abs(np.mean(nees) - 4.0) < 0.25
    assert np.sqrt(np.mean(np.square(pos_err))) < SM                    # better than the raw measurement


def test_dropout_makes_the_filter_less_sure():
    x, P = np.zeros(4), np.diag([0.02, 0.02, 0.06, 0.06])
    sizes = []
    for _ in range(16):                                                 # 2 s with no measurements
        x, P = kalman.predict(x, P, DT, SA)
        sizes.append(np.sqrt(P[0, 0]))
    assert all(b > a for a, b in zip(sizes, sizes[1:])) and sizes[-1] > 0.5
