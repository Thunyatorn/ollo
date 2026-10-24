# ollo Phase 3: the math behind the vision service

This document explains every calculation the vision service makes, why we chose it, and how we will check it.
It is written so you can follow it without a math degree, and so you can still argue with it if you have one.
Numbers marked **(computed)** were produced by running the code in `vision/.venv` while writing this file; they are real, not hand-waved.
Numbers marked **(start value)** are my first guess and must be tuned on real footage.

Spec: `CLUADE.md` ("Vision service"). Where this file and the spec disagree, tell me and we fix one of them.

## Contents

0. The pipeline in one picture, conventions, symbols
1. Camera pixels to floor meters: the homography
2. Pose keypoints: what the model gives us
3. Tracking one person: the Kalman filter
4. Tracking many people: the Hungarian algorithm
5. Zones: polygon geometry
6. Prediction: "will this child enter the zone within 3 seconds?"
7. Deciding to alert: CUSUM
8. The other detectors (fall, climbing, stillness, unsupervised, distress, lost child, head count)
9. Privacy: face blur and saved clips
10. Timing and latency
11. How we test each piece
12. What we build in Phase 3 (the list)
13. Decisions I need from you
14. Parameter table and references

---

## 0. The pipeline, conventions, symbols

```
camera frame (pixels)
   |  capture thread, keeps only the newest frame
   v
pose model  ->  per person: box + 17 keypoints (pixels) + confidence         [section 2]
   |
   v
foot point (pixels) --homography H--> position on the floor (meters)         [section 1]
   |
   v
tracker: Kalman filter per person + Hungarian matching between frames        [sections 3, 4]
   |  gives each person: position, velocity, uncertainty, ID
   v
for each (child, zone): evidence e in [0,1] that the child is entering       [sections 5, 6]
   |
   v
CUSUM: add up evidence over time, fire only when it is sustained             [section 7]
   |
   v
event -> Spacetime `report_event` (and the wrist buzzer, over the local network)
```

Other detectors (section 8) read the same tracks and keypoints.

### Conventions (so we never mix up axes)

| Thing | Convention |
| --- | --- |
| Image coordinates | `(u, v)` in pixels. `u` goes right, `v` goes **down**. Origin is the top-left corner of the frame. |
| Floor coordinates | `(x, y)` in **meters**. Origin is the top-left corner of the room on the floor plan, `x` right, `y` down. This is exactly the SVG coordinate system in the dashboard, so no conversion is needed anywhere. |
| Time | seconds, taken from the moment the camera captured the frame (not when we finished processing it). |
| Velocity | meters per second on the floor. |
| Angles | degrees in this document, radians in code. |
| Vectors | column vectors. `A^T` is the transpose, `A^-1` the inverse. |

### Symbols

| Symbol | Meaning |
| --- | --- |
| `p = (u, v, 1)` | an image point written in homogeneous form (a trailing 1 lets us use matrix multiplication) |
| `q = (x, y)` | a floor point in meters |
| `H` | the 3x3 homography matrix, maps image to floor |
| `x_k`, `P_k` | Kalman state and its covariance (its uncertainty) at step `k` |
| `F`, `Q` | Kalman motion model and its process noise |
| `Hm`, `R` | Kalman measurement model and its measurement noise |
| `z` | a measurement: where the camera says the person is |
| `dt` | time between two frames, in seconds |
| `e` | evidence in `[0, 1]` that something bad is happening right now |
| `S` | the CUSUM running sum |
| `k`, `h` | CUSUM drift and threshold |
| `L` | torso length (shoulder midpoint to hip midpoint), used to make pose measurements size-independent |

---

## 1. Camera pixels to floor meters: the homography

### 1.1 The problem

The camera sees a flat picture. The dashboard and every rule ("keep kids out of the stairs") live in meters on the floor.
We need a function `pixel -> floor position`. It only has to work for points that are **on the floor plane**,
and that is the whole trick: **a plane seen by a camera is related to the plane's true layout by a 3x3 matrix.**
That matrix is the homography `H`. No camera model, lens numbers or 3D reconstruction are needed.

### 1.2 The model

```
[ s*x ]       [ u ]
[ s*y ] = H * [ v ]          H = [ h11 h12 h13 ]
[  s  ]       [ 1 ]              [ h21 h22 h23 ]
                                 [ h31 h32 h33 ]
```

Plain words: multiply the pixel by `H`, get three numbers `(a, b, s)`, then divide the first two by the third:
`x = a/s`, `y = b/s`. The division is what makes far-away things look smaller. Written out:

```
x = (h11*u + h12*v + h13) / (h31*u + h32*v + h33)
y = (h21*u + h22*v + h23) / (h31*u + h32*v + h33)
```

`H` and `2*H` do the same thing (the scale cancels in the division), so `H` has 9 numbers but only **8 degrees of freedom**.
We fix the scale by dividing everything by `h33`.

### 1.3 Solving for H from clicked points (the "DLT")

Each calibration point gives a pair: pixel `(u, v)` and its known floor position `(x, y)`.
Start from the two equations above and cross-multiply to get rid of the division:

```
x * (h31*u + h32*v + h33) - (h11*u + h12*v + h13) = 0
y * (h31*u + h32*v + h33) - (h21*u + h22*v + h23) = 0
```

These are **linear in the 9 unknowns `h`**. Each point therefore adds two rows to a matrix `A`:

```
[ -u  -v  -1   0   0   0   x*u   x*v   x ]
[  0   0   0  -u  -v  -1   y*u   y*v   y ]      (times h = 0)
```

With 4 points `A` is 8x9, so there is exactly one direction `h` (up to scale) that satisfies `A h = 0`.
We find it with the singular value decomposition (SVD): `h` is the last row of `V^T` in `A = U S V^T`.
Reshape `h` into 3x3 and divide by `h33`.

With **5 or more points** the system has no exact solution (clicks are noisy), so we take the `h` that makes `||A h||` smallest
subject to `||h|| = 1`. That is also the last row of `V^T`. The smallest singular value tells you how inconsistent your points are.
This is why we ask for more than four points when possible (see 1.6).

### 1.4 Hartley normalization (why raw pixels are a bad idea)

Pixel coordinates are in the hundreds, floor coordinates are 0 to 4, and the last column of `A` mixes them.
That makes `A` badly scaled and the answer sensitive to rounding. The fix is old and standard:

1. Move each point set so its centroid is at the origin.
2. Scale each set so the average distance from the origin is `sqrt(2)`.
3. Solve the DLT on the normalized points to get `H~`.
4. Undo it: `H = T_floor^-1 * H~ * T_image`.

where `T = [[s, 0, -s*cx], [0, s, -s*cy], [0, 0, 1]]`, `(cx, cy)` the centroid, `s = sqrt(2) / mean distance`.
With exactly four good points the answer barely changes; with more points or poor geometry it matters a lot. We always normalize.

### 1.5 Worked example (computed)

Four floor markers in a 4 m x 3 m room, clicked in the camera picture:

| Marker | Pixel `(u, v)` | Floor `(x, y)` m |
| --- | --- | --- |
| 1 | (100, 100) | (0, 0) |
| 2 | (500, 120) | (4, 0) |
| 3 | (560, 400) | (4, 3) |
| 4 | (60, 380) | (0, 3) |

The DLT gives (rounded):

```
H = [  0.01065   0.00152  -1.21736 ]
    [ -0.00073   0.01450  -1.37778 ]
    [ -0.00009   0.00097   1.00000 ]
```

Checks (computed): the four markers map back to exactly (0,0), (4,0), (4,3), (0,3).
The middle of the picture, pixel (330, 250), maps to floor (2.207, 1.655).
The bottom of `H` (`-0.00009`, `0.00097`) is what shrinks distant things: change `v` by one pixel and the
denominator changes, so one pixel is a different number of meters in different places.

### 1.6 Reprojection error, and why four points is not enough to judge quality

"Reprojection error" means: push each calibration pixel through `H`, and measure how far it lands from its known floor position. Report it in meters.

**Catch:** with exactly four points the error is zero **by construction**, because four points have enough freedom to fit perfectly,
even if you mis-clicked badly. The spec's `/calibrate` "returns a reprojection error", but with four points that number cannot warn you.

