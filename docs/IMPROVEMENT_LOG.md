# Improvement log

Each iteration finds the current biggest bottleneck, makes one focused change, verifies it with `npm run build` and `pytest`, and records measured results here. Nothing is committed automatically.

## Backlog (ranked by impact on the demo and cost)

1. ~~Detector cannot see body points or more than one person~~ (iteration 1)
2. ~~Event detectors on keypoints~~ (iteration 2)
3. ~~Frame rate~~ (iteration 3). ~~Browsers throttle timers in hidden tabs, so analysis depends on the dashboard tab staying visible~~ (SRC-4: the server reads the camera itself). Optical flow inside the person box as a second rhythm signal, since pose degrades on fast, blurred limbs.
4. Floor-plan homography, Kalman velocity, and probability of entry within 3 s (predictive warning).
5. ~~Cost of cloud review~~ (iteration 4)
6. Escalation: Cartesia Line outbound voice agent adapter (spoken "I'm on it" acknowledges), with the existing Twilio and Cartesia TTS press-1 path as fallback.
7. Dashboard: skeleton overlay, per-person zone state, who owns each alert, floor-plan view.
8. Evaluation harness: label staged clips and report precision, recall, alert delay, and false alarms per hour per event type.

## Iteration 1: local YOLO pose and multi-person tracking (2026-10-24)

**Bottleneck.** The only detector was OpenCV HOG: one upright adult-sized person at a time, boxes only, no keypoints. Every NestWatch event (falls, seizure-like movement, hands at throat, prediction) needs body keypoints and stable per-person IDs, so nothing else on the roadmap could be built on it.

**Change.**
- `server/vision.py`: YOLO26n-pose (Ultralytics, CPU PyTorch) with ByteTrack IDs. Each tracked person gets their own zone hysteresis. A person missing from a frame is treated as missing data, never as outside, and is forgotten after 1.5 s. The ByteTrack state restarts on session reset.
- Ground point uses confident ankles, else the box's bottom center.
- HOG remains the fallback when the model or Ultralytics is missing, or when `LOOKOUT_DETECTOR=hog`. Existing single-subject behavior is unchanged in that mode.
- Weights load once at API startup (`warm()`), from `models/` only. `npm run models` fetches them. The API never downloads at runtime.
- Camera state now reports which detector is active.
- `server/requirements-pose.txt` pins OpenCV 4.x, because Ultralytics would otherwise install OpenCV 5, which removes the HOG fallback.

**Measured** (CPU, 640 px wide frames, 16-core laptop):

| Image | HOG | YOLO26n pose |
|---|---|---|
| bus.jpg (4 full people + 1 partial) | 2 people, 105 ms | 5 people with 17 keypoints each, 39 ms |
| zidane.jpg (2 people) | 0 people, 35 ms | 2 people, 19 ms |

Through the full engine on a 40-frame simulated camera pan: 4 distinct track IDs (no ID switches), 3–4 people per frame, latency p50 29 ms and p95 36 ms.

**Cost.** $0 per camera-hour for detection: local CPU inference, no frames leave the machine.

**Verification.** `npm run build` passes. `pytest`: 21 passed; with `LOOKOUT_DETECTOR=hog`, 20 passed and the real-model test skipped. New tests cover the ankle and fallback ground point, independent zone state for two tracked people, and missing-then-forgotten tracks.

**Limitations.** These are adult photos, not daycare footage. Child and crawling-pose accuracy is unmeasured. The browser still sends 2 fps (backlog item 3).

## Iteration 2: keypoint event rules (2026-10-24)

**Bottleneck.** The only event was restricted-zone entry. The pose keypoints from iteration 1 went unused, so four of NestWatch's core events (possible choking, falls, seizure-like movement, prolonged stillness) did not exist.

**Change.**
- New `server/events.py`, with pure-math rules per tracked person. Distances are aspect-corrected and normalized by the person's median upright height, so thresholds hold at any distance from the camera and do not shrink during a fall.
  - Hands at throat: throat point = shoulder midpoint + 0.35·(nose − shoulder midpoint). Score 1 for both wrists within 0.25 torso lengths, 0.4 for one, 0 otherwise. Time-weighted CUSUM with k = 0.45 and h = 0.8 evidence-seconds, so one hand never accumulates.
  - Fall: hips drop more than 0.3 body lengths within 1 s, then lying (torso more than 55° from vertical, or a wide box) for 1 s, within 3 s of the drop.
  - Rhythmic movement: per limb (wrists, ankles), resample the last 6 s to a uniform grid, detrend, and apply a Hann-windowed FFT. A limb counts when its amplitude exceeds 2% of body length and more than 60% of its power sits within ±0.5 Hz of a 1–5 Hz peak or its first harmonic. Two or more limbs give score 1. CUSUM k = 0.3, h = 3. Inactive below 8 frames per second, and the reason is reported in `detectors` status.
  - Stillness: mean keypoint displacement over 2 s below 4% of body length, for `stillness_seconds` (default 30). Disabled by `nap_mode`.
