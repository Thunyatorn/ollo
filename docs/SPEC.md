# ollo specification

Status: source of truth for the build, 2026-10-24. Product name **ollo**; the repository and API keep the working name `lookout` until the M5 rename. This file supersedes [IMPLEMENTATION_SPEC.md](IMPLEMENTATION_SPEC.md) wherever they disagree; that file remains the research background.

**Promise.** ollo connects to existing CCTV security cameras, analyzes safety events in real time, and acts through caregiver notifications and AI agent phone calls until a responder takes responsibility. The product goal includes escalation of critical emergencies to 911 through a configured emergency-response workflow, with an incident record of what was observed and how people responded. Daycares are the first use case.

**Product direction and build scope.** The target workflow is CCTV feed → real-time analysis → notification or AI phone call → confirmed response → incident record. The current build implements compatible RTSP/HTTP camera ingestion, local event rules, dashboard alerts, caregiver call integrations, acknowledgment and incident records. External notification delivery and 911 integration remain future work. Before emergency calling is implemented, its policy must define escalation criteria, human confirmation requirements, location information, call content and failure handling. The requirements below describe the prototype; automatic emergency-service calls remain outside its current scope, and hackathon calls target consenting teammates only.

## How this spec is used

Development is spec-first. Every behavior has a requirement with a stable ID, testable acceptance criteria, and the tests that verify it.

1. **Change the spec first.** Add or edit the requirement and its acceptance criteria, with status `Planned`.
2. **Write the acceptance test.** Name it under the requirement's **Verify** line. It fails until the behavior exists.
3. **Implement** until the test passes. Then set the status to `Done`.
4. `server/tests/test_spec.py` enforces traceability on every `pytest` run:
   - every `Done` requirement names at least one verifying test, and every named test exists
   - every test function in `server/tests` is claimed by at least one requirement
   - requirement IDs are unique

**Statuses:** `Done` means verified by the listed tests. `Planned` means specified, not built. **Verify** entries are pytest tests (`file.py::test_name`), or for browser behavior, `scripts/*.mjs` smoke checks.

## Decisions

| ID | Decision | Why | Revisit if |
|---|---|---|---|
| D-1 | All detection is local: YOLO26n-pose with ByteTrack IDs and keypoint rules, on CPU. Frames are analyzed on the daycare's computer. | $0 per camera-hour. No live video leaves the machine. About 38 ms per frame at 12 fps on one laptop. | Child pose accuracy on staged clips (M6) is unusable. Then try RTMPose (Apache-2.0) or an optical-flow rhythm signal. |
| D-2 | Claude is never on the alert path. It runs only after a local rule has alerted: second opinion, plain-language rule setup, incident report. | A slow or failed cloud call can never delay or suppress an alert, and idle cost is $0. | — |
| D-3 | Keep the FastAPI + SQLite core as the single alert authority, and the React dashboard. Spacetime and Mana are **not** used as the core. | The lifecycle, timers, first-acknowledgment-wins, and call gating already work and are covered by tests. Rebuilding them in a new backend this weekend risks the one flow the demo depends on. | The team decides the Spacetime or Mana prize is worth it. Then add Spacetime as a read-only live mirror of incidents and positions for phones; FastAPI stays authoritative. |
| D-4 | Escalation calls use Twilio with Cartesia voice (built). Add a Cartesia Line voice agent for spoken acknowledgment ("I'm on it") behind the same call adapter. Wajo is not used. | Cartesia does real work in the call, which fits its sponsor track. Wajo Fo has no developer API for starting calls. | Cartesia Line cannot call back to our acknowledge endpoint (open question Q-1). |
| D-5 | Claude model IDs are configuration (`VISION_MODEL`, `CLAUDE_MODEL`). Settings show estimated cost per review. | The cost-quality trade is the team's call. Per-review cost is $0.0003 (Haiku 5.5) to about $0.01 (Opus 5.5). | — |
| D-6 | The browser samples recorded video and the browser webcam at 12 fps. A webcam or RTSP/HTTP camera can instead be read by the server with OpenCV (SRC-4), which the live demo uses. | Uploaded clips need browser playback. Server capture removes the hidden-tab throttling limit, so a minimized dashboard never slows analysis. | Several cameras per server are needed (out of scope today). |

## Glossary

- **Observation:** the vision engine's output for one frame: a kind, text, origin (`local_rule`, `model`, `fixture`) and priority.
- **Incident:** a server-owned record created from observations of one kind. It moves through the lifecycle in ALR-2.
- **Epoch:** a counter that increments on session start, stop, reset or source change. Anything stamped with an older epoch is ignored.
- **Second opinion:** Claude's structured context attached to an incident. It never changes the incident's status.

## Requirements

### Sources and analysis rate

#### SRC-1 · Recorded video
- **Status:** Done
- **Acceptance:** MP4, MOV or WebM up to 100 MB and 5 minutes is accepted, decoded once to validate it, and played in the dashboard. Analysis follows playback, so each analyzed frame carries the video's media time. Files that are too long, the wrong type, or don't decode are rejected with a clear error.
- **Verify:** `test_api.py::test_video_upload_validation`, `scripts/media-smoke.mjs`

#### SRC-2 · Analysis rate and its health
- **Status:** Done
- **Acceptance:** The dashboard samples at 12 fps (`ANALYSIS_FPS`) and skips a tick while an upload is in flight. The server reports frames actually analyzed per second (`camera.analysis_fps`). The video footer shows it and turns amber below 8 fps, the rhythm rule's minimum.
- **Verify:** `test_vision.py::test_analysis_fps_reports_recent_rate`, `test_events.py::test_rhythmic_movement_needs_band_power_amplitude_and_frame_rate`. Live measurement: 11.98 fps (improvement log, iteration 3).

#### SRC-3 · Frame ordering and staleness
- **Status:** Done
- **Acceptance:** Frames from an older epoch, an older session, or with a non-increasing sequence number are rejected and never change state. A session reset discards in-flight results.
- **Verify:** `test_vision.py::test_frames_epoch_order_and_boundary`, `test_coordinator.py::test_reset_invalidates_frames_and_jobs`