What we do instead (built in `calibration.py`, tested in `tests/test_calibration.py`; the rates below are measured, with 1 px of random click noise on every point):
- Ask for **six or more** points: the 4 corners plus 2 or more check points (for example the middle of two walls). Points lying on a line between corners are fine.
- **Judge by the fit error**, in meters: ok if the RMS error over all points is at most 5 cm. With normal clicking (1 px noise) 100% of six-point calibrations pass; with sloppy 3 px clicks about 70% do.
- **Catch and name one wild click** (six or more points): drop each point in turn and refit; the bad click is the point whose removal makes the rest fit. A single click 20 px off is flagged 93% of the time and the right point is named 83% of the time; at 40 px it is flagged 100% and named 94%.
- **Do not use hold-out error to judge or blame.** Leaving out a *corner* is an extrapolation, so with normal noise the hold-out error often exceeds 5 cm (only 61% of good calibrations passed when I tried it) and it names the wrong point. It is kept in the report for information only.
- **With exactly 4 points** the error is zero by construction, so the report says so and recommends check points.
- **With 5 points** a bad click is caught only about half the time (35% at 20 px, 58% at 40 px), because there is a single spare point. When trouble is flagged the report says "add a sixth point so I can tell which", and does not guess.
- **Refuse an unusable layout** with the *conditioning* of the DLT matrix: second-smallest over largest singular value after normalization. About 0.27 to 0.31 for a good layout, 0.0035 when three of four markers are in a line, about 1e-18 when all are. Reject below 0.02, warn below 0.1 ("spread the markers out"). This replaced my first idea, "reject if any three points are collinear", which wrongly rejected the check points at wall midpoints.

### 1.7 Which point of the person do we convert?

`H` is only correct for points **on the floor**. A person's box center is at hip height; pushing it through `H` puts them
in the wrong place, by an amount that grows with distance from the camera. So we convert the **feet**:

```
foot point (pixels) = midpoint of the two ankle keypoints (indexes 15 and 16)   if both are confident
                    = the lower ankle                                          if only one is
                    = bottom-center of the person's box                        otherwise (feet hidden, child kneeling...)
```

The ankle keypoint sits a few centimetres **above the sole**, so a foot point taken at the ankle is slightly off the floor plane. In the sample photo the dot lands at the ankle, not at the shoe's contact point. The bias is a few centimetres, below the 0.10 m measurement noise we already assume for `ankles`, so we leave it; if M9 shows a systematic offset toward the camera we shift the point down by a fraction of the shin length.
A child sitting or lying down has no meaningful feet; there, bottom-center of the box is the best floor estimate.
We attach a flag `foot_quality` (`ankles`, `one_ankle`, `box_bottom`) and give worse flags a larger measurement noise (section 3).

### 1.8 How much does one pixel of error cost? (computed)

Take the derivative of the mapping to get the "meters per pixel" at any spot. With `w = h31*u + h32*v + h33`:

```
dx/du = (h11 - x*h31) / w        dx/dv = (h12 - x*h32) / w
dy/du = (h21 - y*h31) / w        dy/dv = (h22 - y*h32) / w
```

This 2x2 matrix is the Jacobian `J`. In the example room:

| Pixel | Floor point | Meters per pixel (singular values of J) |
| --- | --- | --- |
| (80, 390), near the camera | (0.17, 3.08) | 0.0086 and 0.0077 |
| (330, 250), middle | (2.21, 1.66) | 0.0108 and 0.0088 |
| (120, 105), far corner | (0.20, 0.05) | 0.0133 and 0.0098 |

So in this room one pixel is about 1 cm. The far side is about 50% coarser than the near side. In a bigger room or with a camera at a shallow angle the difference is far larger.

If the pose model's foot point has a standard deviation of `sigma_px` pixels, the floor uncertainty is `sigma_floor = J * sigma_px`.
We feed that into the Kalman filter as the measurement noise `R` for each detection, so far-away detections are trusted less. That is the principled version of "far things are noisier".

Calibration-click error matters too. Simulating 1 pixel of random error on every click, 2000 times (computed):

| Points used | RMS floor error at the middle of the room |
| --- | --- |
| 4 | 1.07 cm |
| 6 | 0.75 cm |

So extra points help even though you "only needed four".

### 1.9 Several cameras, blind spots, and recalibration

- Each camera has its **own** `H` into the **same** floor coordinate system. That is what makes cameras comparable.
- When two cameras see the same person, their floor positions should agree within a few centimeters to ~30 cm. We treat both as measurements of one person and merge detections closer than 0.3 m taken within 100 ms (start value) before tracking.
- A blind spot (an area no camera covers) is a polygon on the floor. A track that disappears next to a blind spot is **expected** to vanish; it is not a missing child (section 8.6).
- If the camera is bumped, the old `H` is silently wrong. Mitigation: keep the calibration image; a nightly check compares the current frame to it (simple feature matching) and warns if the view shifted. (Stretch goal.)
- Lens distortion (fisheye / wide angle) breaks the "plane to plane" assumption near the edges. If a camera is very wide, undistort the frame first (`cv2.undistort` with a checkerboard calibration). We will check the held-out error near the edges to see if it matters.

### 1.10 What we implement

`calibration.py` with: `fit_homography(image_pts, floor_pts) -> H, report`, `to_floor(H, pixels)` (vectorized), `jacobian(H, pixel)`,
`reprojection_report(...)`. We write the DLT ourselves in numpy (it is ~30 lines and you will see exactly what it does),
then check it against `cv2.findHomography`.

---

## 2. Pose keypoints: what the model gives us

The pose model returns, per person: a box and 17 keypoints `(u, v, confidence)` in the standard COCO order:

| Index | Point | Index | Point |
| --- | --- | --- | --- |
| 0 | nose | 9 | left wrist |
| 1 | left eye | 10 | right wrist |
| 2 | right eye | 11 | left hip |
| 3 | left ear | 12 | right hip |
| 4 | right ear | 13 | left knee |
| 5 | left shoulder | 14 | right knee |
| 6 | right shoulder | 15 | left ankle |
| 7 | left elbow | 16 | right ankle |
| 8 | right elbow |  |  |

Rules we apply everywhere:
- A keypoint with confidence below **0.3 (start value)** is treated as **missing**, not as a point at some position.
- Anything computed from a missing keypoint is missing too; we never invent values.
- **Smoothing:** raw keypoints jitter by a few pixels frame to frame. Detectors that use velocity or angles need a smoothed signal.
  We use the One-Euro filter: an exponential filter whose strength depends on speed (strong smoothing when still, light when moving fast).
  The basic building block is `x_hat_t = a*x_t + (1-a)*x_hat_{t-1}` with `a = 1 / (1 + tau/dt)`.
- **Size normalization:** distances in pixels depend on how close the child is to the camera. We divide by torso length `L`
  (shoulder midpoint to hip midpoint) so "head dropped by 1.2 `L` per second" means the same thing everywhere.

---

## 3. Tracking one person: the Kalman filter

### 3.1 Why a filter at all

The pose model gives a noisy position every frame, sometimes none (occlusion), and no velocity.
We need a **smooth position, a velocity, and a measure of how sure we are**. The Kalman filter is the standard tool: it blends a motion prediction with each new measurement,
weighting each by its uncertainty. Velocity comes for free from the motion model.

### 3.2 The model: constant velocity

State per person on the floor: `x = [px, py, vx, vy]^T` (position and velocity).

Motion between frames, `dt` apart:

```
x_k = F x_{k-1} + w          F = [ 1 0 dt 0 ]
                                 [ 0 1 0 dt ]
                                 [ 0 0 1  0 ]
                                 [ 0 0 0  1 ]
```

Plain words: new position = old position + velocity * dt; velocity stays the same, **plus a random kick `w`** because children speed up, stop and turn.

Why constant velocity and not something fancier? Our prediction horizon is 3 seconds, and the data is noisy.
A constant-velocity model with the right amount of random kick is robust and has few knobs. Constant acceleration amplifies noise.

**Process noise** (the size of the random kick), "white noise acceleration" model with intensity `sigma_a` (m/s^2):

```
Q = sigma_a^2 * [ dt^4/4   0      dt^3/2   0     ]
                [ 0        dt^4/4 0        dt^3/2]
                [ dt^3/2   0      dt^2     0     ]
                [ 0        dt^3/2 0        dt^2  ]
```

Plain words: the longer the gap `dt`, the more the child may have drifted from a straight line, growing fast (`dt^4` in position).

### 3.3 The measurement

The camera tells us the floor position: `z = [x, y]^T`, so

```
z = Hm x + noise        Hm = [ 1 0 0 0 ]       R = [ s_m^2   0   ]
                             [ 0 1 0 0 ]           [  0    s_m^2 ]
```

`s_m` is the measurement noise in meters. Start value 0.15 m, but better: derive it per detection from section 1.8
(`s_m = sqrt(sigma_px^2 * (J J^T))` plus a floor for `foot_quality`: `ankles` 0.10, `one_ankle` 0.15, `box_bottom` 0.25 m, **start values**).

### 3.4 The equations (every frame)

**Predict** (before looking at the new frame):

```
x_pred = F x                  where we were + where velocity takes us
P_pred = F P F^T + Q          our uncertainty grows
```