- `Cusum` caps Δt at 1 s, so a frame gap is never treated as evidence, and has a refractory period per event.
- Incident kinds, titles, spoken call phrases and limitations now come from one table (`KINDS` in `server/store.py`). The new kinds flow through the existing incident, escalation and timeline path unchanged.
- `PUT /api/settings` accepts and validates `stillness_seconds` (10–600) and `nap_mode`.

**First approach failed a robustness check.** The initial rhythm test (more than 60% of power anywhere in 1–5 Hz) fired on a still person with 2% pose jitter. Broadband noise puts about 55% of its power in that band at 15 fps, which is too close to the threshold. Requiring concentration around one peak and its harmonic fixed it. A full frequency sweep then caught a regression: slow 0.6–0.8 Hz waving fired, because a peak at the 1 Hz band edge captured power from below the band. The strongest frequency overall must now itself lie in 1–5 Hz.

**Measured** (synthetic skeletons):

| Case | Result |
|---|---|
| Both hands at throat | Alert at 1.5 s |
| One hand at throat for 10 s; both hands for 0.75 s | No alert |
| Fast fall to lying | Alert 1.0 s after the drop |
| Lying down slowly over 5 s; dropping quickly to sitting upright | No alert |
| Limb shaking at 1.5, 3 or 4.5 Hz (amplitude ≥ 3% of height); 2 Hz non-sinusoidal jerks | Alert about 8.3 s after onset, at 8, 10, 15 or 30 fps |
| Waving at 0.4–1.0 Hz; movement at 5.5–6 Hz; 3 Hz at amplitude 2% of height | No alert |
| Pose jitter of 2%, 3% and 5% of body height for 60 s, still person | No rhythm alert (failed at 2% before the fix) |
| Still for 10 s with jitter, setting 10 s | Alert at 10–12.5 s; none while walking or in nap mode |

Full engine latency on the 40-frame pan: p50 26 ms, p95 34 ms. The rules add no measurable time.

**Cost.** $0: all local arithmetic on keypoints.

**Verification.** `npm run build` passes. `pytest`: 27 passed; with HOG forced, 26 passed and 1 skipped. New tests in `server/tests/test_events.py` cover the CUSUM timing, each positive case, its look-alikes, and the engine producing a `local_rule` observation.

**Limitations.** Thresholds are tuned on synthetic skeletons, so they need staged clips to calibrate. At the current 2 fps the rhythm rule is inactive, falls and the throat rule have coarse timing, and lying along the camera's line of sight looks upright in the image.

## Iteration 3: analysis frame rate and CPU cost (2026-10-24)

**Bottleneck.** Measured in the real app (built-in browser, 20 s test clip uploaded through the UI): exactly **2.00 frames analyzed per second**. At that rate the rhythm rule from iteration 2 could never run (it reported "needs ≥8 fps"), and fall and throat timing were coarse. A second problem showed up in the same pipeline. The dashboard refreshes state every 1.5 s but hides any tracking box more than 0.5 s from the video's current time, so boxes were stale or missing.

**Change.**
- `src/App.tsx`: sample at 12 fps (`ANALYSIS_FPS`) with one reused canvas. A tick is skipped while the previous upload is in flight, so slow analysis sheds frames instead of queueing stale ones.
- `POST /api/frames` returns the latest overlays, and the UI applies them immediately, so boxes refresh at the frame rate at no extra cost.
- The server measures frames actually analyzed per second (`camera.analysis_fps`). The video footer shows it (for example "Pose · 11.7 fps") and turns amber below 8 fps, with a hint to keep the tab visible.
- **CPU cost.** Ultralytics resets PyTorch to 8 threads during predictor setup, so a thread cap set before the first inference had no effect. That benchmark first looked like threads didn't matter. Applying the cap after setup works. Measured per frame on this laptop:

| Threads | Latency | CPU cores at 12 fps |
|---|---|---|
| 8 (Ultralytics default) | 30 ms | 2.67 |
| 3 (new default, `POSE_THREADS`) | 35 ms | 1.22 |
| 2 | 45 ms | 1.04 |
| 1 | 76 ms | 0.91 |

- **Bug found while verifying.** When a person's feet are cut off by the frame's bottom edge, the ground point fell back to the frame edge and the person counted as outside the zone. `foot_point` now returns `None` (unknown) in that case, so the zone state treats it as missing data, consistent with the existing rule that missing data never counts as outside.

**Measured** (live app, same clip):

| | Before | After |
|---|---|---|
| Frames analyzed per second | 2.00 | 11.98 (server reports 11.4–12.0) |
| Rhythm rule | inactive ("needs ≥8 fps") | active |
| Tracking boxes visible during playback (50 samples, 100 ms apart) | stale, 1.5 s refresh | visible in 100% of samples, 3–4 people |
| API CPU while analyzing at 12 fps | 2.5 cores (before the thread cap) | 1.3 cores |
| API memory | 500 MB | 516 MB |
| Engine latency, 40-frame pan | p50 26 ms | p50 38 ms, p95 43 ms (inside the 83 ms budget) |

**Cost.** Still $0 in cloud spend. Local compute roughly halved per analyzed second while analyzing 6× more frames.

**Verification.** `npm run build` passes. `pytest`: 27 passed; with HOG forced, 26 passed and 1 skipped. Includes a new assertion that a cut-off box gives an unknown ground point. Live check in the built-in browser covered upload → playback → 12 fps analysis → overlays → rhythm rule active.

**Limitations.** A hidden or minimized dashboard tab is throttled by the browser, so analysis then slows to about 1 fps. The footer now makes that visible but does not prevent it. Measured on one 16-core laptop; slower machines may need `POSE_THREADS=2` or a lower `ANALYSIS_FPS`.

## Iteration 4: Claude as an event-triggered second opinion (2026-10-24)

**Bottleneck.** Cloud review was the only cost that grew with camera time, and it was broken on current models.
- While enabled, it sent 6 full frames every 3 s (up to 1,200 requests per hour, capped at 200 per session) whether or not anything was happening.
- It used forced `tool_choice`, which Claude Opus 5.5, Sonnet 5.5 and Fable 5.1 reject with a 400. Only Haiku 5.5 or older models could run it.
- It was the detector for distress, which put a cloud call on the alert path. It also sent whole frames, including every other person in the room.

**Change (approach replaced).**
- `server/review.py`, using the official `anthropic` SDK. Review now runs only after a local rule (distress, fall, rhythmic, stillness) has already raised an incident, so it cannot delay, cancel or downgrade an alert. One review runs at a time and the latest pending trigger wins. The session request cap still applies.
- **Privacy.** It sends up to 4 frames cropped to the flagged person's padded box. Every visible head (nose, eye and ear keypoints) is blurred before cropping, so other people are excluded or blurred.
- **Output.** JSON-schema structured output (`output_config.format`) replaces forced tool use, and the result is validated with Pydantic. The assessment is `concern_visible`, `benign_explanation_likely` or `insufficient_view`, plus visible observations, alternatives and limitations.
- **Request settings.** `effort: low`. Opus 5.5, Sonnet 5.5 and Fable 5.1 get server-side `fallbacks: "default"`. A safety decline, `max_tokens` stop or invalid output marks the review unavailable and leaves the alert untouched.
- **Delivery.** The result attaches to the newest incident of that kind (`Store.annotate`) through a callback, so it arrives even if playback stops. It also logs a `second_opinion` event.
- **Cost meter.** Requests, tokens and USD per session, from list prices: Haiku 5.5 $0.10/$0.50, Sonnet 5.5 $2/$10, Opus 5.5 $4/$20, Fable 5.1 $10/$50 per million tokens. Shown in settings and on each opinion.
- **UI.** The incident card shows the second opinion as context, and each incident's own limitations now come from `KINDS` instead of a hard-coded choking line.

**Measured.** Real YOLO detections on bus.jpg: crops are 139–218 × 475–512 px, about 90–150 image tokens each (w·h/750 estimate), versus about 307 per full 640×360 frame. No API key was used, so per-review cost is estimated: about 1,000 input and 300 output tokens.

| Model | Old: periodic, per camera-hour while enabled | New: per review | New: idle hour |
|---|---|---|---|
| claude-haiku-5-5 | ≈ $0.47 | ≈ $0.0003 | $0 |
| claude-opus-5-5 | ≈ $19 (and it failed with a 400) | ≈ $0.01 | $0 |

