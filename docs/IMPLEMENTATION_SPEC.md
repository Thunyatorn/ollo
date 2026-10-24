# Daycare camera safety assistant — hackathon implementation spec

Status: implementation-ready draft, October 23, 2026. Working name: **Lookout** (placeholder, not a cleared brand name).

## 1. Product and promise

**Pitch:** Your camera shows what happened. Lookout helps a caregiver get there sooner.

Software analyzes a daycare camera feed for configured boundary crossings and experimental signs of possible distress/choking. It shows the evidence, alerts the responsible caregiver, calls a designated teammate when an alert goes unanswered, and maintains an incident timeline through acknowledgment and resolution.

Primary scenario: a toddler room in a small daycare. Bedroom/nursery use is a later configuration, not a second product to build this weekend. The prototype does not identify children, diagnose choking, monitor breathing, or establish that a room is safe. Babies remain part of the product vision, but infant distress detection is not validated by a toddler/adult demo.

## 2. Confirmed scope and choices

- Prerecorded video is the required input; browser webcam is optional after the core works.
- Real outbound calls to consenting teammates are required; simulated calls are a clearly labeled fallback.
- React + TypeScript frontend, Python backend; interchangeable vision, speech, and calling adapters.
- Deliver a local web application, a phone acknowledgment flow, a reproducible demo, measured prototype results, and sponsor submission artifacts. This document specifies implementation; it does not claim anything has been built or validated.
- No new hardware; do not promise compatibility with arbitrary proprietary camera apps. RTSP/security camera integration is a stretch adapter.

## 3. Required demo experience

Two core stories, each approximately 60–90 seconds:

### A. Observable boundary event

1. Open a staged room video marked **Recorded demo**. Show the room, recent frame age, analysis status, and assigned caregiver.
2. Enable a preconfigured doorway polygon. A tracked demo subject moves from outside to inside it.
3. A tracking box and a floating incident island appear: **Restricted area entered — check Toddler Room doorway.**
4. The primary caregiver does not acknowledge. The UI shows the backup-call countdown.
5. The designated teammate's real phone rings; a Cartesia-generated message identifies the room and asks for acknowledgment.
6. The teammate presses 1. Both desktop and mobile show who acknowledged. They then explicitly resolve the incident.
7. Open the timeline: observation, alert, call attempt, acknowledgment, resolution, evidence.

### B. Experimental possible distress

1. Play a safely staged, clearly labeled clip of a consenting adult acting a concerning gesture. Do not induce distress or stage a dangerous event with a child.
2. Analyze ordered frames; show **Possible distress / choking concern — check immediately**, together with the actual visual observations and **Airway status cannot be determined from video**.
3. Trigger the same notification/escalation workflow. Demonstrate an ordinary eating/face-touching clip that should not create an alert as a contrast.
4. State that adult simulation tests the software workflow, not pediatric clinical sensitivity. If actual analysis is unreliable, mark this branch experimental and show measured failures; do not disguise event fixtures as model inference.

Additional short scenario: video or model stops responding; the system shows **Analysis unavailable**, rather than a reassuring status.

## 4. Scope priorities

### P0 — ship these

- Video upload, playback, start/stop analysis, session reset.
- One active camera, one polygon zone, one tracked subject for the boundary demo.
- Local person tracking and rule-based zone entry.
- Experimental multi-frame distress review, with structured observations and abstention.
- Full-screen desktop video with evidence overlays and incident islands.
- Server-owned incident lifecycle and notification timers.
- Primary and backup caregiver configuration; real call to an allowlisted, consenting teammate.
- DTMF acknowledgment (press 1) or authenticated mobile acknowledgment if account restrictions block DTMF.
- Incident history, evidence stills, explicit resolution, analysis-health state.
- Clearly separated live inference, labeled cached replay, and developer fixtures.
- A small held-out evaluation set and reliable setup instructions.

### P1 — only after P0 integration passes

- Browser webcam adapter, zone drawing UI, event video clips, multi-person tracking.
- Mobile clip viewing, CSV/JSON export, additional language for call audio.
- One RTSP source through backend ingestion if a compatible camera is available.

### Out of scope

- Drowning, SIDS/apnea detection, infant sleep-position safety assessment, emotion diagnosis, abuse classification, facial recognition, identity/age inference, automatic emergency-service calls, parent mass notifications, generated first-aid instructions, custom model training, native phone apps, full daycare management.