**Update** (after a detection `z` is matched to this track):

```
y = z - Hm x_pred             innovation: how wrong the prediction was
S = Hm P_pred Hm^T + R        how big a miss we expected
K = P_pred Hm^T S^-1          Kalman gain: how much to trust the new measurement
x = x_pred + K y
P = (I - K Hm) P_pred (I - K Hm)^T + K R K^T       "Joseph form", stays symmetric and valid
```

Plain words: if the prediction was far off and the measurement is precise, `K` is large and we jump to the measurement.
If the measurement is noisy, `K` is small and we trust our own prediction.

If a track has **no** detection this frame (occluded), we do only the predict step. `P` grows, so the track becomes less certain,
and when it reappears it gets matched with a wider gate (section 4).

### 3.5 What it settles to (computed)

At 8 Hz with `sigma_a = 1.0 m/s^2` and `s_m = 0.15 m`, the filter settles to:

| Quantity | Value |
| --- | --- |
| Position uncertainty (1 sigma) | 0.091 m (better than the raw 0.15 m measurement) |
| Velocity uncertainty (1 sigma) | 0.247 m/s |
| Gain on position | 0.366 |
| Gain on velocity | 0.664 per second |

So after a second or so we know the position to about 9 cm and the velocity to about 0.25 m/s. That velocity uncertainty is the single most important number for prediction (section 6).

### 3.6 Practical details

- **`dt` is variable.** Frames arrive unevenly. We always use the real capture timestamps, never a fixed `1/fps`.
- **Initialization.** A new track starts with `P = diag(s_m^2, s_m^2, 1.0^2, 1.0^2)`: position known to a measurement, velocity unknown to ~1 m/s.
- **Speed cap.** If the estimated speed exceeds 3 m/s (nobody in a playroom runs that fast), clamp it. It means a bad match.
- **Tuning `sigma_a`.** Start at 1.0 m/s^2 for tracking. Children accelerate hard. Too low and the filter lags turns; too high and it is jittery. We tune on real video by looking at the consistency test below.
- **Consistency check (NEES/NIS).** If the filter is correct, then over many frames the average of `y^T S^-1 y` (the *normalized innovation squared*) should be about **2** (the number of measured dimensions),
  and the average of `(x_true - x)^T P^-1 (x_true - x)` about **4** (the state size) on simulated data. Far above means the filter is overconfident, far below means too timid. We will test this.

---

## 4. Tracking many people: the Hungarian algorithm

### 4.1 The problem

Each frame gives `m` detections. We have `n` tracks. Which detection belongs to which track?
Each pair has a "cost" (how unlikely the match is). We want the one-to-one assignment with the lowest **total** cost.
Doing it greedily (each track grabs its nearest detection) fails when two children cross: one steals the other's match.
The Hungarian algorithm finds the **globally best** assignment in `O(n^3)` time. For 20 people that is nothing. We use `scipy.optimize.linear_sum_assignment`.

### 4.2 The cost: Mahalanobis distance

Plain distance ignores uncertainty: being 0.3 m off is fine for a track we are unsure about, and alarming for one we are sure about.
The Mahalanobis distance measures the miss **in units of expected miss**:

```
d^2(i, j) = y_ij^T S_i^-1 y_ij
   y_ij = z_j - Hm x_pred_i            (detection j minus the prediction of track i)
   S_i  = Hm P_pred_i Hm^T + R_j
```

`d^2` is exactly the quantity the Kalman update already computes, so it costs almost nothing.

### 4.3 Gating

If the prediction is right, `d^2` follows a chi-squared distribution with 2 degrees of freedom.
So we can set a **statistical limit**: accept only pairs with `d^2 < gate`. Pairs over the limit get a huge cost (like 1e6) so the solver never picks them.
After solving, any pair that still has the huge cost is discarded. Plain words: "a detection that is wildly inconsistent with a track can never be that track."

**Which limit? My first choice (9.21, the 99% value) was wrong, and testing showed why (computed, `tests/test_tracker.py`).**
A 99% gate throws away 1 correct detection in 100. A thrown-away detection starts a *new* track, so the same person ends up with two tracks.
At 8 frames a second that happens within seconds: a single child walking alone kept one ID in only 87% of 10-second runs with the 99% gate (70% in a right-angle pass), and had duplicate tracks in several frames per run.
With the **99.9% gate, 13.82**, the single walker kept exactly one ID in 100% of runs and never had two tracks. 18.4 (99.99%) gave no further gain, so we use 13.82.
The price is a slightly higher chance of accepting a wrong match for a person standing very near another, which is the crossing case below.

### 4.4 Track life cycle

| State | Rule |
| --- | --- |
| New detection with no match | Starts a **tentative** track. |
| Tentative | Becomes **confirmed** after 3 matches within 5 frames. Dropped after 1 miss. This kills one-frame ghost detections. |
| Confirmed, matched | Normal update. |
| Confirmed, no match | Predict-only. Keep for up to **2 s** (spec: "last position kept for about 2 s"), then mark lost and emit `child_not_visible` if not explained by a blind spot or exit (section 8.6). |
| Lost track, new detection appears near its predicted spot within 3 s | Re-use the old ID (and the adult tag, if any). |

### 4.5 Adults and children