At 5 alerts per camera-hour, Opus 5.5 costs about $0.05 per hour instead of about $19.

**Verification.** `pytest`: 29 passed, 5 consecutive runs; with HOG forced, 28 passed and 1 skipped. `npm run build` passes. New `server/tests/test_review.py` uses a fake SDK client and covers:
- zero requests over 40 calm frames
- one request after a throat alert, with JSON-schema output and no `tool_choice`
- at most 4 images per review
- fallbacks only for models that need them
- the crop excludes the other person and blurs the head (detail at least 5× lower)
- a decline or a reset mid-request never touches the alert
- the callback attaches the opinion without changing incident status
- the cost table

A first version of these tests was timing-dependent and flaky; it now waits for the review task. Live UI check: the opinion card renders in the event trace. That check exposed a stale Vite watcher, which a dev-server restart fixed.

**Limitations.** No real API call was made, so per-review tokens are estimates until the first real review reports its usage. Blurring the face hides the mouth, so the opinion relies on hands, posture and neck.

## M1: predictive zone warning, DET-9 (2026-10-24)

Built spec-first: the DET-9 acceptance criteria and 8 named tests came before the code. `test_spec.py` caught one test I wrote but hadn't listed.

**What it does.**
- **Calibration.** The operator clicks 4–20 floor points on the video and types each one's position in meters. The server fits a homography (RANSAC from 6 points) and rejects bad input with a message that names the problem point.
- **Tracking.** Each tracked person's ground point drives a constant-velocity Kalman filter on the floor. Its measurement noise is the image noise pushed through the homography's Jacobian.
- **Warning.** When more than half of 200 sampled future paths cross into the zone within 3 s, on 2 consecutive frames, the person's box turns amber and reads "Restricted area in ~N s", with a dashed predicted path. One `approach_warning` history event is logged per episode.
- It never creates an incident or a call; actual entry still does (DET-3).

**Spec change found by testing.** The first rejection rule (mean reprojection error above 0.15 m) accepted a 0.6 m measurement typo. Least squares spread that error to a 0.14 m mean. The rule is now worst-point: a 0.3 m typo is rejected ("Point 5 is 0.20 m from where the other points place it"), while a 0.1 m error is accepted. Four points always fit exactly, so the UI recommends five or more.

**Measured.**

| Case | Result |
|---|---|
| Synthetic: 1 m/s straight at the zone from 4 m, 3 cm noise (5 seeds) | Warns at least 2 s before entry (spec) |
| Synthetic: parallel 0.5 m from the edge; standing 1 m away with 5 cm jitter (5 seeds) | Never warns |
| Live app: real YOLO pose on a person cut-out walking about 0.6 m/s, calibrated through the UI (5 clicked points, 0.01 m error) | Warned at 5.88 s, entered at 8.64 s: **2.76 s lead**. P rose 0.01 → 0.47 → 0.77 → 0.97 without flicker. |
| Live app: the same walk, but passing about 0.3 m outside the zone (first clip, by mistake) | Late warning at P 0.58, about 1 s before passing the edge. Reasonable for a child that close to a gate, and documented as the sensitivity at about 0.3 m. |

Only the entry created an incident; the pre-warnings appear in history only. CPU and latency are unchanged: 200 samples × 4 edges per tracked person is vectorized NumPy.

**Verification.** `pytest`: 43 passed; with HOG forced, 42 passed and 1 skipped. `npm run build` passes. Live UI checks covered: calibration mode toggle, clicking points, entering meters, saving, the rejection message on a typo, the amber warning, the predicted path, history events, and no incident from the warning.

## M2: spoken acknowledgment and alert ownership, ESC-3 and UI-3 (2026-10-24)

**Open question resolved first (Q-1).** Cartesia's docs confirm that managed voice agents support HTTPS webhook tools with bearer authentication, and that outbound calls (`POST /agents/calls`) accept per-call `dynamic_variables`, which can fill tool body fields. The spec was updated with the concrete contract before any code.