## 5. Architecture and repository plan

Use a simple monorepo. Frontend: Vite, React, TypeScript, Tailwind, SVG overlay layer, lightweight client state. Backend: FastAPI, Pydantic, asyncio coordinator, SQLite in WAL mode, local evidence files, Anthropic SDK, Cartesia HTTP client, Twilio SDK. Local vision baseline: MediaPipe Pose Landmarker and OpenCV; smoke-test binaries and model on the actual laptop first. Pin versions after that test.

The local baseline is for a controlled, single-subject prototype, not reliable daycare age classification. A developer selects the demo subject/region; the system does not automatically decide who is a child or a caregiver. If pose tracking fails its first feasibility test, use a pretrained person detector with a simple tracker; check its model/code license before committing. Do not spend the weekend training a detector.

```text
apps/web/                  desktop, mobile route, API client, SVG overlays
services/api/              FastAPI, coordinator, SQLite, authenticated media
services/api/vision/       frame windows, local tracking, zone geometry
services/api/providers/    vision reviewer, TTS, calling adapters
contracts/                 exported JSON schemas + generated TypeScript types
fixtures/                  synthetic API events, visibly fixture-only
data/manifests/            clip metadata, rights, labels, evaluation splits
docs/                      setup, demo script, evaluation, Figma stage log
```

```text
Browser video -> timestamped sampled frames -> bounded backend ingestion
       |                                  -> local tracking -> zone rules
       |                                  -> multi-frame Claude review
       |                                                        |
       +<-- SVG overlays + server events <-- incident coordinator+
                                              |
                                   SQLite + notification outbox
                                              |
                                 Cartesia audio -> Twilio call
                                              |
                                signed callback / mobile action
                                              |
                                   acknowledgment -> UI timeline
```

Keep model requests and phone calls out of the frame-ingestion request path. One FastAPI process owns the demo coordinator; run a bounded worker pool for CPU vision. Do not run blocking decoding/inference on the async event loop. A separate durable distributed worker stack is unnecessary for this scope.

## 6. Video ingestion, timing, and overlays

### Recorded input — primary

- Accept MP4/H.264 initially; validate file type, size (proposed 100 MB), duration (proposed 5 minutes), and successful decoding. Store outside the public frontend directory.
- Browser plays the file and uses video frame callbacks where available. Sample at a proposed 4 frames/second, max width 640–960 pixels, preserving aspect ratio.
- Send a binary JPEG plus metadata through a dedicated authenticated frame WebSocket. Limit queued work to the latest frames; never let analysis lag invisibly behind playback.
- Server stores an approximately 8-second timestamped ring buffer of sampled frames. Analysis is a sampled feed, not full continuous video interpretation.
- MP4 playback stays smooth even if inference is slower. Never claim the UI playback rate is the analysis rate.
- Every frame has `session_id`, `epoch`, increasing `frame_seq`, `media_time_ms`, source width/height, and server receipt time. Source times are evidence; server monotonic time owns notification deadlines.
- Seeking, looping, changing source, or stopping creates a new epoch, clears temporal/tracking windows, and discards late inference responses. Pause marks analysis paused. Existing alert deadlines continue unless explicitly canceled or the demo session is stopped.
- Use playback rate 1x with external calls armed. Reset cancels queued calls and ends active demo calls where the provider permits it; increment epoch and invalidate all delayed jobs.

### Webcam — optional

Use `getUserMedia`, timestamp frames monotonically, reuse the same protocol. Camera permission denial must fall back to recorded upload. Stop media tracks when leaving the view.

### Drawing correctness

All boxes and polygon vertices use normalized source-image coordinates `[0,1]`. Account for letterboxing when mapping to the displayed video; use the same object-fit rectangle for SVG. Match returned overlays to source timestamp and epoch, show their age, and hide boxes older than 500 ms rather than displaying a misleading attachment. Room-level alerts remain visible. Do not mirror the evidence image without applying the same transform to coordinates.

## 7. Detection design

### A. Boundary crossing — deterministic prototype path