#### SRC-5 · Browser camera stays visible
- **Status:** Done
- **Why:** with "Use this device's camera", the picture went black after leaving the camera view (Settings, Incident history, another camera) and coming back. The stream was attached to the `<video>` element once, 80 ms after connecting; a re-created element never got it.
- **Acceptance:** after connecting the browser camera, the main camera view shows the live picture (frames advancing) on first connect, after a round trip through Settings, and after selecting another camera and selecting this one again.
- **Verify:** `scripts/webcam-smoke.mjs`

#### SRC-6 · Uploaded videos are analyzed by the server, every frame
- **Status:** Done
- **Why:** browser sampling (SRC-2) skips frames whenever the computer is busy or the tab is hidden. Measured on the stock runner clip (2026-10-24): the fall is caught at 6–12 fps and missed at 4 fps and 1 fps; the user's runs averaged about 6 fps and missed it.
- **Acceptance:**
  - **Server decodes.** For a recorded source (`POST /api/video`), the server reads the stored file itself and analyzes the frame at every 1/12 s of the video's own timeline (`ANALYSIS_FPS`), in order, through the same path as `POST /api/frames` (SRC-3 ordering, vision, incidents, clips). It never skips one: when analysis is busy, the next frame waits.
  - **Follows playback.** The dashboard sends only its playhead, `POST /api/playhead` with `{session_id, epoch, media_time_ms}`, several times a second. The server analyzes up to the playhead and no further, so alerts appear as the video plays. When the computer is slow or the tab is hidden, analysis falls behind and catches up; the reply carries `analyzed_to_ms` and the latest overlays.
  - **Pause and seek.** A paused playhead stops analysis at that point. A seek (a new epoch from `POST /api/session/start`) restarts analysis; frames of the old epoch never count.
  - **Where analysis starts.** `POST /api/session/start` may carry `{media_time_ms}`, the playback position the new epoch starts from (0 after an upload, the seek position after a seek). Analysis of that epoch begins there, even if the first playhead arrives late (a hidden tab); without it, at the first playhead.
  - **Only for recordings.** `POST /api/playhead` is refused (409) for any other source, and `POST /api/frames` is refused for a recording. The browser camera keeps SRC-2 sampling.
  - **The picture waits for the analysis.** Found 2026-10-25 on a 1080p iPhone clip: analysis ran 3–8 s behind playback (it starts only once the upload arrives, and this laptop analyzes at most about 13–14 fps), so every skeleton was filtered out as stale. When analysis is more than 0.5 s behind the playhead, the dashboard holds playback and shows "Analyzing…"; it resumes once analysis is within 0.15 s. If analysis makes no progress for 15 s, playback resumes with a notice. A pause, play or seek by the viewer ends the hold.
- **Verify:** `test_playback.py::test_every_frame_in_order_even_when_analysis_is_busy`, `test_playback.py::test_pause_and_seek_follow_the_playhead`, `test_playback.py::test_playhead_endpoint_analyzes_only_recordings`, `scripts/catchup-smoke.mjs`

#### SRC-4 · Server-side camera capture
- **Status:** Done
- **Acceptance:**
  - **Why.** Browsers throttle timers in hidden tabs, so browser sampling (SRC-2) drops to about 1 fps when the dashboard is minimized. With server capture, analysis does not depend on any browser tab.
  - **Choosing it.** `POST /api/source` with `{source_type: "server_camera", camera}`. `camera` is a webcam index from 0 to 9, or an `rtsp://`, `rtsps://`, `http://` or `https://` stream URL with a host, at most 500 characters. Anything else, including file paths and other URL schemes, is rejected with 422 and changes nothing. A valid source resets the session like any other source change and opens the camera in the server process. `POST /api/session/start` then starts analysis, and no browser is needed after that.
  - **Capture.** A reader thread reads frames continuously and keeps only the newest, so camera buffers never fill and analysis never falls behind live. Every 1/12 s, the newest frame not yet sent is scaled to 640 px wide and encoded as JPEG quality 65, like the dashboard's frames. It is stamped with the time it was read (`media_time_ms`, from the start of capture) and goes through the same path as `POST /api/frames`: SRC-3 ordering, the vision engine, incidents and clips.
  - **No repeats.** Each camera frame is analyzed at most once. When the camera delivers no new frame, nothing is analyzed, so a frozen stream can never look like a still child (DET-8).
  - **One source.** While the server camera is the source, `POST /api/frames` returns 409.
  - **Live picture.** `GET /api/camera/frame?after=N` waits up to 1 s for a frame newer than `frame_seq` N. It returns `{frame_seq, media_time_ms, image, overlays}`: the JPEG that was analyzed and the overlays computed from it, so boxes always match the picture. While analysis is paused, frames keep coming with no overlays. It returns 204 when no frame arrives in time and 404 without a server camera, and needs the operator session (PRV-2).
  - **Dashboard.** The source dialog takes the index or URL. The dashboard then shows these frames with the overlays and samples nothing itself. A reloaded dashboard returns to the server camera view.
  - **Health.** `camera.capture` reports:
    - the source, with any URL password masked
    - `status`: `connecting`, `live` or `offline`
    - the camera's delivered frame rate and the last error

    `camera.analysis_fps` reports frames analyzed (SRC-2). If no new frame arrives for 2 s, or the camera cannot be opened, the capture is `offline` and `camera.health` is `offline`, which is within 3 s of the stream stopping. A `camera_offline` event is logged then, and `camera_online` when frames resume. The capture retries opening every 2 s.
  - **Release.** A session reset, any other source (upload, browser webcam, fixture), or server shutdown stops capture and releases the camera.
  - **Testing.** Tests use a fake capture object and never open a real camera. The browser check serves a generated MJPEG stream over local HTTP, so the real OpenCV path is exercised.