**What it does.**
- `CALL_PROVIDER=cartesia_agent` places the escalation call with a Cartesia voice agent. Each call carries `room`, `alert`, `caregiver` and a fresh single-use `ack_token`; only its SHA-256 hash is stored.
- When the caregiver says "I'm on it", the agent's `acknowledge_alert` tool posts `{token, decision}` to `/webhooks/voice/ack` with the shared bearer secret.
- The server acknowledges through the existing first-wins path as that step's named caregiver, via `voice`. A decline expedites the backup, like keypad 2.
- The reply is a sentence for the agent to say, including "already handled by ⟨name⟩" when someone else got there first. Cartesia documents no hang-up endpoint, so that reply lets the agent end the call.
- A failed agent call (HTTP error, or a per-destination `error`) falls back to the Twilio keypad call for the same step.
- Keypad acknowledgments now record the configured caregiver's name instead of "Primary caregiver".
- Every acknowledgment records its channel. The event trace shows "Handled by ⟨name⟩ via ⟨dashboard | keypad | voice⟩".
- Setup for the agent and tool: [CARTESIA_AGENT.md](CARTESIA_AGENT.md).

**Verification.** `pytest`: 48 passed; with HOG forced, 47 passed and 1 skipped. `npm run build` passes. New `server/tests/test_voice.py` uses mocked HTTP and covers:
- the exact request to Cartesia, with only the hash stored
- 403 for a missing or wrong secret, 409 for an unknown token, single use, acknowledgment as the named caregiver via voice
- decline expediting the backup, and "already handled by Dana" when the dashboard won first
- fallback to keypad on a per-destination error

Live check in the browser: after a dashboard acknowledgment, "Handled by Maya Chen via dashboard" appeared within 120 ms.

**Not verified.** A real Cartesia agent call. Agent creation in the Cartesia console is documented but untested, and needs an account, a Cartesia number and an HTTPS tunnel.

## M3: rules in plain words, AI-6 (2026-10-24)

**Spec gap found while designing.** A rule like "keep kids away from the kitchen gate during nap time" needs named places and several scheduled zones, but the engine had exactly one zone. The spec now includes landmarks and multi-zone enforcement, and M3 built both.

**What it does.**
- **Landmarks.** In the rules panel (shield button), click 3–12 points around a place on the video and name it. Names are unique, outlines must enclose an area, and deleting a landmark deletes its rules.
- **Drafting.** Type a rule. Claude (`CLAUDE_MODEL`, default Opus 5.5, effort low, `fallbacks: "default"`, JSON-schema output) returns either a proposal (landmark ID, schedule `always` / `window` / `nap`, severity, summary) or one question.
- **Validation.** The server checks the result. An unknown landmark, an invalid or empty time window, a model error, or no API key returns a question or an error, and creates nothing.
- **Confirmation.** A draft is outlined in amber on the video and is never enforced until you press Confirm.
- **Enforcement.** Active rules whose schedule applies (server local time, windows may wrap past midnight, `nap` follows nap mode) become restricted zones. The engine now tracks entry state per (person, zone) and predictive warnings per zone. Incidents name the zone ("entered Kitchen gate (restricted by rule)") and use the rule's severity. The original zone stays as the default zone.

**Verification.** `pytest`: 54 passed. New `server/tests/test_rules.py` uses a fake Claude client and covers:
- landmark validation and cascade delete
- the exact draft request (model, fallbacks, structured output, landmark names in the prompt)
- invalid model output becoming a question with nothing created
- 503 without a key
- schedule windows, including wrapping past midnight and nap mode
- the engine enforcing only confirmed, in-schedule rules

Live check in the browser:
- drew "Kitchen gate" by clicking on the video, then saved it
- drafting without an API key showed "Claude is not configured" and created nothing
- added one sample draft directly in the database in place of Claude; it showed an amber outline with Confirm and Discard
- with the rule still a draft, a walk through the gate (86 frames analyzed) raised no incident
- after Confirm, the same walk raised a critical incident: "Tracked person 1 entered Kitchen gate (restricted by rule)"

My first attempt at the draft-only check reset the session mid-test, so no frames were analyzed and the result was invalid. It was redone through the upload path, which restarts analysis.

**Not verified.** A real Claude draft, because no API key is available here.

## M4: evidence clips and cited reports, PRV-3 and AI-7 (2026-10-24)

**Spec gap found while designing.** The event log did not record which incident an event belonged to, so no report could be assembled. Events now carry `incident_id`, with a schema migration for existing databases. The opening, calls, decline, acknowledgment, resolution, second opinion and evidence clip are all linked.