- Configure one room polygon and one selected subject track. Derive the track anchor from the lower bounding-box center (document that crawling/occluded subjects are harder).
- Smooth positions briefly and use polygon hysteresis to reduce boundary flicker.
- Proposed entry rule: previously outside, then inside across 3 consecutive processed frames. These are tuning defaults, not validated safety thresholds.
- If the subject first appears inside, issue a distinct **Person present in restricted area** review candidate rather than inventing a crossing.
- Loss of the selected subject means tracking uncertainty, not evidence that they left. Reset track assignment after prolonged loss; do not silently attach a new person to an old identity.
- An entry event goes directly to the coordinator; a cloud model must not delay or veto it.
- Presence of another person never automatically means adequate supervision.

### B. Possible distress/choking concern — experimental path

Use Claude vision on an ordered window of 6 frames from the most recent approximately 3 seconds, plus timestamps and room context. In the one-camera demo, review every 3 seconds, with at most one request in flight. Periodic review is required; a pose heuristic must not be the only gate, because infants or occluded subjects may not produce usable poses. Keep overall room context along with optional subject crops.

Ask for observable facts, plausible benign explanations, visibility limits, and one of `no_concern`, `possible_distress`, `insufficient_view`. Do not ask it to establish breathing, oxygenation, airway obstruction, or medical certainty. Visible concerning gestures may justify a caregiver-check alert, but their absence cannot rule out choking. A video gesture is not a clinical label.

Proposed prototype policy: a schema-valid `possible_distress` result with a visible observation creates an immediate caregiver-check incident; no additional confirmation window is required. This favors fast notification at the expense of false alerts and must be evaluated. Ordinary eating, crying, face touching, and play are explicit negative controls. Invalid output, timeout, refusal, or insufficient view is an analysis limitation, not `no_concern`.

Claude supports joint analysis of multiple images; use a model available on the team's account that supports the required schema. Configure the model ID, never invent or hardcode an unverified model. This is sampled-image reasoning, not a validated video medical detector. [Vision documentation](https://platform.claude.com/docs/en/build-with-claude/vision), [structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs).

Example provider output (not a medical probability):

```json
{
  "review_id": "rev_123",
  "session_id": "session_123",
  "epoch": 1,
  "window_start_ms": 12000,
  "window_end_ms": 15000,
  "assessment": "possible_distress",
  "observations": [
    {"frame_seq": 52, "description": "Subject holds both hands near the neck"}
  ],
  "visibility": "partial",
  "alternative_explanations": ["Gesture may be ordinary play"],
  "limitations": ["Cannot determine airway status from these images"]
}
```

The server supplies IDs/timing from its own request context, validates referenced frame IDs, bounds text lengths, and rejects invented event kinds. The model does not generate phone numbers, tool permissions, or escalation deadlines. Do not display arbitrary confidence percentages.

### C. Health state

Track video freshness and each analysis component independently: `active`, `paused`, `degraded`, `offline`. Proposed stale-frame warning at 3 seconds; cloud-review warning after 10 seconds without a valid recent result. Show last analyzed timestamp. A cloud failure can leave local zone detection active; label the loss of distress review. An empty frame or successful HTTP response does not establish healthy monitoring.

## 8. Incident coordinator and escalation

Separate lifecycle from delivery status:

- Incident: `open -> acknowledged -> resolved`, or `open -> dismissed` with reason.
- Notification attempt: `queued -> initiating -> ringing -> answered -> completed`, with `busy`, `no_answer`, `failed`, `canceled`, and `unknown` terminal/exception states as appropriate.
- A completed/answered call is not acknowledgment. Only a valid button action or DTMF 1 marks acknowledgment. Acknowledgment means someone accepted responsibility, not that the subject is safe. Resolution is explicit.

Suggested demo policy (configurable, not a clinical response standard):

1. At incident creation, immediately show a persistent desktop and connected-mobile alert. Sound requires the user to enable audio in the browser beforehand.
2. If unacknowledged after 8 seconds, call the primary configured teammate.
3. After failed/no-answer/no-acknowledgment, call the backup once; also enforce an overall 30-second deadline for moving to backup, canceling the primary attempt if necessary.
4. After the backup attempt ends without acknowledgment, show **No responder confirmed — check immediately** and keep the incident open. No unlimited dialing, no emergency-service numbers, no inferred contacts.
5. Acknowledgment cancels all unsent escalation jobs and attempts to terminate other active calls. Keep cancellation failures visible.