- **Verify:** `test_capture.py::test_camera_spec_accepts_index_and_stream_urls_only`, `test_capture.py::test_capture_samples_newest_frames_at_12_fps`, `test_capture.py::test_stalled_stream_goes_offline_within_3_s_and_never_repeats_a_frame`, `test_capture.py::test_capture_reconnects_when_the_camera_drops_or_cannot_open`, `test_capture.py::test_server_camera_runs_analysis_without_a_browser`, `scripts/camera-smoke.mjs`. Live, through real OpenCV and YOLO pose: 12.0–12.4 fps analyzed with no dashboard tab open, and reported offline 2.0–2.1 s after the stream stalled (improvement log, SRC-4).

### Detection

#### DET-1 · Local pose detection with per-person tracking
- **Status:** Done
- **Acceptance:**
  - Each analyzed frame yields people with a box, 17 keypoints and a stable track ID.
  - Weights load only from `models/`; nothing is downloaded at runtime.
  - The tracker restarts on session reset.
  - Without the pose model, the HOG detector runs instead and its single-subject rules still work.
- **Verify:** `test_pose.py::test_real_pose_model_loads_and_resets_tracker`, `test_vision.py::test_jpeg_bounds_and_blank_detector`

#### DET-2 · Ground point
- **Status:** Done
- **Acceptance:**
  - A person's ground point takes its horizontal position from their confident ankles (else the box center) and its vertical position from the box bottom, where the soles touch the floor.
  - When the box touches the frame's bottom edge, the vertical position comes from the ankles instead. If the ankles are also hidden, the ground point is **unknown**.
  - Found by EVAL-1: ankle joints sit about 4–5% of body height above floor contact, which put a person walking just outside a zone's edge inside it.
- **Verify:** `test_pose.py::test_foot_point_prefers_confident_ankles`

#### DET-3 · Restricted-zone entry
- **Status:** Done
- **Acceptance:**
  - Each tracked person has their own hysteresis: 3 consecutive inside observations confirm entry.
  - Missing or unknown data never counts as outside.
  - A track unseen for 1.5 s is forgotten.
  - Entry creates a `boundary` incident naming the person's track.
- **Verify:** `test_vision.py::test_polygon_and_validation`, `test_vision.py::test_hysteresis_presence_crossing_and_loss`, `test_pose.py::test_each_tracked_person_has_own_zone_state`, `test_pose.py::test_missing_track_is_unknown_then_forgotten`

#### DET-4 · Evidence accumulation
- **Status:** Done
- **Acceptance:** Rules other than zone entry integrate evidence with a time-weighted CUSUM, S ← max(0, S + (score − k)·Δt), and fire when S > h. Δt is capped at 1 s, so a frame gap is not evidence, and each rule has a refractory period.
- **Verify:** `test_events.py::test_cusum_needs_sustained_evidence_and_respects_refractory`

#### DET-5 · Possible choking: hands at the throat
- **Status:** Done
- **Acceptance:**
  - Both wrists within 0.25 torso lengths of the throat point, sustained, alerts within 2 s.
  - One hand, or both hands for under 1 s, never alerts.
  - The incident text names the benign look-alikes.
- **Verify:** `test_events.py::test_hands_at_throat_fires_once_and_ignores_look_alikes`, `test_events.py::test_engine_turns_local_rule_into_observation`

#### DET-6 · Possible fall
- **Status:** Done
- **Acceptance:**
  - Alerts after a fast drop, followed within 3 s by staying down. A fast drop is either:
    - the hips dropping more than 0.3 upright body lengths within 1 s, or
    - body height collapsing from at least 0.85 to at most 0.7 of upright height within 1.5 s.

    Each drop pairs with its own way of staying down:
    - a hip drop with lying (torso more than 55° from vertical, or a wide box) for 1 s
    - a height collapse with staying low (at most 0.75 of upright height, box not lying-wide) for 1.5 s. A hand within 0.15 body lengths of the floor is required when the low posture begins, which separates a fall from a quick sit; after that the hands may lift. Gaps up to 0.5 s are tolerated, but the person must still be low when the alert fires.

    A slow lie-down collapses height too, but ends flat and wide, so it never matches the hands-and-knees path.
  - Measured on the stock clip: the runner lifted her hands briefly while staying low, which an every-frame hands requirement treated as getting up.
  - Found on real footage: a runner falling forward toward the camera onto hands and knees barely moved her hips in the image and never looked horizontal, but her height collapsed and her hands reached the floor.
  - Lying down slowly (over 5 s) never alerts.
  - A quick drop to sitting upright with hands on the lap never alerts.
  - A quick crouch with hands to the floor that stands back up within 1.5 s never alerts.
- **Verify:** `test_events.py::test_fall_requires_fast_drop_then_lying`, `test_events.py::test_forward_fall_onto_hands_and_its_look_alikes`

#### DET-7 · Unusual rhythmic movement (seizure-like)
- **Status:** Done
- **Acceptance:**
  - A limb counts as rhythmic when its amplitude exceeds 2% of body length, its strongest frequency is 1–5 Hz, and more than 60% of its power is within ±0.5 Hz of that peak or its first harmonic.
  - Two or more rhythmic limbs, sustained, alert within 10 s.
  - Pose jitter up to 5% of body length, waving below 1 Hz, and movement above 5 Hz never alert.
  - The rule reports `needs ≥8 fps` and stays silent when the analysis rate is too low.
- **Verify:** `test_events.py::test_rhythmic_movement_needs_band_power_amplitude_and_frame_rate`

#### DET-8 · Prolonged stillness
- **Status:** Done
- **Acceptance:** Alerts when mean keypoint movement over 2 s stays under 4% of body length for `stillness_seconds` (10–600, default 30). Walking never alerts. `nap_mode` suppresses the rule.
- **Verify:** `test_events.py::test_stillness_duration_motion_and_nap_mode`

