"""Constant-velocity Kalman filter on the floor plane. State [px, py, vx, vy]. See MATH.md section 3."""
import numpy as np

HM = np.array([[1.0, 0, 0, 0], [0, 1.0, 0, 0]])   # we measure position only


def F_matrix(dt: float) -> np.ndarray:
    F = np.eye(4)
    F[0, 2] = F[1, 3] = dt
    return F


def Q_matrix(dt: float, sigma_a: float) -> np.ndarray:
    """White-noise-acceleration process noise (MATH 3.2)."""
    q = sigma_a ** 2 * np.array([[dt ** 4 / 4, dt ** 3 / 2], [dt ** 3 / 2, dt ** 2]])
    Q = np.zeros((4, 4))
    Q[np.ix_([0, 2], [0, 2])] = q
    Q[np.ix_([1, 3], [1, 3])] = q
    return Q


def predict(x: np.ndarray, P: np.ndarray, dt: float, sigma_a: float):
    F = F_matrix(dt)
    return F @ x, F @ P @ F.T + Q_matrix(dt, sigma_a)


def innovation(x: np.ndarray, P: np.ndarray, z: np.ndarray, R: np.ndarray):
    """The miss y = z - Hx and its expected size S (MATH 3.4)."""
    return z - HM @ x, HM @ P @ HM.T + R


def update(x: np.ndarray, P: np.ndarray, z: np.ndarray, R: np.ndarray):
    """Blend a measurement into the prediction. Joseph form keeps P symmetric and valid.

    Returns x, P, and the normalized innovation squared (NIS), which averages 2 if the filter is honest.
    """
    y, S = innovation(x, P, z, R)
    Sinv = np.linalg.inv(S)
    K = P @ HM.T @ Sinv
    x_new = x + K @ y
    I_KH = np.eye(4) - K @ HM
    P_new = I_KH @ P @ I_KH.T + K @ R @ K.T
    return x_new, P_new, float(y @ Sinv @ y)


def mahalanobis2(x: np.ndarray, P: np.ndarray, z: np.ndarray, R: np.ndarray) -> float:
    y, S = innovation(x, P, z, R)
    return float(y @ np.linalg.inv(S) @ y)