Create one active incident per camera/session/event family/subject, merging new observations. For the single-subject MVP, distress is room-level and may use a null subject ID. Use a 30-second duplicate window; a higher-priority new event still alerts. Suppress repeated dialing for the same ongoing condition; require condition clear for 5 seconds plus a new onset to reopen a resolved episode. Persist dismissed/resolved episode state so the next frame cannot recreate it immediately.

Use an SQLite transaction for every state transition. An outbox item and its incident change commit together. Unique key `(incident_id, escalation_step)` prevents duplicate call scheduling. Lock/CAS claim jobs, recheck incident state immediately before provider calls, and process webhooks idempotently. Provider timeouts can leave an unknown call outcome: do not blindly retry a create-call request; reconcile provider state or flag for operator review. On restart, restore overdue jobs, never reset timers, and default real-call arming off until the operator reviews pending attempts.

## 9. Phone integration

Default implementation: Cartesia generates a short WAV message; Twilio places the call and plays it inside a DTMF `<Gather>`. Store the audio behind a short-lived, unguessable media token usable by Twilio. Never put child imagery on a public audio endpoint.

Call script, populated from trusted room/event fields:

> This is a Lookout demo alert for Toddler Room. Possible distress was observed. Please check the room immediately. Press 1 to acknowledge, or 2 if you cannot respond.

Boundary calls substitute the observed boundary event. Keep the message short, factual, and free of child names or medical instructions. Press 2 advances to backup; timeout or voicemail never counts as acknowledgment. Do not record calls in the MVP. Conversational speech handling is a stretch feature; fixed keypad acknowledgment is easier to verify.

- Validate provider webhook signatures against the exact external URL and payload; map callback CallSid to the stored attempt. Never accept a caller-supplied incident ID as authority.
- Webhook replay must not produce a second transition or a new call. Do not regress terminal delivery states when callbacks arrive out of order.
- Place real calls only to a backend-maintained E.164 allowlist of consenting teammates. Explicitly arm calls per session. Rate-limit to at most two attempts per incident and six attempts per session by default; an operator can reset the session budget intentionally.
- A reachable HTTPS callback/audio route is required. Use a narrow tunnel for Twilio routes or deploy the API; protect every other route. Test venue Wi-Fi and mobile connectivity early.
- Twilio's current trial documentation limits calls to verified numbers and describes custom-TwiML/API restrictions. Verify both teammates and test the exact Play/Gather workflow in the actual account before relying on it. Do not assume a fixed free balance or that all trial accounts behave identically. [Voice trial](https://www.twilio.com/docs/usage/trials/try-out-voice), [Gather](https://www.twilio.com/docs/voice/twiml/gather).
- If the account blocks custom outbound playback, investigate Cartesia managed outbound calling or a funded Twilio account; do not spend more than 90 minutes on telephony setup before preserving a labeled simulation fallback. These are account/budget decisions, not confirmed free entitlements.

## 10. Desktop and phone interface

### Desktop — video first, floating islands

Design at 1440×900, usable at 1280×720. Near-full viewport video on a neutral dark background. Compact header for room/source selection and history. Keep the center clear; anchor islands to video corners, not arbitrarily moving positions over people.

- **Top left, source island:** room, Recorded demo / Live webcam badge, playback state, last-frame age, separate tracking and AI-review health. Say **Monitoring active**, never **All children safe**.
- **Top right, caregiver island:** primary/backup initials and roles, acknowledgment state, real-calls armed badge. Hide phone digits except optional last four.
- **On-video evidence:** selected subject box and optional doorway polygon. A concerning event can highlight the associated region only when localization exists; never invent a precise box from text-only model output.
- **Bottom left, observation island:** brief observable facts, latest analysis timestamp, expandable evidence/limitations. No rolling chain-of-thought or fabricated reasoning stream.
- **Bottom center/right, incident island:** event title, room, detected-at time, **Check room**, **Acknowledge**, **Cannot respond**, **Resolve** after acknowledgment, and **Dismiss** with reason. Show call countdown and live delivery state beneath the main action. Use text/icons as well as color.
- **History drawer:** timestamped incidents, short summary, stills/clip where available, delivery attempts and outcomes. Keep history out of the primary video during an active alert.
- **Developer drawer:** scenario selector, reset, model timings, calls arming, fixture injection. Close during pitch; injected results must keep a visible Fixture badge.