#### DET-9 · Predictive zone warning
- **Status:** Done
- **Acceptance:**
  - **Calibration.** In calibration mode the operator clicks at least 4 floor points on the video and enters each point's floor-plan position in meters. `POST /api/calibration` fits H (normalized image → meters) with `cv2.findHomography`, using RANSAC with a 0.15 m threshold when there are 6 or more points.
  - **Calibration is rejected** (422, nothing saved) when there are fewer than 4 points, duplicate or collinear points, coordinates out of range, fewer than 4 points survive RANSAC, or any point used lands more than 0.15 m from its measured position. A worst-point check catches a mistyped measurement that an average would hide; 4 points always fit exactly, so the UI recommends 5 or more. The saved calibration reports its mean and worst error and any ignored points. `DELETE /api/calibration` removes it.
  - **Zone.** The restricted zone, drawn on the video floor, is mapped to the floor plan through H.
  - **Tracking.** Each track's ground point (DET-2) feeds a constant-velocity Kalman filter on the floor plane. Process noise uses white acceleration (σₐ = 1.5 m/s²). Measurement noise is R_floor = J·R_img·Jᵀ + (2 cm)²·I, with J the homography's Jacobian at the ground point and R_img = (1% of the frame)². Velocity starts at 0 ± 0.5 m/s.
  - **Probability.** P(entry ≤ τ), with τ = 3 s, is the fraction of 200 velocity samples drawn from N(v̂, P_vv) whose straight-line path from the current position crosses a zone edge within τ.
  - **Warning.** Raised for a person who is not inside the zone and has been tracked for at least 0.5 s, once P > 0.5 on 2 consecutive frames. It clears when P < 0.3, on entry, or when the track is lost.
  - **Presentation.** The warning is transient, not an incident, and never escalates. While it is active, the video shows the person's predicted path for τ and "Restricted area in ~N s". One `approach_warning` event per episode is logged in the history. Actual entry still raises DET-3.
  - **Without calibration** the rule is inactive and reports `needs calibration`.
  - **Synthetic acceptance cases** (12 fps, 3 cm ground-point noise):
    - Walking straight at 1 m/s toward a zone 4 m away warns at least 2 s before entry.
    - Walking parallel to the zone edge, 0.5 m away, never warns.
    - Standing still 1 m from the zone with 5 cm jitter never warns.
- **Verify:** `test_predict.py::test_calibration_fits_and_rejects_bad_points`, `test_predict.py::test_jacobian_matches_finite_difference`, `test_predict.py::test_entry_probability_geometry`, `test_predict.py::test_kalman_recovers_walking_velocity`, `test_predict.py::test_approach_warns_early_and_ignores_look_alikes`, `test_predict.py::test_engine_warns_without_creating_an_incident`, `test_api.py::test_calibration_endpoint`, `test_api.py::test_approach_observation_logs_event_not_incident`

#### DET-10 · Unsupervised child
- **Status:** Planned (add-on)
- **Acceptance:** Caregivers are tagged once per session by clicking their track. Alerts when a tagged child's floor-plan distance to the nearest tagged adult exceeds `D_max` (default 4 m) for `T` (default 20 s). Needs DET-9 calibration.

### Alerts and lifecycle

#### ALR-1 · One incident per ongoing condition
- **Status:** Done
- **Acceptance:** Repeated observations of the same kind extend the open incident instead of creating new ones. A condition that persists right after resolution does not reopen it within 30 s.
- **Verify:** `test_coordinator.py::test_incident_dedupe_and_lifecycle`

#### ALR-2 · Lifecycle
- **Status:** Done
- **Acceptance:**
  - Open → acknowledged → resolved.
  - Open → dismissed, which requires a reason.
  - Resolving requires acknowledgment first.
  - Closed incidents are immutable.
  - Answering a phone call is not acknowledgment.
- **Verify:** `test_coordinator.py::test_resolve_requires_acknowledgment`, `test_api.py::test_signed_callbacks_order_and_answer_is_not_ack`

#### ALR-3 · First acknowledgment owns the alert
- **Status:** Done
- **Acceptance:** The first acknowledgment from any channel (dashboard, call keypad, voice) sets `assigned_responder`. Later acknowledgments never change it. Acknowledgment cancels queued and active calls.
- **Verify:** `test_coordinator.py::test_incident_dedupe_and_lifecycle`

#### ALR-4 · Server-side escalation ladder
- **Status:** Done
- **Acceptance:**
  - On open, the primary step is queued at `primary_delay_seconds` and the backup at `backup_delay_seconds`, with backup after primary and both 1–120 s.
  - A job is claimed exactly once.
  - A primary that cannot respond (keypad 2 or the decline action) moves the backup to now, once.
  - Stale or closed incidents never dispatch.
- **Verify:** `test_coordinator.py::test_durable_single_job_claim`, `test_coordinator.py::test_decline_expedites_only_one_backup_and_rejects_stale`

#### ALR-5 · Kind-specific titles and limitations
- **Status:** Done
- **Acceptance:** Every incident kind (`boundary`, `distress`, `fall`, `rhythmic`, `stillness`) has one title, one spoken phrase, and its own limitations (for example "Injury cannot be determined from video"). They come from `KINDS` and are shown on the incident.
- **Verify:** `test_coordinator.py::test_every_kind_has_title_phrase_and_limitations`, `test_events.py::test_engine_turns_local_rule_into_observation`

#### ALR-6 · Records stay readable while they are written
- **Status:** Done
- **Acceptance:** The dashboard's `/api/state` reads incidents, events, call attempts and settings in a worker thread while the coordinator and frame processing write in other threads. Reads and writes from several threads at once never raise and never return a half-read row. Each read returns a consistent snapshot.
- **Verify:** `test_store.py::test_concurrent_reads_and_writes_never_fail`

### Escalation calls