The spec says adults are **tagged by a person on the dashboard** at the start of the day, so we never guess identity from appearance.
The tag lives on the track ID. When a track dies and a new one is born within 1 m and 3 s of its last position, the new track inherits the tag.
(Optional later: a size prior. Adults' boxes are larger at the same floor position, learned from tagged adults.)

### 4.6 Known weaknesses (measured)

**Two people reaching the same spot at the same instant can swap identities.** When both are inside each other's measurement noise (about 0.12 m) for a frame or two, nothing in position alone says which is which;
afterwards the Kalman velocities usually sort it out, but not always. Measured over 40 random runs each, worst case (both arrive at the crossing at exactly the same time), fraction of runs where the two IDs were **permanently exchanged**:

| Crossing angle | speed 0.5 m/s | speed 1.0 m/s |
| --- | --- | --- |
| 30 deg | 40% | 28% |
| 60 deg | 30% | 5% |
| 90 deg | 12% | 0% |
| 120 deg | 5% | 0% |

So slow children passing on a shallow angle at the same moment are the problem case; fast or perpendicular crossings are fine. If they reach the crossing at *different* times (1.5 s apart) there were **0 swaps in 40 runs**.
A lower `sigma_a` (more inertia) halves the swaps in some rows (60 deg, 0.5 m/s: 30% to 15%), but makes the filter slower to follow a child who turns. That trade-off is decided on real footage in M9, not now.
Why it matters: an adult tag or a child's alert history follows the track ID, so a swap moves them to the wrong person. A swap during an alert is the dangerous case, and it is why a later appearance cue (clothing colour or keypoint-based size) is worth adding if real footage shows swaps.
The test `test_crossing_swap_rates_stay_within_the_measured_limits` fails if tracking gets worse than these numbers.

Other weakness: heavy occlusion by furniture produces gaps longer than 2 s, which look like new people. Camera placement matters more than any algorithm here.

---

## 5. Zones: polygon geometry

A zone is a polygon on the floor, in meters. Three operations are needed.

### 5.1 Is a point inside? (ray casting)

Shoot a ray from the point to the right. Count how many polygon edges it crosses. Odd = inside, even = outside.
For an edge from `(xi, yi)` to `(xj, yj)` the ray at height `py` crosses it when

```
(yi > py) != (yj > py)    and    px < (xj - xi) * (py - yi) / (yj - yi) + xi
```

and each crossing flips the answer. Points exactly on an edge are a coin flip in this test; we pad every zone by a small margin (2 cm) so it does not matter.
`shapely` has a tested version, which we use to cross-check ours.

### 5.2 How far is a point from the zone?

Distance to a segment `a -> b`: project the point onto the segment, clamp the projection to the segment, measure:

```
t = clamp( ((p - a) . (b - a)) / |b - a|^2 , 0, 1 )
distance = | p - (a + t (b - a)) |
```

Take the minimum over all edges. Make it negative if the point is inside (a "signed distance"). Used for "near the stairs" and for blind-spot checks.

### 5.3 When would a moving point enter? (ray vs edges)

A person at `p` moving with velocity `v` is at `p + t v` at time `t`. An edge `a -> b` with `e = b - a` is hit when `p + t v = a + s e` for some `t >= 0` and `s` in `[0, 1]`.
Using the 2D cross product `u x w = ux*wy - uy*wx`, the solution is:

```
den = v x e
t = ((a - p) x e) / den
s = ((a - p) x v) / den           (if den = 0 the path is parallel to the edge: no hit)
```

The time to entry is the smallest `t >= 0` over all edges that satisfy `0 <= s <= 1`. If the person is already inside, it is 0.

Worked example (computed): child at (1.8, 2.4) m moving (0.45, 0) m/s toward stairs `[(2.8,1.9),(4,1.9),(4,3),(2.8,3)]`.
The result is `t = 2.222 s`, which equals `(2.8 - 1.8) / 0.45`. This number is what we send as `predicted_entry_s`.

### 5.4 Schedules and blind spots

- A zone is **active** at time `t` if its `status` is `active` and its schedule covers `t`. A schedule is either explicit hours (minutes after midnight) or a name like `nap_time`, which the dashboard resolves to hours.
  The vision service caches zones and re-reads them when Spacetime says they changed.
- Zones may overlap. A child is evaluated against each active zone separately.
- A blind spot is a polygon with `status = no camera`. It never produces alerts; it only explains why a track vanished.

---

## 6. Prediction: "will this child enter the zone within 3 seconds?"

This is the heart of the product. The detector must say "that child is about to reach the stairs" before it happens, but not for every child who walks nearby.
Code: `prediction.py`. Tests: `tests/test_prediction.py` (the table in 6.2 is a regression test).

### 6.1 The obvious approach, and why it fails (computed)

Obvious idea: predict where the child will be 3 s from now and test if that point is inside the zone.
Let the child be uncertain: position at time `tau` ahead is Gaussian with mean `p + v*tau` and covariance

```
Sigma(tau) = P_pp + tau (P_pv + P_vp) + tau^2 P_vv + sigma_a^2 * tau^3 / 3
```

(position uncertainty, plus velocity uncertainty growing with time, plus the random kicks accumulating).
Then `P(inside at tau)` is the probability mass of that Gaussian inside the polygon (we estimated it by sampling).

For a child walking **straight at the stairs**, 2.2 s away (computed):

| `sigma_a` | P(inside) at 1 s | at 2 s | at 3 s |
| --- | --- | --- | --- |
| 1.0 | 0.12 | 0.06 | 0.02 |
| 0.5 | 0.07 | 0.16 | 0.07 |
| 0.3 | 0.04 | 0.23 | 0.14 |

The best result is **0.23**. A child heading dead at the zone scores low because the zone is small (1.2 m x 1.1 m) compared to how far the Gaussian spreads, and the answer swings wildly with `sigma_a`.
It would need a very low alarm threshold, which then fires for children who merely wander near. **We do not use this.**

### 6.2 What we use: the "hit fraction"

Different question: **of all the plausible straight-line paths this child could be on, what fraction reach the zone within the horizon `T_h = 3 s`?**

1. Sample `N` plausible states from the Kalman estimate: `(p_i, v_i) ~ Normal([p, v], P)` (position and velocity together, using the full 4x4 covariance).
2. For each sample, compute the time to entry with the exact ray test of 5.3.
3. Evidence `e` = the fraction of samples with `time_to_entry <= T_h`.

```
e = (1/N) * count( time_to_entry(p_i, v_i, zone) <= T_h )
```

This separates cleanly (computed, 3000 samples, pure hit fraction with independent position sigma 0.09 m and the velocity sigma shown):

| Situation | Evidence `e` |
| --- | --- |
| Heading straight at the zone, 2.2 s away, velocity sigma 0.10 m/s | 0.85 |
| Same, velocity sigma 0.15 | 0.70 |
| Same, velocity sigma 0.25 (a worse estimate) | 0.52 |
| Fast child (1.2 m/s) heading straight from 2.5 m away | 0.65 |
| Slow child (0.2 m/s) heading straight, 0.6 m away | 0.42 |
| Walking **parallel** past the zone | 0.10 |
| Walking **away** | **0.00** |
| Standing still, far away | **0.004** |

That is a sensible ordering, and it honestly drops as our velocity estimate gets worse (we should be less sure then).
`N = 200` samples per child per zone per frame is plenty (4 children x 2 zones x 200 samples x 8 Hz = 12,800 cheap ray tests per second; vectorized numpy).
The evidence is a Monte Carlo estimate, so it jitters by about 0.03 between frames on top of the real jitter in the estimated velocity; CUSUM (section 7) smooths both.

### 6.3 Already inside

If the child is **inside** the zone (signed distance below 0), evidence is 1.0 and the event type is `zone_entry` instead of `zone_entry_predicted`.

### 6.4 A standing child looks like a slowly drifting one (found by testing)

A child who stands still has an *estimated* velocity that is pure noise: with 12 cm measurement noise at 8 Hz the filter's velocity uncertainty settles near 0.23 m/s (section 3.5), so the estimate for a stationary child is typically 0.2 to 0.5 m/s in a random direction.
For a child 30 cm from the stairs, noise that happens to point at the stairs reads as "about to walk in". Two guards:

- **Ramp:** the velocity-based evidence is faded out for estimated speeds below 0.15 m/s (zero at 0.05, full at 0.15).
- **Shrinkage:** before sampling we shrink the velocity estimate toward zero by `max(0, 1 - c * sigma_v^2 / speed^2)`, with `c = 0.5`. A speed at the noise level is mostly cancelled; a clear walk keeps most of its evidence (computed, straight at the zone at 0.45 m/s: velocity sigma 0.10 goes 0.85 to 0.83, sigma 0.15 goes 0.71 to 0.66, sigma 0.25 goes 0.52 to 0.43, all above the 0.3 leak). The **countdown** shown to caregivers uses the unshrunk estimate.

Measured at the older threshold `h = 0.3` (100 runs of a 12 s child standing 10 to 30 cm from the stairs edge): alerts fire in 38% of runs with no shrinkage, 8% with `c = 0.5`, 2% with `c = 1.0` (at the chosen `h = 0.2` the `c = 0.5` rate is 25%, table 7.5). But at `c = 1.0` real threats start being missed (7 of 90 not alerted in time), so we use `c = 0.5`.
A child standing 10 to 30 cm from a staircase edge is arguably worth an alert; whether 8 to 25% of such runs is right is a product decision for M9.

### 6.5 End to end, on simulated children (computed; `tests/test_pipeline.py`)

Noisy 8 Hz detections, 12 cm measurement noise, tracker `sigma_a = 1.0`, evidence shrinkage 0.5, CUSUM `k = 0.3, h = 0.2`, 150 runs per scenario:

| Scenario | Result |
| --- | --- |
| Child heading at the stairs (various speeds 0.4 to 1.0 m/s, starts, small angles) | alerted **before** entry in 133 of 133 runs |
| Warning before entry | **median 1.25 s, 10th percentile 0.75 s** |
| Walking parallel to the stairs, walking away, standing 0.4 to 1.2 m away, standing far | **0 false alarms** in 150 runs each |
| Wandering the left of the room (up to 0.8 m/s, at least 1 m from the stairs) | 1 in 150 |
| Strolling in a loop 1.0 to 1.4 m from the stairs | 1 in 150 |
| Standing 10 to 30 cm from the edge | 38 of 150 (the case discussed in 6.4) |

**An earlier version of this table was wrong.** My first "non-threat" scenarios sent children running at the stairs from 0.6 m before turning, which really is a threat, and showed 10 to 18% "false alarms". The numbers above use realistic paths.

**What the warning time really is.** The alert comes about **1.25 s before the child steps onto the stairs** (0.75 s in the worst tenth). The 3 s horizon cannot give more: a child's velocity is only trustworthy after about a second of walking, and CUSUM adds 0.3 to 0.9 s on top. A longer 4 s horizon added only about 0.1 s.
So the product cannot stop a fast child from reaching the stairs; it gets a buzz to a caregiver while the child is about to arrive, and it makes sure someone owns the alert. Slow children and children who linger get more warning. This should be said plainly in the demo.

---

## 7. Deciding to alert: CUSUM

### 7.1 The problem

`e` is noisy. One frame of `e = 1` can be a glitch (a ghost detection, a wrong keypoint). We want to alert on **sustained** evidence, fast, with almost no false alarms.
A fixed threshold ("alert when `e > 0.7`") flaps. Averaging adds delay. The classic tool for "detect a sustained change quickly" is **CUSUM** (cumulative sum, Page 1954).
Code: `cusum.py`. Tests: `tests/test_cusum.py`.

### 7.2 The rule

```
S_0 = 0
S_t = max( 0 ,  S_{t-1} + (e_t - k) * dt )
alert when S_t >= h        (then S = 0 and a 60 s cooldown starts)
```

Plain words: keep a bucket `S`. Every moment, add the evidence **minus a leak `k`**. When the bucket is full to `h`, alert. Evidence below `k` drains the bucket, floored at zero.
So a brief spike barely fills it, and quiet time empties it.

Units: `S` is in "evidence-seconds", so the behaviour does not depend on the frame rate. A stalled frame counts for **at most 0.15 s** (`max_dt`): otherwise a 30 s pose-model hiccup followed by one bad frame would add a huge step and alert by itself (found by testing).
There is no upper clamp: the bucket is emptied at every alert and held at zero during cooldown, so it never exceeds `h` by more than one step.
A zone that is switched off by its schedule keeps its bucket at zero.

### 7.3 Where `k` comes from

CUSUM is the sum of log-likelihood ratios. For evidence that is roughly Gaussian with mean `mu0` when safe and `mu1` when dangerous (same spread), each term is proportional to `e - (mu0 + mu1)/2`.
So `k` is **halfway between typical safe evidence and typical dangerous evidence.** Safe is about 0.0 to 0.1, dangerous about 0.5 to 0.85 (6.2), so `k = 0.3` is the natural leak.

### 7.4 How fast does it fire? (computed)

If evidence stays at `e > k`, the bucket fills at `(e - k)` per second, so the delay is about `h / (e - k)`. With `k = 0.3`, **`h = 0.2`**:

| Sustained evidence `e` | Time to alert |
| --- | --- |
| 1.00 | 0.29 s |
| 0.85 | 0.36 s |
| 0.70 | 0.50 s |
| 0.52 | 0.91 s |
| 0.40 | 2.0 s |
| 0.30 or lower | never |

Frame-level behaviour at 8 Hz (computed): one frame of `e = 1` (a glitch) peaks at **0.0875**, no alert; two frames give 0.175, no alert; **three** frames of full evidence (0.375 s) alert.
After an alert `S` is reset to 0 and that (child, zone) pair is on **cooldown for 60 s**, so the buzzer does not retrigger.

### 7.5 Choosing `h` (measured, 150 runs per row)

`h` trades warning time against false alarms, with shrinkage 0.5:

| `h` | Alerted before entry | Median warning | 10th percentile | Strolling-near false alarms | Standing 0.1 to 0.3 m from the edge |
| --- | --- | --- | --- | --- | --- |
| 0.30 | 132 of 133 | 1.00 s | 0.62 s | 0 of 150 | 14 of 150 |
| **0.20** | **133 of 133** | **1.25 s** | **0.75 s** | **1 of 150** | **38 of 150** |
| 0.15 | 133 of 133 | 1.50 s | 1.00 s | 9 of 150 | 59 of 150 |

We chose **0.20**. 0.15 buys another quarter second but begins to fire on children strolling a metre away. These are simulated children; **M9 re-tunes `k` and `h` on your real footage** with `tune_cusum.py`, and the acceptable false-alarm rate (proposed: under one per hour per room) is a decision for you and a real provider.

Where we use CUSUM: zone entry (`k = 0.3, h = 0.2`), unsupervised (`k = 0.5, h = 5`, so full evidence takes 10 s), possible distress, climbing.
Fall is a state machine, not CUSUM (section 8.1).

---

## 8. The other detectors

Every detector produces a **stream of evidence** (or a state machine), then goes through the same rules: severity, cooldown, event type from the spec.

### 8.1 Fall (built and measured; `detectors/fall.py`)

**The rule.** A fall is a FAST downward drop of the body followed by staying genuinely LOW or HORIZONTAL. Everything is
measured in the person's own standing height, in the picture, so no calibration is needed:

```
drop : the top of the person's box moves down by >= 0.45 x standing height within 1.5 s
low  : box height < 0.65 x standing height, or wider than tall (w/h > 1.1), or torso > 60 deg from vertical
fall : low for >= 0.8 s, with the drop at most 3 s before the low phase began (or during it)
       gaps in detection up to 0.5 s do not reset "low"; one alert per 10 s per person
```

Standing height is the median box height while clearly upright (torso under 30 deg, taller than 1.3 x wide).
It uses low-confidence detections too (0.1): a person on the floor often scores low.
**Order matters, found by testing:** the body tilts first (low by angle) and the top drops a moment later. My first
version required the drop to come before the low phase and caught only 5% of real falls.

**Measured on real footage: OmniFall labels on the GMDCSA24 videos** (4 adults, staged falls at home, 160 clips: 78 falls,
82 everyday activities such as sitting down, lying down on purpose, walking). Same frames (12 fps, 640 px) and the same
scoring as the team's evaluator (a hit is an alert 0 to 5 s after the labelled start of the fall).

| Detector | Falls caught, all 160 | False alarms | Subject 4 only (17 falls, 20 everyday clips) | Delay |
| --- | --- | --- | --- | --- |
| Team's `server/events.py` (YOLO26n + ByteTrack) | 24 / 78 (31%) | 12 | 7 caught, 5 false alarms | 2.3 s |
| Ours, untuned start values | 67 / 78 (86%) | 23 | 13 caught, 5 false alarms | — |
| **Ours, tuned on Subjects 1 to 3** | **65 / 78 (83%)** | **10** | **9 caught, 3 false alarms** | **1.6 s** |

How to read it honestly:
- Subjects 1 to 3 were used for tuning, so "all 160" flatters ours. **Subject 4 is the only fair comparison**, and with
  17 falls the intervals are wide (recall 31% to 74%).
- On Subject 4 the tuned setting caught FEWER falls (9) than the untuned one (13). The best tuning settings were near-ties
  and sat at the edge of the grid: a sign of fitting three people's way of falling. Choosing by the worst tuning subject
  instead of the average gave the same setting. **Subject 4 is now used up as a test**; the next honest check needs
  footage neither detector has seen (CAUCAFall, 10 people in homes, or your own clips).
- **The pose model matters as much as the rule.** With the small model the person on the floor is still found in 89%
  of frames (nano: 69%); clips where the fallen person is mostly invisible drop from 24 to 7. Half the team detector's
  misses were the person being lost after the fall.
- Adults only. Nothing here says how it behaves for children, who fall differently and are smaller.

Tools: `scripts/cache_poses.py` (run the model once), `scripts/bench_falls.py` (score, tune with `--grid --robust`),
`scripts/eval_clips.py` (the whole pipeline on labelled clips; it reproduces the benchmark exactly).

### 8.2 Climbing

Hardest one from a single 2D camera, because height is not visible. Two weak signals, combined:
- **Hands up:** both wrist `v` coordinates above the shoulder line by more than `0.3 L` for at least 1 s.
- **Elevated:** the person's box height in pixels is larger than expected for that floor position. We learn the expected height `h_exp(v) = a*v + b` (a line in image row `v`) from standing children and adults, then `rho = h_obs / h_exp`. A child standing on furniture gives `rho > 1.25` **(start value)**.
- **Near a climbable thing:** only evaluated within 0.5 m of a zone marked `climbable` (fence, shelf, gate). That needs a flag on zones; it is not in the spec yet. Without it, this detector would fire on children reaching for toys.

Evidence is the product of the three signals (each in 0 to 1), then CUSUM. Honestly this is the detector most likely to need a second camera angle or to be cut.

### 8.3 Prolonged stillness

```
M      = median over keypoints of  |kp_t - kp_{t - 1s}| / L        "motion energy"
still  = ( s_hip < 0.05 m/s )  and  ( M < 0.03 )
event  = still continuously for T_still   (start value 90 s)
```

Not during a **nap schedule** in a nap area: lying still then is normal. Outside nap hours or outside the nap zone it is the event. Severity: medium. This one also needs the schedule data from Spacetime.

### 8.4 Unsupervised child (built; `detectors/unsupervised.py`)

```
d_a(c)   = distance from child c to the nearest visible TAGGED adult, in meters on the floor
e_t(c)   = 1 / (1 + exp(-(d_a - R) / w))      R = 2.0 m, w = 0.4 m          (1.0 if no tagged adult is in view)
alert    : CUSUM with k = 0.5, h = 5 evidence-seconds (about 10 to 12 s alone), then 120 s cooldown; severity medium
```

**It stays off until someone has been tagged as an adult.** Adults are only known from the dashboard's tags; without
one, every person counts as a child alone and it would alert on everybody after 10 s. Tested: a child 3 m from the tagged
adult alerts once after about 10 to 12 s; a child 1 m away never does; with nobody tagged it never fires.
Weakness: an adult standing in a blind spot looks absent. The worker's second opinion is meant to catch that. Not yet
measured on real footage (needs a recording with tagged adults).

### 8.5 Possible distress

Honest status: **this is a guess, not a measurement.** Vision cannot hear crying. Proxy features, experimental and low weight:
- very high speed (above 1.5 m/s) toward an exit with no adult nearby,
- hands to face: wrist-to-nose distance below `0.5 L`, sustained, while the child is alone,
- sudden collapse in height followed by stillness (overlaps with the fall detector).

I recommend shipping this as **medium severity, disabled by default**, and letting the second-opinion step review it. If you want, we can drop it from the first demo.

### 8.6 Child not visible, and head count

```
child_not_visible : a confirmed child track is lost for > 2 s,
                    AND its last position was farther than 0.5 m from any blind spot and from the frame edge.   -> severity low
head_count_mismatch : the median visible-child count over the last 5 s differs from the expected count
                      for more than 15 s.                                                                        -> severity low
```

The expected count must come from somewhere. It is not in the spec as an input; the simplest option is a number the caregiver sets at roll call on the dashboard. **Decision needed (section 13).**

---

## 9. Privacy: face blur and saved clips

Rule from the spec: raw video never leaves the computer, and faces are blurred **before** anything is saved or sent.
Code: `evidence.py`. Tests: `tests/test_evidence.py` (they use real photos with real faces and an independent face detector).

### 9.1 What gets blurred, in three layers

1. **Pose heads.** For each person the pose model reports, a box around the head keypoints (0 to 4: nose, eyes, ears), found at full size and scaled down.
   Center = confidence-weighted mean of the confident head keypoints. Side = the largest of: 1.8 x ear distance, 3.0 x eye distance, 1.6 x the spread of the head keypoints, 0.5 x torso length, and a floor of **0.17 x the person's box height** (children's heads are large). Then a 25% margin.
   No head keypoint at all: the top 30% of the person's box. The ratios are rough human proportions, **not facts**.