Calm monitoring uses restrained neutral surfaces; alerts have clear contrast and priority, no decorative pulsing. Islands must not hide the doorway/subject; allow collapse/reposition and keyboard access. At narrow widths, move islands below video instead of obscuring it. Provide readable text, visible focus, and touch targets around 44 px.

### Mobile companion

Responsive `/respond/:incidentId` route with room, event, observation time, evidence still, and large acknowledgment/cannot-respond controls. A per-caregiver session or scoped expiring action token authorizes actions; read-only links must not mutate state. Avoid SMS as a P0 dependency: open the route via a paired QR code before the demo. A WebSocket updates the open mobile view; this is not background mobile push. A real call reaches a locked phone; an open mobile page does not prove background notification support.

## 11. Data contracts and API surface

Pydantic is the source of truth; export JSON Schema and generate TypeScript types before independent UI/backend work.

Core entities:

- `Session`: id, epoch, source type, source metadata, status, policy version, calls_armed.
- `Camera`: id, room label, current health, last-frame time, last-review time.
- `Zone`: camera, normalized vertices, enabled, rule configuration.
- `Caregiver`: id, display name, role, phone secret reference, consent/verification state; phone never returned in ordinary API responses.
- `Observation`: id, source window/frame references, event family, track id nullable, visible facts, limitations, origin (`local_rule`, `model`, `fixture`, `cached_replay`), model/prompt version.
- `Incident`: id, session/epoch, camera, kind, priority, lifecycle, observations, opened/acknowledged/resolved times, assigned responder, revision.
- `NotificationAttempt`: id, incident, step, recipient id, provider id, delivery state, timestamps, error code.
- `AuditEvent`: id, increasing sequence, actor, event type, server timestamp, media time nullable, payload.

Minimum endpoints:

```text
POST /api/sessions                    create session, return upload capability
POST /api/sessions/{id}/video         bounded validated upload
POST /api/sessions/{id}/start          start epoch
POST /api/sessions/{id}/stop           stop, cancel jobs/calls
POST /api/sessions/{id}/reset          clear demo state, new epoch, disarm calls
PUT  /api/cameras/{id}/zone            normalized polygon
PUT  /api/caregivers                  admin-only allowlisted demo contacts
POST /api/sessions/{id}/arm-calls      explicit operator action
GET  /api/state                       current snapshot + latest audit sequence
GET  /api/incidents/{id}               incident, evidence, delivery history
POST /api/incidents/{id}/acknowledge   authenticated actor, idempotency key
POST /api/incidents/{id}/decline       route to backup
POST /api/incidents/{id}/resolve       explicit reviewed outcome
POST /api/incidents/{id}/dismiss       required reason
GET  /api/media/{id}                  authorized evidence/video
WS   /api/frames/{sessionId}          binary frames + metadata
WS   /api/events                      sequenced state updates
POST /webhooks/twilio/status          signed provider delivery callbacks
POST /webhooks/twilio/digits          signed DTMF callback
GET  /call-media/{token}              short-lived audio only
GET  /health                          process health; not scene safety
```

All mutation responses return the new revision; conflicting resolution actions return 409 with current state. WebSocket envelopes include version, event id/sequence, session, epoch, server timestamp, source timestamp where relevant, and typed payload. Reconnecting clients load a snapshot then apply only newer events, ignoring duplicates. Server status and timers always override frontend countdowns.

## 12. Data sources and footage plan

### Primary demo/test material — create a small controlled set

Use consenting adult teammates acting benign gestures and moving through room boundaries; use mannequins only as explicitly nonrepresentative UI fixtures. Obtain rights-cleared toddler footage only if already available with appropriate permission; it is not a prerequisite for building. Do not scrape private daycare feeds or videos of actual child emergencies. Never manufacture a real choking or breathing event.

Proposed minimum corpus: 20 development clips plus 10 held-out clips, 15–30 seconds each, and at least 15 minutes of ordinary activity for false-alert observation. Include boundary entries/nonentries, ordinary eating, face touching, reaching, play, partial occlusion, empty room, low light, camera movement, and safely acted concerning gestures. Held-out footage must use different takes, not neighboring frames from the same original take. Adult results remain adult simulation results.