#### ESC-1 · Simulation unless explicitly armed
- **Status:** Done
- **Acceptance:** No real call is placed unless all of these hold:
  - `CALLS_ENABLED=true`
  - provider credentials are present
  - the callback URL is HTTPS, and it reaches this server: `GET {PUBLIC_CALLBACK_BASE_URL}/health` answers with this server's health reply. Checked when arming (a refusal says to start the tunnel) and again before each real call (a dead tunnel fails the call with that reason instead of dialing a phone that would hear "application error"). Found 2026-10-24: the ngrok tunnel had stopped and an answered call could not fetch its instructions.
  - the E.164 destination is on the allowlist
  - the operator has armed calls this session

  Arming resets on restart. There are at most 6 real calls per session. Destinations come only from server configuration.
- **Verify:** `test_api.py::test_simulation_cannot_place_call`, `test_twilio_trial.py::test_unreachable_callback_blocks_arming_and_calls`

#### ESC-2 · Keypad acknowledgment with signed callbacks
- **Status:** Done
- **Acceptance:**
  - Twilio callbacks must carry a valid signature.
  - Out-of-order status updates never move a call backwards.
  - Pressing 1 acknowledges as that caregiver; pressing 2 declines.
  - The call message is generated with Cartesia voice.
- **Verify:** `test_api.py::test_signed_callbacks_order_and_answer_is_not_ack`

