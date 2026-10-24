# The math behind NestWatch: how it was built and how it was optimized

This document explains every formula the system actually runs, why each one is shaped the way it is, and what testing changed. Formulas are written in LaTeX (`$…$`, `$$…$$`); view it on GitHub or in any Markdown viewer with math support. Numbers marked **measured** come from runs recorded in [IMPROVEMENT_LOG.md](IMPROVEMENT_LOG.md); the rest are definitions or derivations.

Requirement IDs (DET-9, AI-1, …) refer to [SPEC.md](SPEC.md). Code locations are given as `file.py`.

## 0. The pipeline in one picture

Every analyzed frame (12 per second) passes through the same chain:

```
frame (640 px JPEG)
 → YOLO26n-pose + ByteTrack        boxes, 17 keypoints, stable track IDs        server/vision.py
 → ground point (u, v)             where the person touches the floor           §1
 → homography H                    image → floor plane in meters                §2
 → Kalman filter per person        position + velocity, with honest noise       §3
 → Monte Carlo over velocities     P(enter a zone within 3 s)                   §4   server/predict.py
 → keypoint rules                  throat, fall, rhythm, stillness              §6   server/events.py
 → CUSUM evidence gate             no single noisy frame can alert              §5
 → incident → escalation → record  (Claude only after this point)               §9
```

Two design principles run through all of it:

1. **Unknown is not "outside".** If a measurement is missing (feet cut off, keypoint hidden, track lost), the code reports *unknown* and the state machines hold or reset; it never concludes the safe thing.
2. **Evidence accumulates over time, in physical units.** Thresholds are in seconds, meters and body lengths, so they mean the same thing at 8 fps or 30 fps and at any distance from the camera.

---

## 1. Where is the person standing? (the ground point)

A pose model gives a box and 17 body points per person. For zone checks we need the one point that touches the floor.

**First version:** the mean of the two ankle keypoints.

$$(u, v) = \Big(\overline{x}_{\text{ankles}},\ \max y_{\text{ankles}}\Big)$$

**Problem found by the evaluation harness.** On a clip where a person walked just *beside* a zone, both the boundary rule and the early warning fired. The ankle *joint* sits roughly 4–5 % of body height above the floor contact point, so in the image the person appeared to stand a little closer to the camera than they were, and a person 1–2 % of the frame outside a zone's edge counted as inside.