**Evidence clips (PRV-3).**
- A rolling 5 s buffer of analyzed frames. When an incident opens, the frames from 5 s before to 5 s after are encoded as VP8 WebM (OpenCV's FFmpeg, playable in Chrome) at the analysis rate.
- Every head is blurred using face keypoints, or else the top 22% of the person's box for the HOG fallback. This is now one shared `blur_heads` used by second-opinion crops, clips and evidence stills. Stills were previously saved unblurred.
- A session reset, stop or source change finalizes clips in progress.
- Clips and stills older than `clip_retention_days` (1–90, default 7) are deleted at startup and hourly, and their links are removed from incidents.

**Reports (AI-7).**
- `GET /api/incidents/{id}/report` builds numbered facts only from stored data: the opening, observations, linked events, call records and the second opinion.
- Without Claude, it renders a plain timeline. With Claude, Claude phrases lines that must each cite existing facts. Lines with no citation, an unknown citation, or diagnosis or outcome language ("choked", "was injured", "unconscious"…) are removed and counted. If none survive, the plain timeline is used.
- Limitations are included verbatim, with a fixed footer.
- The Report button opens the Markdown and downloads it as `.md`.

**Found during the live check.** The first plain report listed each call twice: once from its call record and once from its log event. Call log events are now excluded in favor of the records, which carry the caregiver's name and final status, and a test asserts it.

**Measured live** (walking clip through the confirmed Kitchen-gate rule):
- The incident opened at 5.3 s. A 10.1 s VP8 clip at about 12 fps (122 frames) was saved and linked, and its event was logged against the incident.
- A frame grabbed from the clip and the evidence still both show the face blurred and the body visible.
- The report rendered as a plain timeline (no API key here) with 8 facts, the clip link, limitations and the footer. The download button is present.

**Verification.** `pytest`: 61 passed. New `test_clips.py` covers the before/after span, 12 fps VP8 decode, the head being at least 2× flatter than the body, partial finalize, and retention deleting files and links. New `test_report.py` uses a fake Claude client and covers linkage, the plain timeline, cited lines with 3 of 5 removed (uncited, unknown fact, diagnosis), and fallback.

**Not verified.** A real Claude-written report, because no API key is available here.

## M5: design, UI-4 to UI-6 (2026-10-24)

**Verification first.** Playwright was never installed, so the repository's smoke scripts had never run here. I installed it (1.64, headless Chromium). Both existing suites passed against all M1–M4 changes before any UI work. A new `scripts/design-smoke.mjs` (`npm run test:design`) is the acceptance test for M5. It injects a tracked, warned person by intercepting `/api/frames` and echoing the posted epoch and media time, so it checks rendering independently of detection.

**What changed.**
- **UI-6 branding.** NestWatch in the title, the brand, the camera label and downloads; no visible "Lookout" text. Internal type names and the settings storage key are unchanged, so saved settings survive.
- **UI-6 skeletons.** Each tracked person is drawn as a skeleton (16 COCO limb pairs, confident keypoints only) under their labeled box.
- **UI-4 floor plan.** A Map button toggles a top-down inset in meters. It shows zones in force, landmarks, calibration points, each person as a dot with their track ID, a warned person's predicted path in amber, and a 1 m scale bar. The server adds `floor_plan` to the state and `floor` and `approach.floor_path` to overlays. Without calibration, the inset says to calibrate first.
- **UI-5 phone view.** Acknowledging on `/respond/{id}` records the channel `app` (operator endpoints accept only `dashboard` or `app`; keypad and voice still require their verified webhooks). The page shows "Handled by ⟨name⟩ via ⟨channel⟩".

**Found in screenshots.**
- After acknowledging on the phone, "I cannot respond" was still shown, but the server would reject a decline once someone owns the alert. It now shows only while the alert is open, and the spec says so.
- The floor-plan inset overlapped the camera clock; it moved down.

**Verification.**
- `pytest`: 63 passed, including `test_state_exposes_floor_plan` (calibrated `floor_plan`, default zone in meters within 1 cm, `None` after delete, overlay floor position and predicted floor path) and `test_mobile_acknowledgment_records_app_channel` (`voice` rejected from the operator endpoint).
- Browser: `test:design`, `test:ui` and `test:media` all pass with no runtime exceptions.

## M6: evaluation harness, EVAL-1 (2026-10-24)

**What it does.** `npm run eval -- labels.json [--split test]` runs the real engine offline on labeled clips. It samples at 12 fps, encodes like the dashboard, and uses the clip's own timeline. Matching is one-to-one within 0–5 s after onset. The report gives, per kind: hits, misses, false alarms, precision and recall with Wilson 95% intervals, mean delay, and false alarms per hour of negative footage. Output is JSON plus Markdown that states staged clips are not deployment accuracy.

**First real run found a systematic bias.** I used three scratch clips with real YOLO pose: a walk into the zone, a walk just past it, and a pan across people standing. Both the boundary rule and the predictive warning fired on the pass-by clip.

The cause was the ground point. DET-2 used the ankle joint, which sits about 4–5% of body height above floor contact, so a person 1–2% of the frame outside the zone's edge counted as inside. DET-2 was changed spec-first: horizontal position from the ankles, vertical position from the box bottom (soles), and the ankles only when the box is cut off by the frame. The test was updated before the code.

| Kind (3 clips, 0.5 min negative footage) | Before | After |
|---|---|---|
| approach | 1 hit, 1 false alarm, precision 50% (9–91%) | 1 hit, 0 false alarms, precision 100% (21–100%), warned 2.6 s before entry |
| boundary | 1 hit, 1 false alarm, precision 50% (9–91%) | 1 hit, 0 false alarms, precision 100% (21–100%), 0.2 s after entry |

These clips are synthetic composites (a cut-out photo moved across a floor). They validate the harness and show how one bias was caught; they are not accuracy. The intervals stay wide until the team records real staged clips. Runtime: 3 clips, 528 frames, 23 s on CPU.

**Verification.** `pytest`: 66 passed, including the new `test_evaluate.py` (Wilson values, one-to-one matching including late and early alerts, the end-to-end run on a generated video file) and the revised DET-2 test.

## SRC-4: server-side camera capture (2026-10-24)

**Bottleneck.** The browser sampled every frame. Browsers throttle timers in hidden tabs to about once per second, so a minimized dashboard dropped analysis to about 1 fps. That is below the rhythm rule's 8 fps minimum and coarse for every other rule. For a live demo, this was the main remaining reliability gap.

**Change (spec first).** SRC-4's acceptance criteria were written out, then five failing tests, then the code.
- `server/capture.py`: the server opens a webcam index (0–9) or an `rtsp://`, `rtsps://`, `http://` or `https://` stream with OpenCV. File paths and other schemes (`file:`, `concat:`…) are refused with 422.
  - A reader thread keeps only the newest frame, so camera buffers never fill and analysis never lags behind live.
  - An asyncio pump sends the newest unsent frame 12 times a second. Frames are encoded like the dashboard's (640 px, JPEG 65) and stamped with their read time.
  - A frame is never sent twice. A frozen stream analyzes nothing, rather than looking like a perfectly still child to the stillness rule.
- `server/app.py`: browser frames and captured frames share one `submit_frame` path (SRC-3 ordering, vision, incidents, clips).
  - `POST /api/frames` returns 409 while the server camera is the source.
  - `GET /api/camera/frame?after=N` long-polls for the analyzed JPEG plus the overlays computed from it, so boxes always match the picture. While paused, frames keep coming without overlays.
  - Health: `camera.capture` reports the masked source (never the URL password), `connecting`/`live`/`offline`, the camera's frame rate and the last error. No new frame for 2 s, or a camera that won't open, makes `camera.health` `offline`, and `camera_offline` and `camera_online` events are logged. The reader reopens every 2 s, and RTSP/HTTP reads time out after 5 s.
  - A reset, any other source, or shutdown releases the camera.
- Dashboard: a "Camera read by the NestWatch server" option in the source dialog. The live picture comes from the long poll, so no timers are involved. A reload returns to the server camera. The offline overlay names the source and says it is reconnecting, and the footer says "no frames" instead of the last 3 s rate.

**Found while testing.**
- The rate in the footer (SRC-2) is measured over the last 3 s of frames, so it still read 12.6 fps for about a second after the camera went offline. The footer now says "no frames" whenever health is offline; the SRC-2 calculation is unchanged.
- A dashboard showing a server camera always has one frame request open, so Playwright's `networkidle` never arrives. `camera-smoke.mjs` waits for `load`, and always resets the session in `finally` so a failed run cannot leave a camera running for the other suites.
- The new option's label first read "Camera on this computer or network", next to "Use this device's camera". It now says the server reads it.

**Measured.** All through real OpenCV FFmpeg and real YOLO26n-pose. The source is a synthetic MJPEG stream served over local HTTP, so no camera was opened. Numbers are from an isolated copy of the app on ports 8001/5174.

| Check | Result |
|---|---|
| Analysis with no dashboard tab open (`test:camera`, 15 fps 1280×720 stream) | 12.0–12.4 fps over 4 s, in two runs |
| Health after the stream stalls with the connection still open | `offline` after 2.0 s and 2.1 s (target ≤ 3 s) |
| Back to `active` after frames resume | 0.1–0.2 s |
| API CPU, 30 fps 1280×720 stream, analyzing at 11.9–12.0 fps | 1.17 cores (NFR-2 target ≤ 1.5); camera read at 29.8 fps |
| OpenCV opening a local HTTP MJPEG stream | 0.01 s; a stalled read returns after the 5 s timeout, then the stream is reopened |

The CPU figure is for frames with no people in them; per-frame pose time barely depends on content, but tracking adds a little per person.

**Verification.**
- `pytest`: 71 passed. New `server/tests/test_capture.py` uses fake cameras and covers:
  - which sources are accepted, and password masking
  - 12 fps sampling of the newest frame, with under 100 ms lag
  - a stall: offline in under 3 s, and no frame re-sent
  - reconnecting after a camera that won't open and a dropped stream
  - the API end to end with no browser: about 12 fps, overlays matching the picture, 409 for browser frames, picture continuing while paused, offline in under 3 s with one logged event, and the camera released on a source change
- `npm run build` passes.
- Browser: `test:ui`, `test:media`, `test:design` and the new `test:camera` all pass.

**Not verified.** A physical webcam and a real RTSP camera. The HTTP MJPEG test uses the same OpenCV FFmpeg path, but RTSP transport (UDP vs TCP, camera-specific codecs) is untested. The `npm start` that was already running when this work began still runs the earlier API code until it is restarted.

## SRC-5: several server cameras, and real footage to analyze (2026-10-24)

**Bottleneck.** One camera per server, and no reliable live footage: the team had a webcam, uploads and an illustration.

**Change.**
- `server/app.py`: `cam-01` stays the SRC-4 source; `POST/DELETE/GET /api/cameras` add up to three more, each with its own capture, `VisionEngine`, clip buffer and busy flag. `GET /api/camera/frame?camera=`. Incidents carry `camera_id` and the camera's room; dedupe and second opinions are per camera. Zones, rules and calibration stay on cam-01.
- `server/store.py`: reads take the store lock. Three capture loops sharing one SQLite connection with the threadpool produced `sqlite3.InterfaceError: bad parameter or other API misuse` in the first multi-camera test.
- Dashboard: the camera picker switches the stage among live cameras; the Focus/Grid strip shows each other camera's live picture with boxes and rates, plus an add/remove tile (`src/LiveCameras.tsx`).
- `scripts/cameras/`: MediaMTX config, demo-room builder (GMDCSA24), public-webcam relay (streamlink → ffmpeg → RTSP), `connect_demo.py`.

**Found while testing the relays.** HLS arrives in segment-sized bursts. Copied straight into RTSP, OpenCV saw ~44 fps bursts and multi-second gaps, and one stream failed to open within SRC-4's 5 s open timeout. `-re` in the relay restored a steady 30 fps with a largest gap of 0.08–0.11 s (12 s sample, three streams).

**Measured live** (Mana sandbox, real OpenCV + YOLO26n-pose, three RTSP feeds from MediaMTX, 60 s windows):

| Camera | Delivered | Analyzed (median) | People tracked |
|---|---|---|---|
| cam-01 daycare (recorded GMDCSA24 loop) | 15.0 fps | 5.2 fps | 1 in 97% of samples; **Possible fall** opened, evidence clip saved, call simulated |
| cam-02 Bourbon St (EarthCam, live) | 30.0 fps | 5.3 fps | 0–3, present in 60% of samples |
| cam-03 Times Square (EarthCam, live) | 30.0 fps | 5.6 fps | 0–2 of dozens visible |

The sandbox has a 4-core CPU quota shared with other processes; it was throttled in 92% of scheduler periods during the window (API alone 3.2 cores), and pose took ~180–300 ms per frame there, versus ~38 ms on a team laptop (D-1). Three cameras at 12 fps need about 3 × 12 × 38 ms ≈ 1.4 cores of pose plus decoding: plausible on a laptop, not yet measured there. Times Square briefly flapped offline/online under throttling.

**Detection finding.** Wide public views are transport tests, not detection tests: at 640 px, people in the Times Square crowd are 20–40 px tall and mostly missed, and Bourbon Street catches only people near the balcony. Daycare-like detection needs a camera where a person is at least ~100 px tall at 640 px, i.e. a room camera, which is what the recorded demo room and staged phone cameras provide.