Manifest fields: clip ID, source URL/owner, permission and license, allowed use (analysis/display/redistribution/cloud upload), subject age category if actually known, simulation flag, scenario, onset/end timestamps, expected observable event, uncertainty, split, annotator notes. Two teammates label independently and reconcile disagreement. Labels describe the scene, not a medical diagnosis. Keep raw media outside Git and never publish footage based solely on a dataset paper's license.

### Research leads — inspect, do not make them critical dependencies

- **KidRisk:** research benchmark for children's activities/hazard recognition; potentially useful for understanding task design and failure modes. Dataset access, clip permissions, infant/toddler coverage, and choking labels were not verified. The paper's publication license does not establish rights to redistribute its underlying video. Its published benchmark performance is not evidence for our system. [Paper](https://arxiv.org/abs/2606.25298).
- **KS–KSS:** child/adult action-recognition resource containing ordinary actions. Useful for studying pose and age-domain differences, not a choking benchmark. Clear demo/commercial permissions were not established in the reviewed repository; inspect original video rights separately. [Repository](https://github.com/sankamohotttala/KS-KSS-Dataset).
- **MediaPipe Pose Landmarker:** pretrained pose extraction for prototype tracking and optional gesture features; does not supply a distress diagnosis or guarantee infant accuracy. [Official guide](https://developers.google.com/edge/mediapipe/solutions/vision/pose_landmarker/python).
- **Red Cross child/infant choking guidance:** reference for careful wording and the limits of visible signs; not a model-training label source or a basis for generated treatment instructions. [Child](https://www.redcross.org/take-a-class/resources/learn-first-aid/adult-child-choking), [infant](https://www.redcross.org/take-a-class/resources/learn-first-aid/infant-choking).

Do not download a giant generic action dataset or fine-tune a video model during the hackathon. No verified open, licensed infant/toddler choking dataset was identified in this research; that remains a deployment blocker for making clinical detection claims, not a blocker for the prototype workflow.

## 13. Sponsor credits and service choices

Offer evidence comes from the saved October 15/22 organizer emails and briefing; no accounts were registered or offers redeemed. Booth/account verification is still needed.

### Claim first

- **Cartesia — free booth credits, amount unspecified.** Directly useful for spoken caregiver alerts and calls. Ask for API credit balance, supported voice/model, expiry, and whether telephony minutes/numbers are included; do not assume TTS credits cover carrier charges. [Saved offer](emails/2026-10-15-cal-hacks-13-0-pre-event-details-2.md), [TTS API](https://docs.cartesia.ai/api-reference/tts/bytes).
- **Figma Education — student access advertised; verification required.** Useful for interface design, handoff, stage log and Figma Slides. AI usage is not established as unlimited. [Saved offer](emails/2026-10-15-cal-hacks-13-0-pre-event-details-2.md).
- **Anthropic — ask booth about event API access.** No attendee API credit amount verified in the saved materials. The $5,000 Claude-credit award and Max subscription are winner benefits, not the build budget. A consumer subscription is not a presumed API balance. [Sponsor email](emails/2026-10-21-cal-hacks-13-0-meet-anthropic.md).

### Useful optional offers

- **Mana — three months Pro for participating teams using Mana.** Useful for prototyping/build collaboration if desired; API access for continuous video analysis is not established. Keep off the runtime dependency path until confirmed. [Saved offer](emails/2026-10-22-cal-hacks-13-0-pre-event-details-3.md).
- **SpaceXAI — one-month advertised bundle.** Potential development assistance; does not establish free Grok inference/API quota. Ask the booth about actual activation and included tiers. [Saved offer](emails/2026-10-15-cal-hacks-13-0-pre-event-details-2.md).
- **Vultr — free cloud-credit lead from earlier MLH inventory.** Could host API/callbacks if account setup is quick; amount, eligibility, and GPU availability are unverified. Local processing is the baseline. [Inventory](CALHACKS_13_AWARDS.md).
- **Notability — one month Pro, code CALHACKS.** Optional notes/process documentation, not infrastructure. [Saved offer](emails/2026-10-15-cal-hacks-13-0-pre-event-details-2.md).

### Available but not central

- **Apify — $200 advertised credits**, signup [coupon link](https://console.apify.com/sign-up?couponId=APIFY_CAL_HACKS) or `APIFY_CAL_HACKS` under Billing → Subscription. Could collect approved public resource pages for an offline reference pack; it does not provide camera inference or footage rights. Do not add scraping just to chase a track. [Saved offer](emails/2026-10-15-cal-hacks-13-0-pre-event-details-2.md).
- **Wajo/Fo — event access**, no confirmed free calling balance. Not a substitute for a verified telephony account. [Saved offer](emails/2026-10-22-meet-fo-wajo-s-ai-assistant-that-gets-things-done.md).
- **Twilio — general free trial, not a confirmed Cal Hacks sponsor perk.** Verify exact account capabilities as described above. No promised dollar balance.

Budget controls: request-count and token-usage logging, configurable model concurrency, approximately 20 review requests/minute at the proposed cadence, explicit session request ceiling (start at 200), and provider spending limits where available. Six images/request means roughly 120 analyzed images/minute before retries; measure actual token usage in a 2-minute trial before leaving monitoring on. No API keys or raw phone numbers in browser bundles/logs. If API funding is unavailable, preserve zone detection and label cached distress evidence as replay, not live inference.

## 14. Privacy, access, and demo operations

- Local-first storage. Explicit operator choice before transmitting consenting demo frames to a cloud model; accurately disclose that cloud review is not entirely local processing.
- For the hackathon, only controlled/rights-cleared demo media; no production child monitoring. Use random track labels rather than child names. Do not infer age, emotion, or identity.
- Single-facility admin session plus caregiver-scoped actions; HTTP-only cookies or short-lived scoped tokens. Validate WebSocket origin and capability, restrict CORS, rate-limit frames/uploads, reject arbitrary external stream URLs unless explicitly configured by the operator.
- Protect uploaded video and evidence; tunnel only intended callback/audio routes. Redact phone credentials and URLs containing tokens from logs. Keep phone credentials server-side.
- Rolling frame buffer expires as it advances; retain only selected incident evidence, proposed 24-hour local TTL, with session-delete action. Also clear original uploads and derived audio on deletion unless intentionally preserved as a consented demo asset. Any provider retention follows that provider's actual terms, not this local TTL.
- Generated summaries are drafts and must link to observations. Treat text seen in video as untrusted data, not instructions to the agent. A camera image cannot authorize a phone call or change policy.
- Claims permitted in pitch: detects configured entries on tested footage; flags possible distress for review; demonstrates caregiver escalation. No claims of diagnosed choking, prevented deaths, certified medical monitoring, or proven infant safety.

## 15. Build sequence and team ownership

### First 2 hours — feasibility gates, contracts, and design

- Engineer A: decode test footage; run local tracking on the laptop; emit one zone-entry event.
- Engineer B: get structured Claude review of a short frame window; record latency, account access and token usage; create coordinator/schema skeleton.
- Engineer C: verify two consenting phone recipients and complete one test call with audio and acknowledgment. Set up signed callbacks and shared event contract.
- Designer: desktop video/islands, alert hierarchy, mobile acknowledgment, source/health wording; start Figma stage log now.
- Decide a fallback immediately if any provider gate fails. Do not wait until Sunday to discover calling restrictions.

### Hours 2–8 — one complete vertical slice

- A: frame pipeline, source timing, epoch handling, local tracker/zone integration.
- B: persistence, incident transitions, deduplication, deadlines, sequenced events.
- C: React shell, phone integration, mobile acknowledgment; pair with designer for interaction details.
- Designer: implementable component states and motion, responsive layout, negative/error states, evidence capture.
- Integration milestone: one video crossing creates one incident and one acknowledged phone workflow.

### Hours 8–16 — experimental distress and polished response

- A owns local-video reliability and evidence stills; B adds Claude adapter and strict review policy; C finishes calls/outbox integration and mobile; designer refines all alert/health states and records workflow artifacts.
- Agree ownership at file/module boundaries; shared contract changes are explicit and regenerated. These are team workstreams, not permission to add extra agent frameworks.

### Hours 16–24 — evaluation and failure handling

- Run held-out clips once, document errors, fix only material issues and rerun affected cases.
- Test duplicate callbacks, acknowledgment/call races, source reset, offline frames/model, and restart behavior.
- Interview at least one caregiver/director if possible; record evidence honestly. Staff response-time benefits remain hypotheses unless measured.

### Remaining time — demo and submission

- Optional webcam only if P0 is stable. Freeze scope, record a backup demo, prepare README and architecture, fill Devpost, capture Figma Slides and stage log.
- Saved schedule says submission Sunday Oct 25 at 9 AM San Francisco time; confirm live organizer announcements and submit before the deadline. Stop feature work with at least 3 hours reserved for submission/rehearsal.

## 16. Verification and acceptance

Targets below are engineering goals on controlled test footage, not achieved results or real-world guarantees.

- Video plays at normal speed; overlays align across resize/letterboxing, seek/reset never applies an old result to a new scene.
- Boundary incident appears within a proposed 2 seconds of labeled entry on the test workstation. Report p50/p95 and the sample count rather than hiding failures.
- Distress pathway reports actual window collection + request + coordinator latency; initial goal is under 10 seconds on test clips. Missing that target is reported; it is not evidence of timely emergency detection.
- Report boundary event recall, experimental concern recall on acted clips, false incidents per camera-hour, and per-class confusion counts separately. Include negative footage hours and clip count; a tiny test set does not establish deployment accuracy.
- Duplicate/reordered frame messages and provider callbacks never produce extra calls or regress incident state.
- Concurrent phone/mobile acknowledgments select one first responder transactionally and cancel future attempts.
- Provider create timeout yields an unknown-attempt state rather than an automatic duplicate call.
- Camera/model failure produces a visible limitation; no `safe` state is inferred.
- A real teammate call plays correct room/event audio and press 1 updates both screens. Answering without pressing 1 never acknowledges.
- Reset disarms calls and invalidates delayed model results/jobs; old calls/callbacks cannot acknowledge a new session.
- Media requires authorization; provider callbacks fail signature verification when forged; phone destinations cannot be model-generated or browser-overridden.
- Developer fixture and cached replay badges are always visible; recorded video is never labeled live camera.

Required automated checks: zone geometry/hysteresis, epoch/stale-frame rejection, model schema/abstention handling, incident merging/reopening, durable deadline restoration, exactly-once job claim within our process, callback idempotency/order handling, acknowledgment races, allowlist enforcement, and evidence authorization. One end-to-end UI test covers upload → incident → simulated provider callback → acknowledgment → resolution; conduct a separate manual real-call smoke test.

## 17. Awards and submission evidence

- **Microsoft:** primary target; demonstrate the full operational workflow, measured prototype behavior, deployment constraints, and customer understanding.
- **Anthropic:** primary if Claude is meaningful in the running product; name the daycare community, show a real problem, working capability, and known failure modes.
- **People-First Social Impact:** show how staff gain earlier awareness without overstating child-safety outcomes.
- **Cartesia:** spoken escalation is central; include working call/audio evidence, setup, and limits.
- **Figma:** keep workflow/stage-log artifacts, use Figma Slides, and prepare required ≤3-minute demo with embedded prototype/Make evidence. Current source conflicts are recorded in the briefing.
- Confirm category limits and award stacking onsite. No runtime provider should be added solely for another award.

## 18. Remaining setup decisions — nonblocking defaults

- Final product name and visual style: designer chooses; Lookout is a placeholder.
- Actual API credentials/model IDs, Cartesia voice, verified phone numbers: engineers supply through environment configuration; never collect secrets in the spec.
- Demo media rights: start with consenting adult simulations; authentic infant/toddler data remains unverified.
- Runtime hardware: benchmark the actual laptop first; no GPU dependency assumed.
- Call timer tuning: use the demo values above; do not present them as medically appropriate thresholds.
- Environment keys to document in `.env.example`: `ANTHROPIC_API_KEY`, `VISION_MODEL`, `CARTESIA_API_KEY`, `CARTESIA_MODEL_ID`, `CARTESIA_VERSION`, `CARTESIA_VOICE_ID`, `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`, `PUBLIC_CALLBACK_BASE_URL`, `APP_SESSION_SECRET`, `CALL_ALLOWLIST`, `CALLS_ENABLED=false`, `DATA_DIR`, `MAX_MODEL_REQUESTS_PER_SESSION`.

## 19. Source and offer status

Technical/data references were checked October 23, 2026. Sponsor offers are organizer-email evidence saved October 22; balances and redemption were not verified in provider accounts. Start from [the briefing](CALHACKS_13_BRIEFING.md), [saved emails](emails/README.md), and [Figma brief](sources/figma-track-brief.txt). No software was implemented, no footage was downloaded, and no phone calls or registrations were made while preparing this specification.