**Current version:** horizontal position from the ankles (or the box center if they're hidden), vertical position from the **bottom of the box**, where the soles meet the floor:

$$u = \overline{x}_{\text{ankles}}\ \ (\text{else } x_{\text{box}} + \tfrac12 w_{\text{box}}),\qquad v = y_{\text{box}} + h_{\text{box}}$$

If the box touches the bottom edge of the frame ($v \ge 0.98$), the soles are off-screen, so $v$ comes from the ankles; if those are hidden too, the position is **unknown** (`None`).

**Measured:** false alarms on the three test clips went from 2 to 0, and both real detections were kept.

---

## 2. Image → floor plane (homography)

The camera sees the room at an angle, so "inside the zone in the picture" is not "inside the zone on the floor". A **homography** is the 3 × 3 matrix $H$ that maps points on one plane (the floor) between two views. Using homogeneous coordinates:

$$\begin{bmatrix} x' \\ y' \\ w \end{bmatrix} = H \begin{bmatrix} u \\ v \\ 1 \end{bmatrix},\qquad (X, Y) = \left(\frac{x'}{w},\ \frac{y'}{w}\right)$$

$H$ has 8 degrees of freedom (it is defined up to scale), so 4 point pairs determine it exactly. The operator clicks floor points on the video and types their positions in meters; `cv2.findHomography` solves for $H$ (least squares below 6 points, RANSAC with a 0.15 m threshold from 6 up, in `Calibration.fit`).

The inverse $H^{-1}$ maps floor points back into the image, which is how the predicted path is drawn on the video.

### 2.1 Rejecting a bad calibration (and the check that was too weak)

With exactly 4 points the fit is perfect no matter what you typed, so there is nothing to check. With more points, we can compare each clicked point with where the *other* points say it should be. Let $e_i = \lVert H(u_i, v_i) - (X_i, Y_i)\rVert$ be point $i$'s reprojection error in meters.

**First rule:** reject if the *mean* error exceeds 0.15 m.

$$\frac1n\sum_i e_i > 0.15\ \text{m}\quad\text{(too weak)}$$

**Why it failed.** A single mistyped measurement of 0.6 m was spread by the least-squares fit over all five points, giving a *mean* of only 0.14 m, below the limit, so the bad calibration was accepted.

**Current rule:** reject if the *worst* point is off by more than 0.15 m:

$$\max_i e_i > 0.15\ \text{m}\ \Rightarrow\ \text{reject, and name the point}$$

A 0.3 m typo is now rejected with "Point 5 is 0.20 m from where the other points place it", while a 0.1 m measurement slip (about normal tape-measure error) is accepted. Because 4 points always fit exactly, the interface recommends 5 or more.

### 2.2 Far-away positions are less certain (the Jacobian)

One pixel covers more floor far from the camera than near it. If we treated all positions as equally precise, the filter in §3 would over-trust distant measurements. We push image noise through the *local linearization* of the map, its Jacobian $J = \partial(X,Y)/\partial(u,v)$.

With $H = (h_{ij})$ and $x' = h_{11}u+h_{12}v+h_{13}$, $y' = h_{21}u+h_{22}v+h_{23}$, $w = h_{31}u+h_{32}v+h_{33}$, the quotient rule gives

$$J = \frac{1}{w^2}\begin{bmatrix} h_{11}w - x'h_{31} & h_{12}w - x'h_{32}\\[2pt] h_{21}w - y'h_{31} & h_{22}w - y'h_{32}\end{bmatrix}$$

The floor-plane measurement noise is then the propagated image noise plus a small floor-level term:

$$R_{\text{floor}} = J\,\big(\sigma_{\text{img}}^2 I\big)\,J^\top + \sigma_{\text{floor}}^2 I,\qquad \sigma_{\text{img}} = 0.01,\ \ \sigma_{\text{floor}} = 0.02\ \text{m}$$

($\sigma_{\text{img}} = 1\,\%$ of the frame.) A test checks $J$ against a finite-difference derivative to 4 digits.

---

## 3. Tracking position and velocity (Kalman filter)

Detections jitter by a few centimeters frame to frame, so velocity computed by subtracting consecutive positions is mostly noise. A **Kalman filter** combines a motion model with each noisy measurement and also tells us how uncertain its estimate is.

State and constant-velocity model, one filter per person:

$$\mathbf s = \begin{bmatrix} X\\ Y\\ \dot X\\ \dot Y\end{bmatrix},\qquad F = \begin{bmatrix}1&0&\Delta t&0\\0&1&0&\Delta t\\0&0&1&0\\0&0&0&1\end{bmatrix},\qquad C = \begin{bmatrix}1&0&0&0\\0&1&0&0\end{bmatrix}$$

Children change direction and speed abruptly, so we do not assume constant velocity forever: we assume **white acceleration noise** with $\sigma_a = 1.5\ \text{m/s}^2$, which gives the process noise

$$Q = \sigma_a^2\, G G^\top,\qquad G = \begin{bmatrix}\Delta t^2/2 & 0\\ 0 & \Delta t^2/2\\ \Delta t & 0\\ 0 & \Delta t\end{bmatrix}$$

(The larger $\Delta t$ is, the more the filter's uncertainty grows between measurements.)

**Predict**, then **update** with the floor measurement $\mathbf z = (X, Y)$ and the §2.2 noise $R_{\text{floor}}$:

$$\hat{\mathbf s}^- = F\hat{\mathbf s},\qquad P^- = FPF^\top + Q$$
$$S = CP^-C^\top + R_{\text{floor}},\qquad K = P^-C^\top S^{-1}$$
$$\hat{\mathbf s} = \hat{\mathbf s}^- + K(\mathbf z - C\hat{\mathbf s}^-),\qquad P = P^- - KSK^\top$$

A new track starts at the measured position with velocity $0 \pm 0.5\ \text{m/s}$. The block $P_{vv}$ of $P$ (the velocity covariance) is what the next section samples from. A test confirms the filter recovers a 1 m/s walk from 3 cm of noise to within 0.15 m/s.

Identity matching across frames (which detection is which person) is done by Ultralytics' ByteTrack, which uses the same Kalman-plus-assignment ideas in image space; ours only handles the floor-plane estimate.

---

## 4. Will they enter the zone within 3 seconds? (Monte Carlo)

The earlier design computed one time-to-entry from a single velocity. That ignores uncertainty: a child standing still with jittery velocity estimates would flicker between "heading for the zone" and "not". Instead we ask for a **probability**.

Draw $N = 200$ plausible velocities from the filter's own uncertainty,

$$\mathbf v^{(n)} \sim \mathcal N\big(\hat{\mathbf v},\ P_{vv}\big),\qquad n = 1,\dots,N$$

and for each, find when the straight-line path $\mathbf p + \mathbf v^{(n)} t$ first crosses any zone edge $\mathbf a \to \mathbf b$. With $\mathbf e = \mathbf b - \mathbf a$ and $\times$ the 2-D cross product $(p \times q = p_x q_y - p_y q_x)$, solving $\mathbf p + \mathbf v t = \mathbf a + s\mathbf e$ for $t$ and $s$ gives

$$t = \frac{(\mathbf a - \mathbf p)\times\mathbf e}{\mathbf v\times\mathbf e},\qquad s = \frac{(\mathbf a - \mathbf p)\times\mathbf v}{\mathbf v\times\mathbf e}$$

The path hits that edge if $t > 0$ (in the future) and $0 \le s \le 1$ (inside the segment). The entry time of sample $n$ is the smallest such $t$ over all edges, $t^{(n)}_{\min}$. The estimated probability is the fraction of samples that arrive in time:

$$\hat P(\text{entry} \le \tau) = \frac1N\sum_{n=1}^{N}\mathbb 1\!\left[\,t^{(n)}_{\min} \le \tau\,\right],\qquad \tau = 3\ \text{s}$$

A person already inside has $\hat P = 1$ and entry time 0. The displayed "Restricted area in ~N s" is the **median** $t^{(n)}_{\min}$ over the hits.

**Warning logic (hysteresis).** On: $\hat P > 0.5$ on 2 consecutive frames, for a person tracked at least 0.5 s who is not inside. Off: $\hat P < 0.3$, entry, or track loss. The gap between 0.5 and 0.3 stops the warning flickering when the probability hovers near the threshold.

Why Monte Carlo and not a closed form: the zone is an arbitrary polygon, the velocity uncertainty is an ellipse (not isotropic), and 200 vectorized samples against a handful of edges cost well under a millisecond in NumPy.

**Measured, live app:** with a calibrated floor, a person walking toward the zone showed $\hat P$ rising smoothly $0.01 \to 0.47 \to 0.77 \to 0.97$ without flicker, and the warning fired **2.76 s before entry**. Synthetic acceptance tests (3 cm noise, 5 seeds): walking straight at the zone from 4 m always warns at least 2 s early; walking parallel 0.5 m from the edge, or standing 1 m away with 5 cm jitter, never warns.

### 4.1 Many zones, scheduled

Landmarks drawn by the operator become extra zones when a confirmed rule's schedule applies. Each (person, zone) pair gets its own entry state (3-frame hysteresis) and its own predictive monitor, and the overlay reports the highest-probability zone. A schedule is `always`, `nap` (while nap mode is on), or a window $[a, b)$ in minutes since midnight that may wrap past midnight:

$$\text{active}(m) = \begin{cases} a \le m < b & a < b\\ m \ge a \ \lor\ m < b & a \ge b\ \ (\text{wraps})\end{cases}$$

---

## 5. Not alerting on one noisy frame (time-weighted CUSUM)

Pose estimation sometimes glitches for a frame or two. An alert should require *sustained* evidence. A **CUSUM** (cumulative sum) accumulates how much evidence exceeds an allowance $k$, and fires when the total crosses a threshold $h$. Our version is weighted by elapsed time so it behaves the same at any frame rate:

$$S_t = \max\!\Big(0,\ S_{t-1} + (x_t - k)\,\Delta t\Big),\qquad \Delta t = \min(t - t_{\text{prev}},\ 1\ \text{s}),\qquad \text{alert when } S_t > h$$

- $x_t \in [0,1]$ is the per-frame evidence score of a rule.
- $k$ is the allowance for normal noise: scores at or below $k$ never accumulate.
- $h$ is in **evidence-seconds**.
- The cap $\Delta t \le 1$ s means a gap in video (a dropped second, a paused tab) is never counted as evidence.
- After firing, a refractory period suppresses repeats.

For a steady score $x > k$, the time to alert is

$$T = \frac{h}{x - k}$$

A false-alarm / delay trade-off falls out directly: raising $h$ delays alerts but makes them rarer; raising $k$ makes the rule ignore weaker evidence. We use CUSUM only for rules that need sustained evidence; the zone-entry warning uses its own 2-frame hysteresis (§4) because adding CUSUM delay would eat into the 3 s of warning.

---

## 6. Rules on body points

All distances below are divided by $L$, the person's **upright height** in the image, so thresholds do not depend on how far from the camera they stand. $L$ is the median box height over frames where the torso is upright ($<30^\circ$ from vertical) *and* the height is at least 85 % of the previous median; that second condition stops a crouch facing the camera (which still looks upright) from shrinking $L$ and making everything look normal.

Coordinates are first aspect-corrected: $x \mapsto x \cdot W/H$ so that a unit step is the same length horizontally and vertically.

### 6.1 Possible choking: hands at the throat (DET-5)

Throat point, between the shoulder midpoint $\mathbf m_{\text{sh}}$ and the nose:

$$\mathbf n = \mathbf m_{\text{sh}} + 0.35\,(\mathbf q_{\text{nose}} - \mathbf m_{\text{sh}})$$

Per-frame score from how many wrists are within $0.25\,\ell_{\text{torso}}$ of $\mathbf n$ (torso length $\ell_{\text{torso}} = \lVert \mathbf m_{\text{sh}} - \mathbf m_{\text{hip}}\rVert$, used instead of shoulder width because shoulders foreshorten when a child turns sideways):

$$x_t = \begin{cases}1 & \text{both wrists near}\\ 0.4 & \text{one wrist near}\\ 0 & \text{neither}\end{cases}\qquad k = 0.45,\ \ h = 0.8\ \Rightarrow\ T = \frac{0.8}{1 - 0.45} \approx 1.45\ \text{s}$$

The design choice is in the numbers: a single hand scores $0.4 < k$, so eating, scratching or touching the face **never accumulates**, no matter how long it lasts. Both hands must hold for about 1.5 s. **Measured:** alert at 1.5 s.

### 6.2 Possible fall (DET-6): two paths, each "fast drop, then stays down"

A fall is a fast drop followed by *not getting back up*. The first version had only the hip-based path and missed a real fall in a stock-footage clip.

**Path A (falls sideways, seen from the side):**

$$\Delta y_{\text{hip}} > 0.3\,L\ \text{within 1 s}\ \ \longrightarrow\ \ \text{lying}\ \big(\theta > 55^\circ\ \text{or box wider than } 1.2\,h\big)\ \text{for 1 s}$$

where $\theta = \operatorname{atan2}(|\Delta x|, -\Delta y)$ is the torso's angle from vertical (shoulder-midpoint minus hip-midpoint). Waiting for 1 s of lying distinguishes a fall from a deliberate quick lie-down only in combination with the speed of the drop; a slow lie-down (over about 5 s) has no fast drop and never fires.

**Path B (falls toward the camera):** a runner fell forward onto her hands facing the camera. Her hips barely moved *in the image* (the fall is along the line of sight) and she never looked horizontal. What did happen was a collapse in total height. With $h_t$ the box height:

$$\max_{1.5\,\text{s}} h \ge 0.85\,L\ \ \wedge\ \ h_t \le 0.7\,L\ \ \longrightarrow\ \ \text{collapse}$$

then: stays low ($h \le 0.75\,L$, box not lying-wide) for 1.5 s, **having started with a hand within $0.15\,L$ of the floor**.

The hand condition is only required at the *start* of the low posture. A first version required it on every frame; on the real clip the runner briefly lifted her hands while staying down, which reset the timer, and the alert was missed again. Gaps up to 0.5 s are tolerated, but the person must still be low at the moment the alert would fire.

Look-alikes that must not alert (each is a unit test): a quick drop to sit with hands on the lap (no hand at the floor), a crouch to pick something up that stands back up within 1.5 s (low posture never holds), and a slow lie-down.

**Measured:** on the real 76-second stock clip, the fall is detected **2.7 s after the runner goes down**, with zero other alerts in the remaining crowded-race footage; the earlier test clips are unchanged.

### 6.3 Unusual rhythmic movement, seizure-like (DET-7)

The signal is that two or more limbs move back and forth at a steady rate of about 1–5 times per second. Per limb (both wrists and both ankles), take the last 6 s of its image position, resample to a uniform time grid, remove the linear trend, apply a Hann window $w$ (to avoid spectral leakage), and take the power spectrum summed over both axes:

$$P(f) = \Big|\mathcal F\{w\cdot \tilde x\}(f)\Big|^2 + \Big|\mathcal F\{w\cdot \tilde y\}(f)\Big|^2$$

Let $f_0 = \arg\max_{f > 0.2\,\text{Hz}} P(f)$ be the strongest frequency. A limb is "rhythmic" if all three hold:

$$\underbrace{1 \le f_0 \le 5\ \text{Hz}}_{\text{the strongest movement is in the band}}\qquad \underbrace{\sqrt{\operatorname{Var}\tilde x + \operatorname{Var}\tilde y} > 0.02\,L}_{\text{big enough to matter}}\qquad C = \frac{\displaystyle\sum_{|f-f_0|\le 0.5\ \cup\ |f-2f_0|\le 0.5} P(f)}{\displaystyle\sum_{f > 0.2\,\text{Hz}} P(f)} > 0.6$$

$C$ is the **concentration**: how much of all the power sits at the main frequency or its first harmonic (jerky movements are not pure sine waves, so they leak into $2f_0$). Two or more rhythmic limbs give $x_t = 1$, fed into CUSUM with $k = 0.3,\ h = 3$:

$$T = \frac{3}{1 - 0.3} \approx 4.3\ \text{s of sustained evidence, after a 4 s minimum analysis window} \ \Rightarrow\ \approx 8.3\ \text{s total}$$

**Sampling limit (Nyquist).** To see 4–5 Hz movement you need at least twice that many samples per second, so the rule reports `needs ≥8 fps` and stays silent below 8 analyzed frames per second. This is why raising the analysis rate (§7) mattered: at the original 2 fps this rule could never have run.

#### The mistake worth knowing about

The first version used the **band share** (the fraction of power anywhere in 1–5 Hz) $>0.6$ as the test. Pose jitter on a perfectly still person is random, broadband noise; measured over 6 s at 15 fps it puts **57 %** of its power in 1–5 Hz, so with a small boost from the pose model's own error it crossed 0.6 and the rule fired on a person standing still. The fix is the concentration $C$: genuine shaking concentrates power at one frequency, noise spreads it.

| Signal (6 s window, 15 fps, 400 trials) | Band share (old test) | Concentration $C$ (current) | Passes $C > 0.6$ |
|---|---|---|---|
| White noise (pose jitter) | **0.57** | **0.18** | 0 % |
| 3 Hz shaking with small noise | 0.97 | 0.95 | 100 % |

A frequency sweep then caught a regression from that fix: slow 0.6–0.8 Hz waving fired, because a peak just below 1 Hz leaked power into the band. The extra requirement that $f_0$ itself lie in 1–5 Hz closed it. In synthetic tests the rule alerts at about 8.3 s for 1.5, 3 and 4.5 Hz shaking at 8, 10, 15 and 30 fps, never alerts for movement at 0.4–1.0 Hz or 5.5–6 Hz, at 2 % amplitude, or on pose jitter up to 5 % of body height.

### 6.4 Prolonged stillness (DET-8)

Mean keypoint displacement over a 2 s lookback, over the $K \ge 4$ confident keypoints:

$$M_t = \frac1K\sum_{k}\Big\lVert \mathbf q_k(t) - \mathbf q_k(t - 2\,\text{s})\Big\rVert < 0.04\,L\quad\text{for}\ \ T_{\text{still}}\ \text{seconds (default 30; disabled in nap mode)}$$

---

## 7. Optimizing: where the time and CPU went

Optimization here means measuring first. Each change below started from a measurement in the live app.

### 7.1 Detector choice

Same 640 px images, one CPU:

| Image | OpenCV HOG | YOLO26n-pose |
|---|---|---|
| street scene, 4 people + 1 partial | 2 found, 105 ms | 5 found with keypoints, 39 ms |
| two people close up | 0 found, 35 ms | 2 found, 19 ms |

The detector is both more accurate *and* faster, because HOG's multi-scale sliding window does far more work than one forward pass of a 7.5 MB network. Result: 26–38 ms per frame end to end including tracking and all rules.

### 7.2 Analysis rate: 2 → 12 frames per second

Measured in the real browser with a real upload: exactly **2.00 frames per second**. The Nyquist limit of §6.3 and the 2.76 s warning budget both needed more. The sampling loop now runs at 12 fps and skips a tick while an upload is still in flight, so a slow server sheds frames instead of building a queue of stale ones:

$$\text{tick}_n \text{ sent} \iff \text{upload}_{n-1}\ \text{finished}$$

Each upload response now also carries the latest tracking boxes, so overlays refresh at the frame rate instead of every 1.5 s. Result: **11.98 fps measured**, boxes visible in 100 % of 50 samples taken 100 ms apart.

### 7.3 CPU: fewer threads, same latency class

Faster sampling roughly tripled the work, so CPU became the constraint. PyTorch by default used 8 threads per frame. Measured per-frame latency and total CPU work at 12 fps (one 16-core laptop):

| Threads | Latency per frame | CPU cores at 12 fps |
|---|---|---|
| 8 (library default) | 30 ms | 2.67 |
| 4 | 33 ms | 1.48 |
| **3 (chosen)** | **35 ms** | **1.22** |
| 2 | 45 ms | 1.04 |
| 1 | 76 ms | 0.91 |

Latency barely changes between 8 and 3 threads, but CPU time drops by more than half, because extra threads mostly spin waiting for each other (parallel efficiency falls with thread count on a small network). The frame budget is $1/12 = 83$ ms, so 35 ms leaves comfortable headroom: **end-to-end p50 38 ms, p95 43 ms** with all detectors on.

A subtle point: the library resets the thread count to 8 when it first sets up its predictor, so a limit set before the first inference had **no effect** and the first benchmark wrongly suggested threads didn't matter. The limit is applied *after* setup, and re-applied after each inference.

### 7.4 Vectorizing the Monte Carlo

The 200 samples × (number of zone edges) intersections of §4 are one NumPy broadcast over arrays of shape $(N, \text{edges})$, not a Python loop, so they cost a fraction of a millisecond per person per zone. Each Kalman update is a few $4 \times 4$ matrix products. These never show up in profiles; the neural network dominates.

### 7.4b Skipping what cannot matter

- The pose model is warmed once at startup so the first live frame is not slow.
- Rules skip people with no keypoints (the HOG fallback has none).
- The Claude review (next section) does not run when nothing happened.

---

## 8. Optimizing cost: Claude only after an alert

The most expensive component was the cloud call, and it was also the one growing with camera time. This is a **cost model**, with the same formula for every model:

$$\text{cost per request} = \frac{n_{\text{in}}\,p_{\text{in}} + n_{\text{out}}\,p_{\text{out}}}{10^6},\qquad n_{\text{image}} \approx \frac{w \cdot h}{750}$$

with $p$ in dollars per million tokens (Haiku 5.5: 0.10 / 0.50; Opus 5.5: 4 / 20).

**Original design.** While enabled, every 3 s: 6 full frames of $640\times360$ ($\approx 307$ image tokens each) plus a prompt, about 2,250 input and 300 output tokens, up to 1,200 requests per camera-hour:

$$\underbrace{1200}_{\text{requests/hr}} \times \Big(\underbrace{2250 \cdot 4}_{\text{in}} + \underbrace{300\cdot 20}_{\text{out}}\Big)/10^6 \approx \$18\ \text{per camera-hour on Opus 5.5}$$

and it would have failed anyway: it forced a specific tool call, which the newer models reject.

**New design.** Only **after a local rule has already alerted**, only up to **4 crops of the flagged person**, faces blurred. Measured crop sizes ($\approx 140$–$220 \times 475$–$512$ px) are about 90–150 image tokens each; with the prompt, about 1,000 input and 300 output tokens:

$$\text{Opus 5.5: } \frac{1000\cdot 4 + 300\cdot 20}{10^6} = \$0.010,\qquad \text{Haiku 5.5: } \frac{1000\cdot 0.10 + 300\cdot 0.50}{10^6} \approx \$0.0003$$

$$\text{cost per camera-hour} = \$0.010\times(\text{alerts per hour}),\qquad \text{and exactly } \$0 \text{ when nothing happens}$$

At 5 alerts per hour that is about **$0.05** on Opus 5.5 instead of **$18**, a reduction of roughly 360×; on Haiku about $0.0015. The cost scales with *events*, not with time, which is the right shape for a safety product that is quiet most of the day.

Other cost decisions: detection is local (zero marginal cost); the review runs one at a time with the latest alert winning; a per-session request cap bounds the worst case; and the session meter shows tokens and dollars live. Plain-language rule drafting and incident reports are on demand and cost cents.

---

## 9. Why Claude is never on the alert path

If an alert needed a cloud answer, its worst-case delay would be the network's worst case. So the design splits the system by latency tolerance:

| Needs to be fast and reliable | Local code | Typical delay |
|---|---|---|
| Alert, escalation timers, acknowledgment | FastAPI + SQLite | milliseconds |
| Detection and rules | YOLO + the math above | ~40 ms per frame, ≤ 8 s per rule |

| Helps a human decide or document | Claude | Failure effect |
|---|---|---|
| Second opinion (context card) | after alert | none; the alert already went out |
| Rule drafts | on demand | nothing is created, a question is asked |
| Incident report | on demand | falls back to a plain timeline |

Claude's output is also *checked by arithmetic, not trusted*: a drafted rule is accepted only if its landmark ID exists and its times parse (`00:00 ≤ time ≤ 23:59`, start ≠ end); a report line is kept only if it cites at least one real fact ID and contains no diagnosis language. Anything else is dropped and counted.

---

## 10. Measuring honestly

With only a handful of staged clips, a point estimate such as "100 % recall" is misleading. We report **Wilson score intervals**. For $k$ successes in $n$ trials, $\hat p = k/n$, $z = 1.96$:

$$\text{CI}_{95\%} = \frac{\hat p + \frac{z^2}{2n} \ \pm\ z\sqrt{\dfrac{\hat p(1-\hat p)}{n} + \dfrac{z^2}{4n^2}}}{1 + \dfrac{z^2}{n}}$$

Unlike the naive interval $\hat p \pm z\sqrt{\hat p(1-\hat p)/n}$, this never collapses to zero width at $\hat p = 0$ or 1 and stays inside $[0,1]$. Concretely, 1 hit out of 1 gives **21 %–100 %**, and 8 of 10 gives 49 %–94 %: the first is correct but says little, which is the point.

Matching rule: a hit is an alert of the right kind from $0$ to $5$ s after the labeled onset; each alert and each event match at most once (one-to-one). Precision $= TP/(TP+FP)$, recall $= TP/(TP+FN)$, mean delay over hits, and false alarms per hour $= FP_{\text{negative clips}} / \text{hours of negative footage}$.

### What the first real run found

Running the harness on real YOLO output (not synthetic skeletons) caught the §1 ground-point bias, then, on a stock-footage clip, the missing fall path of §6.2. Both were invisible to the synthetic unit tests, because those tests encoded the same assumptions as the code. This is the main reason the evaluation harness exists and why its numbers are reported separately from unit-test results.

**Limits.** The test clips so far are composites and one stock clip of adult athletes. These numbers show the machinery works and has already caught real mistakes; they are not accuracy on children. Staged clips with consenting teammates, and tuning on a `tune` split with reporting on a held-out `test` split, are the next step.

---

## 11. Summary of changes caused by measurement

| What was believed | What measuring showed | What changed |
|---|---|---|
| Ankle joint = floor contact | 4–5 % of body height above the floor; false alarms beside zones | Use the bottom of the box (§1) |
| Mean calibration error is a good check | A 0.6 m typo averaged to 0.14 m and was accepted | Reject on the worst point (§2.1) |
| Rhythm = power in 1–5 Hz | White noise puts 57 % there; fired on a still person | Require concentration at one peak, $C>0.6$ (§6.3) |
| One concentration test is enough | 0.6–0.8 Hz waving leaked into the band | Peak itself must be in 1–5 Hz (§6.3) |
| Falls move the hips | Falling toward the camera barely moves them | Add the height-collapse path (§6.2) |
| Hands at the floor on every frame | Real runner lifted her hands while down | Only required at the start (§6.2) |
| 2 fps is enough | Rhythm rule needs ≥ 8 fps; warning needs responsiveness | 12 fps with in-flight skipping (§7.2) |
| More threads = faster | 8 threads cost 2.2× the CPU of 3 for ~15 % less latency | 3 threads, applied after predictor setup (§7.3) |
| Periodic cloud review is affordable | ≈ $18 per camera-hour, and rejected by newer models | Event-triggered, cropped, blurred (§8) |