2. **A dedicated face detector** (YuNet, 232 KB ONNX, from OpenCV's model zoo, `weights/face_detection_yunet_2023mar.onnx`) run on every saved frame, with a sensitive threshold (0.25) and every box grown 1.5x. Its boxes are blurred in addition to layer 1.
   This is the safety net for people the pose model does not see (found by testing: in the sample photo an out-of-focus person at the edge was not detected as a person at all, and a man bending over had a head box that covered only his lower face).
3. **A trail.** Boxes from the last 3 frames are blurred too, so a moving head is covered despite model latency.

The blur step uses a **more sensitive** setting than anything that checks it (blur threshold 0.25, check threshold 0.3), so a check cannot find a face the blur skipped.
Recording **refuses to start** if the face detector model is missing.
Limit: faces smaller than about 10 pixels in the 640-wide saved frame can be missed by the face detector; the pose heads cover the main people. A face the pose model and the face detector both miss will not be blurred. This is a real residual risk; real footage in M9 is the test.

### 9.2 The blur itself, and why 4 blocks (measured)

The region is reduced to a grid of average colours and then lightly smoothed; what is left cannot be sharpened back.
**My first choice, 8 x 8 blocks, was not enough.** A face detector still found faces in 8-block pictures (in the sample photo, when the face detector alone did the blurring, a 42-pixel face was still found at **0.83 confidence** in the same place and size, and 12% of its fine detail remained).
Measured on two real photos, worst case over every clear face:

| Blocks across | Detector still finds a matching face | Fine detail kept |
| --- | --- | --- |
| 8 | yes, 0.30 with pose, **0.83 with the face detector only** | 11.7% |
| 6 | no | 4.0% |
| **4 (our default)** | **no** | **1.3%** |
| 3 | no | 0.8% |

So the default is **4 blocks** (`EvidenceConfig.blur_cells`): a person-shaped blob, so a caregiver can still see where the child was and what they were doing, but no face.
"Fine detail" is the energy left above a 16 x 16 grid, where eyes, nose and mouth live. (A Laplacian is fooled: the pixel blocks make sharp edges of their own.)

**How we test that blurring works.** "A face detector finds no face after the blur" is the wrong test: the detector hallucinates huge low-confidence faces over a blurred blob.
The right test is, for every clear face in the original (score 0.6 or more): no detection in the blurred picture at the same place and similar size, **and** at most 5% of its fine detail left. This runs on the full-size path, the "pose model sees no one" path, the saved clip's first frame and every key frame.

**Fail closed:** if blurring or encoding throws, the frame is dropped (that moment is simply not recorded) and counted; it is never saved as it was.

### 9.3 Never keep raw frames

The frame is shrunk to 640 px wide **first** and only the shrunk copy is blurred, because only the shrunk copy is ever stored (4x less work, measured: 8.9 ms per frame instead of 28.9).
The recorder keeps **compressed blurred JPEGs** (about 40 KB each), not raw frames. A test proves it holds no reference to the raw picture after `add()` (the object is freed).
Ring buffer: 11 s of frames at 15 fps is about 6 MB (the raw equivalent would be 104 MB).

On an event the buffer is cut into a clip (about 5 s before and 5 s after the alert) and 3 key frames (1 s before, at, and 1.5 s after), written by a **background thread** so the camera loop never waits.
The clip is **H.264** (checked with ffprobe; plays in a browser), written to a temporary name and renamed when complete, so a clip appears whole or not at all. The clip name must match `evt_<digits>_t<digits>`; anything else (such as `../../x`) is refused.
Clips and key frames older than 7 days (`retention_days`, your call) are deleted by `cleanup()`.
The worker only ever gets the 3 key frames, over HTTPS, kept 24 h (spec; built in Phase 5).

## 10. Timing and latency

Target: from the moment a child's path first meets the zone rule to the buzzer vibrating, **under one second**. Measured on simulated children the alert fires a median **1.25 s before entry** (section 6.5); the transport delay below comes out of that.

| Stage | Expected | How we keep it low |
| --- | --- | --- |
| Capture | 33 to 66 ms | A reader thread overwrites its single "latest frame" slot. If processing is slow we skip frames instead of falling behind. |
| Pose model | **measured on this M5 laptop** (below): 7.6 ms nano and 15.9 ms small on the GPU at 640 px | Smallest model that is accurate enough; GPU (Apple MPS) when available; warm up once at start-up (the first call takes about a second). |
| Tracking + geometry + evidence | under 5 ms | Vectorized numpy; no Python loops over samples. |
| CUSUM delay | 0.3 to 0.9 s (section 7.4) | This is the deliberate price of avoiding false alarms. |
| Spacetime write + buzzer message | 20 to 100 ms local network, more over the internet | The buzzer is told **directly** over the local WebSocket; the Spacetime write happens in parallel, so the buzzer does not wait on the cloud. |

**Pose model speed, measured (`scripts/bench_pose.py`, Apple M5, 24 GB, 1280x720 input, median of 40 frames after warm-up):**

| Model | Device | 640 px | 480 px | 320 px |
| --- | --- | --- | --- | --- |
| yolo26n-pose | GPU (mps) | 7.6 ms (131 fps) | 5.1 ms | 6.7 ms |
| yolo26n-pose | CPU | 18.4 ms (54 fps) | 12.8 ms | 7.2 ms |
| yolo26s-pose | GPU (mps) | **15.9 ms (63 fps)** | 11.8 ms | 10.6 ms |
| yolo26s-pose | CPU | 36.4 ms (27 fps) | 23.3 ms | 12.1 ms |

A camera delivers 15 to 30 frames a second, so even the small model on the CPU keeps up with a 15 fps camera, and on the GPU it uses a quarter of a 15 fps frame budget. We default to the **small model on the GPU at 640 px** (`PoseConfig`).
The nano model produced a duplicate detection of one partly visible person in the sample photo (two boxes, IoU 0.68); the small model did not, and gave higher confidences (0.72 to 0.89 vs 0.35 to 0.86). `dedupe()` removes such duplicates (IoU above 0.55) for either model.
Caveats: this is one fast laptop. The daycare's computer may be slower; the numbers above show roughly how much room there is (the small model on CPU at 480 px is 43 fps here). The people count in the sample photo is the only accuracy check so far; real accuracy on children, small bodies and your camera angle is unknown until M9.

**Timestamps:** the Kalman `dt` and all speeds use the **capture** time (for RTSP, the stream's presentation time when available). Using processing time would make velocities wrong whenever the pose model is slow.

---

## 11. How we test each piece

All pieces are pure functions of numbers, so each gets a numpy test with known answers *before* it ever sees a camera.

| Piece | Test | Pass when |
| --- | --- | --- |
| Homography | Pick a random `H`, generate points, recover it | Relative error under 1e-9 with no noise. With 1 px noise: under 2 cm RMS in the example geometry. Collinear points are rejected. Results match `cv2.findHomography`. |
| Calibration report | Wrong click on purpose | Held-out error exceeds the 5 cm limit and the report names the bad point. |
| Kalman | Simulate a child with random kicks and noisy measurements | Position RMSE below measurement noise; average NIS near 2, average NEES near 4. |
| Hungarian tracker | Two tracks crossing at the same speed; one frame drops out; ghost detections | No ID swap in the scripted cases; ghosts never become confirmed tracks. |
| Geometry | Random points and polygons | Our point-in-polygon equals `shapely` always; time-to-entry matches the analytic answer (e.g. the 2.222 s example). |
| Evidence | The table in 6.2 as **regression tests** | Heading at zone at least 0.5; away 0.0; far and still under 0.01; ordering of the table preserved. |
| CUSUM | Glitch, sustained, and recovery traces | One-frame glitch never alerts; sustained `e >= 0.52` alerts in under 1.5 s; cooldown works; Monte Carlo false alarm rate under target. |
| Fall detector | Synthetic keypoint sequences first, then UR Fall clips | Fires on falls, silent on sit, bend and stumble-recover. We report precision and recall, not "it works". |
| Privacy | Run the blur on frames with known face positions | No head keypoint region is left unblurred; with a forced error, no frame is written. |
| Whole pipeline | A recorded video replayed through `scripts/replay.py` | Positions on the floor plan look right; events appear with sensible predicted times; end-to-end latency measured and logged. |

---

## 12. What we build in Phase 3 (the list)

Folder `vision/` (Python 3.11+; a virtual environment already exists at `vision/.venv` with numpy, scipy, shapely).

```
vision/
  pyproject.toml
  nestwatch_vision/
    config.py          all tunable numbers from the parameter table, in one place
    geometry.py        point-in-polygon, distance, ray-entry time              (section 5)
    calibration.py     DLT homography, normalization, reprojection report      (section 1)
    kalman.py          constant-velocity filter                                (section 3)
    tracker.py         tracks, Mahalanobis gating, Hungarian, life cycle, tags (sections 3, 4)
    prediction.py      hit-fraction evidence                                   (section 6)
    cusum.py           CUSUM with cooldown                                     (section 7)
    zones.py           cache of zones and schedules from Spacetime             (section 5.4)
    detectors/         fall.py climbing.py stillness.py unsupervised.py distress.py lost.py headcount.py  (section 8)
    capture.py         camera readers (USB, RTSP, phone camera)
    pose.py            Ultralytics pose model wrapper, keypoint filtering and smoothing (section 2)
    evidence.py        blur, ring buffer, clip and key-frame saving            (section 9)
    sync.py            talks to Spacetime                                      (decision in 13)
    local_api.py       HTTP + WebSocket on the local network (/snapshot /calibrate /tag-adult /clips /keyframes /health /buzzer)
    alarm.py           local speaker alarm
    main.py            wires it together
  scripts/
    replay.py          run a recorded video through the pipeline
    tune_cusum.py      Monte Carlo tuning of (k, h)
  tests/               one file per module, the tests in section 11
```

### Milestones, in the order I recommend

| # | Milestone | You and I review the math together? | What you can see afterwards | My time (rough) |
| --- | --- | --- | --- | --- |
| M1 | `geometry.py` + `calibration.py` + tests | **Yes, first.** Sections 1 and 5. | Calibrate from four clicks on a test image; see error in meters | 30 to 45 min |
| M2 | `kalman.py` + `tracker.py` + tests on simulated people | **Yes.** Sections 3 and 4. | Simulated children tracked through crossings, plots of errors | 45 to 60 min |
| M3 | `prediction.py` + `cusum.py` + `zones.py` + tests | **Yes.** Sections 6 and 7. | The 6.2 and 7.4 tables as live tests; a plot of evidence and bucket `S` over a scripted walk | 30 to 45 min |
| M4 | `pose.py` + `capture.py` on a real webcam | No math | Live keypoints drawn on your camera | 30 to 45 min |
| M5 | Wire M1 to M4: camera to floor positions to `fake`-style events | Review thresholds | Real movement shows up on the dashboard floor plan | 45 min |
| M6 | `evidence.py` (blur, clips, key frames) + privacy tests | Section 9 | Blurred clips of a staged event | 30 to 45 min |
| M7 | `sync.py` + `local_api.py` + `alarm.py` + buzzer WebSocket | No math | The real dashboard driven by the real camera; `/snapshot`, `/calibrate` working from Setup | 45 to 60 min |
| M8 | Other detectors: fall, unsupervised, stillness, then climbing and distress | **Yes.** Section 8. | Fall and unsupervised events on staged footage | 60 to 90 min |
| M9 | Tuning pass on real footage (`tune_cusum.py`, threshold review) | Together, on your videos | Documented chosen values and measured error rates | 60 to 120 min, **needs your footage** |

Total about 6 to 9 hours of my work, most of the uncertainty in M8 and M9.

### Dependencies to install (into `vision/.venv` only)

Already installed: `numpy`, `scipy`, `shapely`. Needed later: `opencv-python`, `ultralytics` (large; pulls in PyTorch), `fastapi` + `uvicorn` + `websockets` for the local API, `pytest`.
Pose model: the weight file name is a **config value**, not hard-coded. You asked for YOLO27 (`yolo27n-pose.pt`), but as of today the Ultralytics docs list YOLO27 as unreleased ("coming soon", a waitlist), and say its examples do not work with the current package. Until it is released we use **YOLO26 pose** (`yolo26n-pose.pt` to start; `yolo26s-pose.pt` if accuracy needs it). All of them output the same COCO 17 keypoints, so section 2 does not change and swapping to YOLO27 later is a one-line config change plus a re-run of the tests.
Weights are downloaded by Ultralytics on first run (a small file; I will tell you before it downloads).

---

## 13. Decisions I need from you

1. **Camera hardware:** how many cameras, USB webcam or phone, and what resolution and frame rate? (This sets the pose-model size and whether we need two homographies.)
2. **Test footage:** can you record 5 to 10 minutes of the actual room, with someone walking, sitting, crouching, lying down, and a staged fall onto a mat? Without real footage, M9 and every threshold marked **(start value)** stays a guess.
3. **Floor markers:** can you put four to six taped markers on the floor of the demo room and measure them with a tape measure? Calibration is only as good as those measurements.
4. **Spacetime link from Python: decided and verified.** Plain HTTP works against a local server: `POST /v1/database/<db>/call/<reducer>` with the vision identity's token as a bearer token and a JSON array of arguments (products as arrays in field order, options as `{"some": x}` or `{"none": []}`); `POST .../sql` with the SQL text for reads (rows come back as arrays; an option is `[0, value]` for some and `[1, []]` for none). `sync.py` implements it, sends from a background thread, queues events while the server is unreachable, and polls the zones once a second. No Python SDK is needed. Not yet tested on Maincloud (needs the module published there).
5. **Head-count source:** a number typed at roll call on the dashboard (needs one small field and reducer in Spacetime)? Or drop `head_count_mismatch` from the demo?
6. **Distress detector:** ship experimental and off by default, or leave it out of the first demo?
7. **Climbable flag on zones:** needed for the climbing detector (section 8.2). Add it, or cut climbing from the first demo?
8. **Acceptable false alarms:** what is "too many"? I proposed under 1 per hour per room. A real provider's answer would be better.
9. **Compute device:** Apple Silicon (MPS) or CPU only? Affects frame rate.

---

## 14. Parameter table and references

All of these live in `config.py`. Every one marked "start" must be re-checked on real footage.

| Parameter | Start value | Section |
| --- | --- | --- |
| Keypoint confidence floor | 0.3 | 2 |
| Prediction horizon `T_h` | 3 s | 6 |
| Kalman `sigma_a` (tracking) | 1.0 m/s^2 | 3.6 |
| Measurement noise: ankles / one ankle / box bottom | 0.10 / 0.15 / 0.25 m | 3.3 |
| Initial velocity sigma | 1.0 m/s | 3.6 |
| Speed cap | 3 m/s | 3.6 |
| Gate (chi-squared, 2 dof, 99.9%) | 13.82 (was 9.21; see 4.3) | 4.3 |
| Tentative to confirmed | 3 hits in 5 frames | 4.4 |
| Lost-track timeout | 2 s | 4.4 |
| Re-identification window | 3 s and 1 m | 4.5 |
| Zone padding | 2 cm | 5.1 |
| Evidence samples `N` | 200 | 6.2 |
| Speed ramp (evidence faded out) | 0.05 to 0.15 m/s | 6.4 |
| Velocity shrinkage `c` | 0.5 | 6.4 |
| CUSUM zone entry `k`, `h` | 0.3, 0.2 | 7.5 |
| CUSUM unsupervised `k`, `h` | 0.5, 5 | 7.5 |
| CUSUM max step per frame | 0.15 s | 7.2 |
| Cooldown per (child, zone) | 60 s | 7.4 |
| Fall: angle rise / head drop / lie-still time | 45 deg / 1.0 L/s / 1.5 s | 8.1 |
| Stillness time | 90 s | 8.3 |
| Unsupervised `R`, `w` | 2.0 m, 0.4 m | 8.4 |
| Calibration error limit | 5 cm | 1.6 |
| Clip retention | 7 days | 9.3 |
| Blur blocks across | 4 (8 was not enough) | 9.2 |
| Face-detector blur threshold / grow | 0.25 / 1.5x | 9.1 |
| Head box floor | 0.17 x person box height | 9.1 |

### References (for when you want the long version)

- R. Hartley and A. Zisserman, *Multiple View Geometry in Computer Vision*: homography, DLT, normalization.
- Y. Bar-Shalom, X. R. Li, T. Kirubarajan, *Estimation with Applications to Tracking and Navigation*: Kalman filter, gating, NEES/NIS consistency tests.
- H. W. Kuhn (1955), "The Hungarian method for the assignment problem".
- E. S. Page (1954), "Continuous inspection schemes": CUSUM. A. Wald, *Sequential Analysis*: the likelihood-ratio view behind it.
- G. Casiez, N. Roussel, D. Vogel (2012), "1 Euro Filter": the keypoint smoothing.
- B. Kwolek and M. Kepski (2014), "Human fall detection on embedded platform using depth maps and wireless accelerometer", *Computer Methods and Programs in Biomedicine* 117(3): the UR Fall dataset paper (cited on the page you shared).

### 8.1a Fresh test on CAUCAFall (2026-10-24)

All 100 CAUCAFall clips (10 subjects, 50 falls, 50 everyday; CC BY 4.0, OmniFall labels), never used for tuning.
YOLO26s poses, the shipped `FallConfig` defaults, the team's scoring rule (hit = alert 0-5 s after onset).

| | Result | 95% interval |
| --- | --- | --- |
| Falls caught | 37/50 (74%) | 60-84% |
| Precision | 74% (13 false alarms) | 60-84% |
| Everyday clips with a false alarm | 12/50 (24%) | 14-37% |
| Median delay | 1.8 s | |

By kind: backwards 7/10, forward 9/10, left 7/10, right 9/10, sitting 5/10. False alarms: pick up object 6,
kneel 4, sit down 2, forward-fall clip 1, hop 0, walk 0. Bending to the floor is the main confusion.
The team's detector on the same clips (their evaluator, their scoring): 15/50 caught (30%, 19-44%), 9 false alarms
(precision 62%, 43-79%) on 8/50 everyday clips, mean delay 3.0 s. Ours catches more than twice as many falls; its
false-alarm rate is a little higher (12/50 vs 8/50 everyday clips, intervals overlap).
Rebuild: `scripts/make_caucafall_labels.py`, `scripts/cache_poses.py`, `BENCH_DATA=.../omnifall_caucafall scripts/bench_falls.py`.

### 8.1b Trying to cut false alarms (2026-10-24)

Question: can the fall rule keep catching falls and stop alarming on kneeling, picking things up and sitting down?
Data: both OmniFall datasets pooled (260 clips). Tuning people: GMDCSA24 Subjects 1-3 and CAUCAFall Subjects 1-7 and 10
(102 falls). Test people, never used to choose: GMDCSA24 Subject 4 and CAUCAFall Subjects 8-9 (26 falls).

What separates true alerts (102) from false ones (23): measured at each alert, ranked by how consistently they separate
the two across both datasets.

| Measurement | Separates? | Note |
| --- | --- | --- |
| aspect (width / height) | partly (0.78, 0.69) | true falls end wide, median 1.84 vs 0.81 |
| height ratio | partly | true median 0.44 vs 0.61 |
| speed of the drop | partly (0.64, 0.79) | true median 1.10 vs 0.78 standing heights per second |
| torso angle, time spent low | no | forward falls and bending to pick something up both give inverted torsos |
| head position | one dataset only | 0.06 on GMDCSA24, 0.62 (reversed) on CAUCAFall |

Search: 648 settings of the existing knobs, now including the torso-angle threshold, ranked by the worst tuning person's F1.
The best setting ties the current defaults on the tuning people (F1 0.83 both; 86 caught / 20 false vs 84 / 16). On the
test people it caught 22 of 26 against 18 of 26 (85% vs 69%; 66-94% vs 50-83%) with 8 false alarms against 7: a gain of four
clips, inside the noise. Not adopted.

Speed gate (alert only if the drop was at least X standing heights per second), tuning people / test people:

| X | caught (tune) | false (tune) | caught (test) | false (test) |
| --- | --- | --- | --- | --- |
| 0 (now) | 84/102 | 16 | 18/26 | 7 |
| 0.7 | 73 | 11 | 16 | 4 |
| 0.8 | 66 | 9 | 15 | 2 |
| 1.0 | 51 | 4 | 11 | 1 |

False alarms fall about as fast as catches do, so F1 never improves. Conclusion: with one camera and the signals above,
fewer false alarms costs real falls; the choice is an operating point, not a fix. A real improvement needs something new
(for example a classifier trained on pose sequences from far more labelled falls, or a second look from Claude).
Tools: `scripts/analyze_falls.py` (measurements per alert), `scripts/tune_falls.py` (the search with held-out people).

### 8.5 A child the camera lost (`child_not_visible`, 2026-10-24)

Spec: "a child's track is lost: last position kept for about 2 s, then a `child_not_visible` event; low alert."
The tracker already marks a confirmed track lost after `lost_timeout` = 2 s. Reporting then would fire on tracking
glitches, so `detectors/not_visible.py` applies three more checks before the low alert:

1. the child stays lost for `grace_s` = 1 s, and a new track that takes the old identity (MATH 4.5) cancels it;
2. the child was tracked for at least `min_age_s` = 3 s, so a flicker is not a missing child;
3. no other untagged child is within `near_m` = 1 m of where it was last seen (a duplicate track dying while the same
   child is still visible is not a missing child).

Adult-tagged tracks are never reported. Total delay from the last sighting: about 3 s. Severity low, so it is shown in
the apps and never buzzes or escalates. Tests: a child who vanishes for good raises one alert 8.5 to 9.5 s into a run
where they disappear at 6 s; hidden 2.2 s raises none; one second of detections raises none. Not yet measured on footage
of a real room: the alerts per hour will depend on blind spots and doorways, so tune `near_m` and `grace_s` there.

### 8.1c The reference build's second fall path (2026-10-24)

The team's reference build (commit 17cca7a) also calls a fall when the body height collapses (from at least 0.85 to at most
0.70 of standing height within 1.5 s) and stays low and not lying wide for 1.5 s, begun with a hand at the floor: a fall onto
hands and knees toward the camera. Added as `FallConfig.collapse_path`, measured with `scripts/tune_falls.py`'s people split:

| | Tuning people: caught / false | Held-out people: caught / false |
| --- | --- | --- |
| Current rule | 84/102 / 16 | 18/26 / 7 |
| + collapse path | 84/102 / 23 | 19/26 / 9 |

Seven more false alarms and no extra catch on the tuning people; on the held-out people one more catch for two more false
alarms. A hand on the floor while low is exactly kneeling and picking something up, our main false alarms (8.1b). Off by default.

### 8.6 Hands at the throat, rhythmic movement, stillness (2026-10-24)

Ported from the reference build's `server/events.py` into `detectors/behaviour.py` (lengths in the person's torso length, which
is about a third of the reference's body length, so its 0.02 and 0.04 body lengths become 0.06 and 0.12 torso lengths):

| Event | Rule | Severity |
| --- | --- | --- |
| `possible_distress` | both wrists within 0.25 torso lengths of the throat point (35% of the way from the shoulders to the nose); CUSUM k = 0.45, h = 0.8 evidence-seconds, so about 1.5 s of both hands; one hand alone (score 0.4) never builds up | high |
| `rhythmic_movement` | at least 8 frames a second; over 6 s, at least two of wrists and ankles whose movement (drift removed) is above 0.06 torso lengths RMS with its strongest frequency in 1-5 Hz and over 60% of its power at that peak and its first harmonic; CUSUM k = 0.3, h = 3 | high |
| `stillness` | mean keypoint movement over 2 s under 0.12 torso lengths for 30 s; never during the `nap_time` schedule; only for a person the floor tracker follows, so a coat or doll cannot raise it | medium |

What was measured: synthetic tests (both hands alert at 1.3 to 1.8 s; one hand, a brief touch, waving at 0.5 Hz, pose jitter,
walking, 5 frames a second and nap time do not alert). On all 260 OmniFall clips (38 minutes: walking, sitting, kneeling, picking
up, hopping and 128 falls) the three rules raised **no** alert. With zero events in 0.63 hours the 95% upper bound is about 4.7
false alarms an hour, so this is a weak bound, not a rate. No labelled choking or seizure footage exists in these datasets, so
**how often a real event is caught is unknown**; these remain "check now" signals, and stillness (30 s) could not be exercised
on clips this short.