#### ESC-4 · Keypad call on a Twilio trial account
- **Status:** Done
- **Why:** Twilio trial accounts reject inline TwiML and status callbacks ("limited parameter access", 400) and send webhooks without a signature. Found by the team's real test calls; the ESC-2 call never got through on a trial account.
- **Acceptance:**
  - **Call creation.** `POST /2010-04-01/Accounts/{sid}/Calls.json` sends only `To`, `From` and `Url` = `{PUBLIC_CALLBACK_BASE_URL}/webhooks/twilio/voice/{call_token}`, where `call_token` is fresh and random per call. A paid account (account `type` not `Trial`, checked once and cached; unknown counts as trial) also gets `Timeout`, `StatusCallback` and its events.
  - **Instructions.** `POST /webhooks/twilio/voice/{call_token}` returns the TwiML: play the Cartesia audio, gather one digit with action `/webhooks/twilio/digits/{call_token}`, then hang up. An unknown or expired token → 404.
  - **Webhook trust.** A request carrying `X-Twilio-Signature` must have a valid signature. A request without one is accepted only when its token matches an attempt (only the token's SHA-256 is stored), the form's `AccountSid` is ours, and its `CallSid` is that attempt's call.
  - **Keypad.** Through the token route, 1 acknowledges and 2 declines exactly as ESC-2.
  - **Call progress without callbacks.** The server reads the call's status from Twilio every 2 s until it ends. Updates follow the same rules as the status webhook: never backwards, and a primary call that ends unacknowledged moves the backup call to now (ALR-4). A call still queued or ringing after 40 s is hung up.
  - **Testing.** Mocked HTTP only; tests never place calls.
- **Verify:** `test_twilio_trial.py::test_trial_call_sends_only_to_from_url`, `test_twilio_trial.py::test_voice_instructions_and_unsigned_keypad_need_token_account_and_call`, `test_twilio_trial.py::test_polled_status_moves_forward_and_expedites_backup`

#### ESC-5 · The keypad call never waits for speech
- **Status:** Done
- **Why:** in the first real test (2026-10-24) the call was created 26 s after the alert instead of 8 s. Cartesia speech for the message took 3.0–9.3 s from the venue network, and the call waited for it. Twilio fetches the audio only after the phone is answered, so the wait bought nothing.
- **Acceptance:**
  - **Dial first.** Twilio call creation starts without waiting for Cartesia; the speech is generated at the same time.
  - **Answered before the speech is ready.** `/webhooks/twilio/voice/{token}` waits up to 10 s for the speech, then plays it. If the speech failed or is still not ready, the instructions use Twilio's own `<Say>` with the same text, so the caregiver always hears the alert and can still press 1 or 2.
  - **Reuse.** Speech is kept per message text; the same message never asks Cartesia twice.
  - **Prepared on arming.** Arming real calls checks the Twilio account type and prepares the speech for every alert kind in the current room, in the background.
- **Verify:** `test_call_speed.py::test_call_is_created_before_speech_is_ready`, `test_call_speed.py::test_answered_call_waits_for_speech_or_falls_back_to_say`, `test_call_speed.py::test_arming_prepares_speech_for_every_kind_once`

#### ESC-3 · Spoken acknowledgment through a Cartesia voice agent
- **Status:** Done
- **Acceptance:**
  - **Provider choice.** `CALL_PROVIDER` selects the provider: `twilio` (default, keypad, ESC-2) or `cartesia_agent`. The ESC-1 gates apply to both.
  - **Configuration.** `cartesia_agent` additionally needs `CARTESIA_API_KEY`, `CARTESIA_AGENT_ID`, `CARTESIA_FROM_NUMBER_ID` and `VOICE_WEBHOOK_SECRET`.
  - **Placing the call.** `POST https://api.cartesia.ai/agents/calls`, with headers `X-API-Key` and `Cartesia-Version`. Each destination carries `dynamic_variables`: `room`, `alert` (the incident title), `caregiver` (the step's caregiver name), and a fresh random `ack_token`.
  - **Recording the call.** The attempt stores the `agent_call_id` and only a SHA-256 hash of the token. A per-destination `error`, or an HTTP failure, counts as a failed placement.
  - **Fallback.** If placement fails and Twilio is configured, the same step falls back to the Twilio keypad call.
  - **Webhook.** `POST /webhooks/voice/ack` is called by the agent's webhook tool with `Authorization: Bearer <VOICE_WEBHOOK_SECRET>` and JSON `{token, decision}`, where `decision` is `acknowledge` or `decline`.
    - A wrong secret → 403.
    - An unknown or already-used token → 409.
    - `acknowledge` acknowledges as that step's caregiver through ALR-3, via `voice`.
    - `decline` behaves like keypad 2 (ALR-4).
    - Each token works once.
  - **Reply to the agent.** A plain sentence the agent can say: "acknowledged", "the backup caregiver will be called", or "already handled by ⟨name⟩" when someone else acknowledged first.
  - **No hang-up.** Cartesia documents no hang-up endpoint, so an agent call is not cancelled remotely. The "already handled" reply lets the agent end it.
  - **Testing.** Tests use mocked HTTP; tests never place calls.
- **Verify:** `test_voice.py::test_cartesia_agent_places_call_with_hashed_token`, `test_voice.py::test_voice_webhook_acknowledges_once_and_checks_secret`, `test_voice.py::test_voice_decline_and_already_handled_replies`, `test_voice.py::test_failed_agent_call_falls_back_to_keypad`

### Claude (never on the alert path)

#### AI-1 · Second opinion only after a local alert
- **Status:** Done
- **Acceptance:**
  - When enabled and configured, a review starts only after a `local_rule` observation of kind distress, fall, rhythmic or stillness.
  - Zero requests are made while nothing happens.
  - One review runs at a time, and the latest trigger wins.
  - The session request cap applies.
- **Verify:** `test_review.py::test_review_runs_only_after_a_local_alert`

#### AI-2 · Privacy of frames sent to Claude
- **Status:** Done
- **Acceptance:** At most 4 frames are sent per review. Each is cropped to the flagged person's padded box, has every visible head blurred first, and is at most 512 px on its long side. Other people outside the crop are not sent.
- **Verify:** `test_review.py::test_crop_blurs_heads_and_keeps_only_the_flagged_person`

#### AI-3 · Structured, validated output
- **Status:** Done
- **Acceptance:**
  - The request uses JSON-schema structured output, not forced tool use, and `effort: low`.
  - The response must validate: the assessment is one of three values, a concern requires a visible observation, and no extra fields are allowed. Observations must cite frames that were sent.
  - Models with safety classifiers send `fallbacks: "default"`.
- **Verify:** `test_review.py::test_schema_abstention_and_required_evidence`, `test_review.py::test_fallbacks_for_models_with_safety_declines`

#### AI-4 · The opinion never changes the alert
- **Status:** Done
- **Acceptance:**
  - The opinion is attached to the newest incident of that kind as `second_opinion`; status and priority are unchanged.
  - A decline, an error, invalid output, or a session reset during the request leaves the incident untouched.
  - Results are delivered even if no further frame arrives.
- **Verify:** `test_review.py::test_decline_or_late_result_never_touches_the_alert`, `test_review.py::test_callback_attaches_opinion_without_changing_incident_status`

#### AI-5 · Cost visibility
- **Status:** Done
- **Acceptance:** Each opinion records its model, tokens and USD cost from the price table. The session meter (requests, tokens, USD) is shown in settings. An unknown model shows tokens without a price.
- **Verify:** `test_review.py::test_cost_table`, `test_review.py::test_review_runs_only_after_a_local_alert`

#### AI-6 · Plain-language rules
- **Status:** Done
- **Acceptance:**
  - **Landmarks.** In landmark mode the operator clicks 3–12 points on the video and names the place (1–40 characters, unique, for example "kitchen gate").
    - `POST /api/landmarks` validates and stores it.
    - `DELETE /api/landmarks/{id}` removes it and every rule that uses it.
  - **Drafting.** `POST /api/rules/draft` with `{text}` (at most 300 characters) sends the text and the list of landmark IDs and names to `CLAUDE_MODEL` (default `claude-opus-5-5`, effort low, `fallbacks: "default"`). The request uses JSON-schema structured output. The result is either:
    - `propose`: a landmark ID; a schedule of `always`, `window` (`HH:MM`–`HH:MM`, server local time, may wrap past midnight) or `nap` (while nap mode is on); a severity of `high` or `critical`; and a one-line summary
    - `clarify`: one question
  - **Validation.** The server checks the result. An unknown landmark ID, an invalid time, or a model error becomes a clarification question, and nothing is created. A valid proposal is saved as a rule with status `draft`.
  - **Not configured.** Without an API key and model, the draft endpoint returns 503 and creates nothing.
  - **Confirmation.** A draft is never enforced. On the dashboard the draft's landmark is outlined on the video. `POST /api/rules/{id}/confirm` makes it `active`; `DELETE /api/rules/{id}` removes it.
  - **Enforcement.**
    - While an active rule's schedule applies, its landmark is a restricted zone.
    - Each restricted zone has its own per-person entry state (DET-3) and predictive warning (DET-9), and incident text names the zone.
    - The original single zone remains as the default zone.
- **Verify:** `test_rules.py::test_landmark_validation_and_cascade_delete`, `test_rules.py::test_draft_proposal_is_saved_as_draft`, `test_rules.py::test_unknown_landmark_or_bad_time_becomes_a_question`, `test_rules.py::test_draft_without_claude_creates_nothing`, `test_rules.py::test_schedule_windows_wrap_and_nap`, `test_rules.py::test_engine_enforces_only_confirmed_rules_in_schedule`

#### AI-7 · Incident report
- **Status:** Done
- **Acceptance:**
  - **Event linkage.** Every event written about an incident records the incident's ID: opened, call attempts, decline, acknowledgment, resolution or dismissal, second opinion, and evidence clip.
  - **Facts.** `GET /api/incidents/{id}/report` builds numbered facts (F1, F2, …) only from stored data: the opening (time, title, priority, origin, room), each observation, each linked event, each call attempt's status, and the second opinion.
  - **Plain timeline.** Without Claude, or with `?ai=false`, the report is those facts rendered as a timeline.
  - **Claude version.** With Claude (`CLAUDE_MODEL`, JSON-schema output of `{lines: [{text, facts}]}`), each line must cite at least one existing fact. A line is removed, and counted, if it:
    - cites no fact or an unknown fact, or
    - asserts a diagnosis or outcome ("choked", "had a seizure", "was injured", "unconscious", "not breathing", "diagnosed").

    If no line survives, or Claude fails, the plain timeline is used.
  - **Footer.** Every report ends with the incident's limitations, verbatim, and the line "Generated by ollo from logged events."
  - **Response.** `{markdown, source: claude|facts, removed_lines, facts}`. The incident card has a Report button that shows the Markdown and downloads it as a `.md` file.
  - **Testing.** Tests use a fake client.
- **Verify:** `test_report.py::test_events_are_linked_to_their_incident`, `test_report.py::test_plain_timeline_from_facts`, `test_report.py::test_claude_lines_must_cite_facts_and_avoid_diagnosis`, `test_report.py::test_report_falls_back_when_no_line_survives`

### Dashboard

#### UI-1 · Live overlays at the frame rate
- **Status:** Done
- **Acceptance:** Each frame upload's response carries the latest overlays, so tracking boxes refresh at the analysis rate. They were visible in 100% of samples during playback (improvement log, iteration 3).
- **Verify:** `test_api.py::test_frame_response_carries_overlays`

#### UI-2 · Event trace
- **Status:** Done
- **Acceptance:** Each incident shows its title, priority, media time, status, first observation, its own limitations, escalation steps with live status, the second opinion card (when present), and acknowledge, resolve and dismiss actions.
- **Verify:** `scripts/smoke.mjs` (lifecycle actions). The second-opinion card was checked live (improvement log, iteration 4).

#### UI-3 · Who owns the alert
- **Status:** Done
- **Acceptance:**
  - The first acknowledgment records `assigned_responder` and `acknowledged_via` (`dashboard`, `app`, `keypad` or `voice`); later acknowledgments change neither.
  - Keypad and voice acknowledgments name the caregiver configured for that step.
  - After acknowledgment, every connected view shows "Handled by ⟨name⟩ via ⟨channel⟩" within 2 s (the state poll).
- **Verify:** `test_coordinator.py::test_acknowledgment_records_channel_first_wins`, `test_voice.py::test_voice_webhook_acknowledges_once_and_checks_secret`. Live check: shown 120 ms after acknowledgment (improvement log, M2).

#### UI-4 · Floor plan view
- **Status:** Done
- **Acceptance:**
  - **Data.** When the floor is calibrated (DET-9), `GET /api/state` includes `floor_plan` with the calibration points, the zones in force and the landmarks, all in meters. Each tracked person's overlay carries their floor position (`floor`), and a warned person carries `approach.floor_path`.
  - **View.** A Map button on the video toggles a top-down inset scaled to fit, drawn in meters:
    - zones in force are filled
    - landmarks are outlined
    - each person is a dot labeled with their track ID
    - a warned person's predicted path is drawn in amber
  - **Without calibration** the button explains that calibration is needed.
- **Verify:** `test_predict.py::test_state_exposes_floor_plan`, `scripts/design-smoke.mjs`

#### UI-5 · Caregiver mobile view
- **Status:** Done
- **Acceptance:**
  - `/respond/{id}` at 375 px width shows an open alert with one large "I am responding" button and a secondary "I cannot respond". The secondary button disappears once someone owns the alert, since a declined handoff is only possible while it is open.
  - Acknowledging there records the channel `app` and the caregiver's name.
  - Once acknowledged, the page shows "Handled by ⟨name⟩ via ⟨channel⟩".
  - No horizontal scroll.
  - Remote pairing and authentication are future work.
- **Verify:** `test_api.py::test_mobile_acknowledgment_records_app_channel`, `scripts/smoke.mjs`, `scripts/design-smoke.mjs`

#### UI-6 · ollo branding and skeleton overlay
- **Status:** Done
- **Acceptance:**
  - The page title and brand read ollo, and no visible text says Lookout.
  - Each tracked person is drawn as a keypoint skeleton (COCO limb pairs, confident keypoints only) under their box, labeled with their track ID.
  - Fixture, illustration and simulated states stay visibly labeled.
  - The restricted zone is drawn on the video only while it is enabled; a disabled zone draws nothing (found 2026-10-25: the dashed box stayed after the zone was switched off).
  - Found after the 2026-10-24 UI update: the skeleton vanished because overlays were shown only for role IDs (`primary`, …) while the server labels roles "Primary caregiver". Staff roles are matched by their first word, so either form shows overlays.
- **Verify:** `scripts/design-smoke.mjs`, `scripts/skeleton-smoke.mjs`

### Privacy and safety

#### PRV-1 · No live video leaves the machine
- **Status:** Done
- **Acceptance:** Frames go only to the local API. The only outbound media are AI-2 crops (opt-in) and call audio. There is no identity, face, or age recognition anywhere.
- **Verify:** `test_review.py::test_review_runs_only_after_a_local_alert`, `test_review.py::test_crop_blurs_heads_and_keeps_only_the_flagged_person`

#### PRV-2 · Local operator session
- **Status:** Done
- **Acceptance:**
  - Bootstrap works only from loopback.
  - API calls require the session cookie or bearer token.
  - Foreign origins are rejected.
  - Callback routes are exempt only because they verify signatures.
- **Verify:** `test_api.py::test_auth_and_fixture_flow`

#### PRV-3 · Evidence clips
- **Status:** Done
- **Acceptance:**
  - **Clip.** When an incident opens, the analyzed frames from 5 s before to 5 s after are saved as a VP8 WebM at the analysis frame rate, under `DATA_DIR/clips`.
  - **Blurring.** Every visible head is blurred in every clip frame, using face keypoints or else the top of the person's box. Evidence stills are blurred the same way.
  - **Linking.** The clip is linked as the incident's `clip_url`, and an "Evidence clip saved" event is logged against the incident.
  - **Session changes.** A session reset, stop or source change finalizes clips in progress with the frames they have.
  - **Retention.** `clip_retention_days` (1–90, default 7). Older clips and stills are deleted from disk at startup and every hour, and their links are removed from incidents.
- **Verify:** `test_clips.py::test_clip_covers_before_and_after_and_blurs_heads`, `test_clips.py::test_reset_finalizes_partial_clip`, `test_clips.py::test_retention_deletes_files_and_links`

### Evaluation

#### EVAL-1 · Measured accuracy on staged clips
- **Status:** Done
- **Acceptance:**
  - **Running it.** `npm run eval -- <labels.json> [--split test]` (`python -m server.evaluate`) reads a label file listing clips. Each clip has a path, a split (`tune` or `test`), optional engine `settings` (zone, calibration, rules), and its events (`kind`, `onset_s`). A clip with no events is a negative clip.
  - **Processing.** Each clip is sampled at 12 fps, encoded like the dashboard (640 px wide, JPEG quality 65), and run through the real engine offline on the clip's own timeline.
  - **Scoring.** A hit is an alert of the right kind from 0 to 5 s after onset. Each alert and each labeled event matches at most once. Unmatched alerts are false alarms.
  - **Report, per kind:**
    - true positives, false negatives and false positives
    - precision and recall, each with a Wilson 95% interval
    - mean alert delay over hits
    - false alarms per hour of negative footage
  - **Output.** Written as JSON and a Markdown table. The Markdown names the split and states that staged clips are not deployment accuracy.
- **Verify:** `test_evaluate.py::test_wilson_interval_known_values`, `test_evaluate.py::test_matching_counts_hits_misses_and_false_alarms`, `test_evaluate.py::test_runs_engine_on_video_files`

## Non-functional requirements

| ID | Requirement | Target | Measured |
|---|---|---|---|
| NFR-1 | Per-frame analysis latency at 12 fps | p95 ≤ 83 ms | p95 43 ms (iteration 3) |
| NFR-2 | API CPU while analyzing at 12 fps | ≤ 1.5 cores | 1.3 cores (`POSE_THREADS=3`) |
| NFR-3 | Cloud cost while nothing happens | $0 | $0 (AI-1 test) |
| NFR-4 | Alert delay from onset | throat ≤ 2 s, fall ≤ 1.5 s after the drop, rhythm ≤ 10 s, zone ≤ 0.5 s | 1.5 s, 1.0 s, 8.3 s; zone 0.25 s (3 frames at 12 fps, derived) |
| NFR-5 | Claude cost per review | ≤ $0.02 on any current model | estimated $0.0003–$0.025 (iteration 4) |

## Interfaces

**Incident states.** `open → acknowledged → resolved`, and `open → dismissed` (with a reason). Each transition records an event and cancels queued calls.

**Observation** (vision engine → API): `{kind, observations: [text], origin: local_rule|model|fixture, priority: medium|high|critical, track_id, frame_seq, media_time_ms}`. A second opinion arrives as `{kind: "review", target_kind, review}` or through the `on_review` callback.

**Main endpoints:**
- `GET /api/state` returns session, camera health (`analysis_fps`, `detector`), incidents, events and overlays.
- `POST /api/frames` returns `{accepted, overlays}`.
- `POST /api/source` and `GET /api/camera/frame` (SRC-4 server camera).
- `POST /api/incidents/{id}/{acknowledge|resolve|dismiss|decline}`
- `PUT /api/settings`
- `POST /api/video`
- `POST /api/session/{start|pause|stop|reset}`
- `POST /api/session/arm-calls`
- `POST /webhooks/twilio/{status|digits}`, and on trial accounts `POST /webhooks/twilio/{voice|digits}/{call_token}` (ESC-4)
- `POST /api/calibration` and `DELETE /api/calibration` (DET-9).
- `POST /webhooks/voice/ack` (ESC-3, called by the Cartesia agent's webhook tool).
- `POST /api/landmarks`, `DELETE /api/landmarks/{id}`, `POST /api/rules/draft`, `POST /api/rules/{id}/confirm`, `DELETE /api/rules/{id}` (AI-6).
- `GET /api/incidents/{id}/report` (AI-7).

## Build plan

Each milestone ends with the full suite green, traceability enforced, a live check in the browser, and an entry in [IMPROVEMENT_LOG.md](IMPROVEMENT_LOG.md).

| Milestone | Requirements | Exit criteria |
|---|---|---|
| **M0 · Spec** (done with this file) | traceability | `test_spec.py` passes; every existing test is claimed by a requirement |
| **M1 · Predict** (done) | DET-9 | Synthetic DET-9 cases pass; calibration endpoint works; the warning is visible on the video |
| **M2 · Respond** (done) | ESC-3, UI-3 | Fake-provider voice acknowledgment passes; "Handled by" shows within 2 s; Twilio keypad still passes |
| **M3 · Set up in words** (done) | AI-6 | Draft → confirm → active rule round trip; ambiguity creates nothing |
| **M4 · Document** (done) | AI-7, PRV-3 | Report cites only real events; blurred clips are linked |
| **M5 · Design** (done) | UI-4, UI-5, UI-6 | Floor plan view, mobile acknowledge, ollo branding, skeletons |
| **M6 · Measure** (harness done) | EVAL-1 | Accuracy table on the team's staged clips, in the README. The harness is built and validated; the team's clips are still to be recorded. |
| **M7 · Demo** (script and docs done) | — | Rehearsed 2-minute script ([DEMO.md](DEMO.md)); backup video recorded (team, on site); README sponsor sections |

**Add-ons, only after M4:** DET-10 unsupervised child, SRC-4 server capture (done), ESP32 wrist buzzer as a third acknowledgment channel, and the Apify recall checker.

## Out of scope

Diagnosing choking, seizures or injury; breathing or airway monitoring; face, identity or age recognition; automatic emergency-service calls; parent mass notifications; custom model training; native mobile apps; running more than one room per server.

## Open questions

- **Q-1 (answered 2026-10-24):** Yes. Cartesia managed agents support HTTPS webhook tools with bearer authentication, and per-call `dynamic_variables` can fill tool body fields (docs.cartesia.ai/agents/webhook-tools, /agents/dynamic-variables). Still unverified with a real account: the exact agent and tool setup in the Cartesia console.
- **Q-2:** Real escalation wait times per severity, from a home daycare provider interview.
- **Q-3:** Is the Spacetime or Mana prize worth reversing D-3? Team decision.
