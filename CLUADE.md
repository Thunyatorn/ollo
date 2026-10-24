# NestWatch Component Spec

Oct 23, 2026 · @Thunyatorn Jirachaisri

## Overview

NestWatch has seven components in three places: two at the daycare (the vision service and the wrist buzzer), two in the cloud (Spacetime and the worker service), two apps (dashboard and phone), plus outside services reached only through the worker.

&#91;embedded content: component map · 7 components, 16 links\]

Numbers on the lines match the Connections table below. Only the worker reaches outside services, and video never leaves the daycare.

| Component | Runs on | Built with | Owner on the team |
| --- | --- | --- | --- |
| Vision service | Local computer at the daycare | Python, OpenCV, Ultralytics pose model, NumPy, SciPy, Shapely | Vision engineer |
| Wrist buzzer | Caregiver's wrist | ESP32, vibration motor, button, battery | Hardware |
| Spacetime backend | Spacetime Maincloud | Spacetime module (TypeScript, Rust or C#) | Backend engineer |
| Worker service | Cloud host or the demo laptop | Node or Python | Backend engineer |
| Caregiver dashboard | Browser | React, Vite, TypeScript, Spacetime client | Frontend engineer |
| Phone app | Caregiver's phone browser | React PWA, Spacetime client | Frontend engineer |
| Outside services | Internet | Claude API, Cartesia, Twilio, Moss, Apify | Worker owner |

**Three rules tie the components together:**

1. **Spacetime is the only place alert state changes.** Screens, the buzzer and the phone call all write through it, so they never disagree.
2. **API keys live only in the worker.** Browsers, phones and the buzzer never call Claude, Cartesia or Twilio directly.
3. **Video stays local.** Only positions, events and blurred key frames leave the daycare.

## Vision service

The vision service turns camera video into positions and events, runs on the local computer at the daycare, and is the only component that ever sees raw video.

**What it does, in order, every frame:**

1. **Read frames** from each camera (USB webcam, phone camera, or IP camera over RTSP) at 15–30 frames per second.
2. **Detect people** with a pretrained pose model, returning a box and 17 keypoints per person.
3. **Map feet to the floor** using the homography H from calibration, giving each person a position in meters on the floor plan.
4. **Track** each person with a constant-velocity Kalman filter, matching detections to tracks with the Hungarian algorithm.
5. **Label adults and children** using the adult tags set on the dashboard at the start of the day.
6. **Score evidence** per child and zone (inside, or predicted entry under 3 s), and run CUSUM.
7. **Run detectors** for falls, climbing, prolonged stillness, unsupervised children and possible distress.
8. **Fire events** when CUSUM crosses its threshold and the child-zone pair is not cooling down.
9. **Save evidence**: blur faces (a box around the head keypoints), then save a short clip and two or three key frames locally.

**Internal modules:**

| Module | Responsibility |
| --- | --- |
| `capture` | One reader thread per camera; drops old frames so processing never falls behind |
| `pose` | Runs the pose model; returns boxes and keypoints |
| `calibration` | Stores and applies H per camera; recomputes H from four clicked points |
| `tracker` | Kalman filters, Hungarian matching, track birth and death, adult tags |
| `zones` | Caches active zones and schedules from Spacetime; point-in-polygon and distance checks |
| `detectors` | Zone prediction, CUSUM, fall, climbing, stillness, unsupervised, distress |
| `evidence` | Face blurring, clip and key-frame saving, clip retention |
| `sync` | Spacetime client: writes positions and events, subscribes to zones and alerts |
| `local_api` | HTTP and WebSocket server on the local network |
| `alarm` | Plays the local alarm through the computer's speaker |

**Inputs:**

- Video from cameras
- From Spacetime (subscription): zones, schedules, calibration settings, adult tags, open alerts and their owners
- From the dashboard (local HTTP): calibration points, adult tag taps
- From the wrist buzzer (local WebSocket): acknowledgment taps

**Outputs:**

- To Spacetime: child positions about 5–10 times a second, events when detectors fire, buzzer acknowledgments, camera health
- To the wrist buzzer: "buzz" and "stop" commands
- To the dashboard (local HTTP): camera snapshots, blurred clips and key frames
- To the speaker: the local alarm

**Local endpoints (local network only):**

| Endpoint | Method | Purpose |
| --- | --- | --- |
| `/snapshot/{camera_id}` | GET | Latest still frame for calibration and zone drawing |
| `/calibrate/{camera_id}` | POST | Four image points and four floor points; returns the new H and a reprojection error |
| `/tag-adult` | POST | Marks a track ID as an adult and names the caregiver |
| `/clips/{event_id}` | GET | Blurred clip for an event |
| `/keyframes/{event_id}/{n}` | GET | Blurred key frame n for an event |
| `/health` | GET | Cameras, frame rate, model status, Spacetime connection |
| `/buzzer` | WebSocket | Connection for wrist buzzers |

## Wrist buzzer and local alarm

The wrist buzzer is deliberately simple: it vibrates when told to and reports a tap, and it talks only to the vision service on the local network, so it keeps working even if the internet drops.

**Hardware:**

- ESP32 board with Wi-Fi
- Small vibration motor driven through a transistor
- One large button for acknowledging
- A small LED for status (connected, alert, low battery)
- Battery and a wrist strap or case

**Behavior:**

| State | Vibration | LED | Tap does |
| --- | --- | --- | --- |
| Idle | Off | Slow green blink | Nothing |
| High alert | Long pulses, repeating | Fast orange | Acknowledges the alert |
| Medium alert | Short pulses, repeating | Slow orange | Acknowledges the alert |
| Alert owned by someone else | Stops | Green | Nothing |
| Disconnected | One long buzz, then off | Red | Retries the connection |

**Protocol:** a WebSocket connection to the vision service's `/buzzer` endpoint, with small JSON messages.

```json
{"type": "hello", "buzzer_id": "buzzer-maria", "battery": 0.82}
{"type": "buzz", "alert_id": "a_1042", "severity": "high"}
{"type": "ack", "buzzer_id": "buzzer-maria", "alert_id": "a_1042"}
{"type": "stop", "alert_id": "a_1042", "owner": "Maria"}
{"type": "ping"}
```

Each buzzer is paired with one caregiver in Spacetime (`caregiver.buzzer_id`). The vision service forwards an "ack" to Spacetime as `acknowledge_alert`, and sends "stop" to every buzzer once the alert has an owner.

**Local alarm:** the vision service plays a loud sound through the computer's speaker when an alert reaches the "unanswered" state, or when a high alert fires while the internet is down.

## Spacetime backend

Spacetime holds every piece of shared state and is the only component allowed to change an alert's status, owner or escalation level. Every other component either subscribes to its tables or calls its server functions.

### Tables

| Table | Key fields | Written by | Read by |
| --- | --- | --- | --- |
| `room` | id, name, width\_m, height\_m, floor\_plan | Dashboard (setup) | All |
| `camera` | id, room\_id, name, homography (9 numbers), blind\_spots, status, last\_seen | Vision service, dashboard | All |
| `caregiver` | id, name, role (primary, backup, staff), phone, buzzer\_id, on\_duty | Dashboard | All; phone numbers readable only by the worker |
| `zone` | id, room\_id, name, polygon (meters), severity, schedule, status (draft, active, off), confirmed\_by | Dashboard, worker (drafts only) | All |
| `track_position` | track\_id, room\_id, kind (child, adult), label, x, y, vx, vy, visible, updated\_at | Vision service | Dashboard, phone app |
| `alert` | id, track\_id, event\_type, zone\_id, severity, status, created\_at, predicted\_entry\_s, owner\_id, acked\_at, escalation\_level, next\_escalation\_at, closed\_at, urgency\_note | Server functions only | All |
| `incident_event` | id, alert\_id, at, kind, text, clip\_ref | Server functions | Worker, apps |
| `call_job` | id, alert\_id, caregiver\_id, attempt, status (queued, ringing, answered, failed) | Server functions, worker | Worker, apps |
| `report` | id, alert\_id, summary, lines, caregiver\_note, status (draft, final) | Worker, apps (note only) | Apps |
| `recall_match` | id, product, recall\_title, recall\_url, confidence, status | Worker | Apps |

One row per track in `track_position`, updated in place, keeps the table small no matter how long the day runs.

### Alert status values

`open` → `notified` → `escalated` → `unanswered` → `owned` → `closed` → `reported`

An alert jumps to `owned` from `notified`, `escalated` or `unanswered` as soon as someone acknowledges it.

### Server functions

| Function | Called by | What it does |
| --- | --- | --- |
| `update_positions(room_id, positions[])` | Vision service | Upserts track rows; marks missing tracks not visible |
| `report_event(track_id, event_type, zone_id, severity, predicted_entry_s, clip_ref)` | Vision service | Reuses an open alert for the same child and zone, or creates one; logs an incident event; sets `next_escalation_at` from the severity timeout; status becomes `notified` |
| `acknowledge_alert(alert_id, caregiver_id, via)` | Vision service (buzzer), apps, worker (phone) | If the alert has no owner, sets owner and `acked_at`, cancels pending calls, status `owned`; otherwise returns the current owner |
| `escalate(alert_id)` | Timer | Level 1: queue a `call_job` for the backup, status `escalated`. Level 2: queue a second call, status `unanswered`, which triggers the local alarm and notifies all staff |
| `close_alert(alert_id, reason)` | Vision service, apps | Requires an owner; status `closed`; the worker then writes the report |
| `set_urgency(alert_id, note, lower_to)` | Worker | Allowed only for medium and low alerts, and only downward; never touches high alerts |
| `save_report(alert_id, summary, lines[])` | Worker | Stores the draft report; status `reported` |
| `add_caregiver_note(report_id, text)` | Apps | Adds the caregiver's own words |
| `save_zone_draft(...)`, `confirm_zone(zone_id)`, `update_zone(...)` | Worker (drafts), dashboard and phone (confirm, edit) | Drafts stay inactive until a person confirms |
| `tag_adult(track_id, caregiver_id)` | Vision service | Marks a track as an adult |
| `update_call_job(job_id, status)` | Worker | Records ringing, answered or failed |
| `camera_health(camera_id, status)` | Vision service | Online, offline, low frame rate |

**Identity checks:** each function checks who is calling. Only the vision service may write positions and events, only the worker may write reports, urgency and call results, and only signed-in caregivers may acknowledge, confirm zones and add notes.

### Escalation timer

Use Spacetime's built-in scheduling to run `escalate` at `next_escalation_at`. If scheduling isn't available in your SDK version, the worker checks open alerts once a second and calls `escalate` when the time passes.

| Severity | First timeout | Second timeout |
| --- | --- | --- |
| High | 20 s | 30 s after the first call |
| Medium | 45 s | 60 s after the first call |
| Low | None (app only) | None |

### Subscriptions

| Client | Subscribes to |
| --- | --- |
| Vision service | `zone`, `camera`, `caregiver` (buzzer pairing), open `alert` rows |
| Worker | `alert` status changes, `call_job` where queued, `zone` drafts, `caregiver` |
| Dashboard | `room`, `camera`, `zone`, `track_position`, `alert`, today's `incident_event` |
| Phone app | Open `alert` rows, the signed-in caregiver's row, `report` |

## Worker service

The worker is the only component that holds API keys and talks to outside services. It reacts to changes in Spacetime, does slow work in the background, and writes results back through server functions, so it never delays an alert.

### Jobs

| Job | Trigger | Steps | Writes back |
| --- | --- | --- | --- |
| **Escalation call** | A `call_job` row with status queued | 1. Build the message text from the alert. 2. Generate speech with Cartesia. 3. Place the call with Twilio, playing the audio and listening for a key press. 4. Track the call status | `update_call_job`; `acknowledge_alert` when the backup presses 1 |
| **Second opinion** | A new medium or low alert | 1. Collect the alert, recent events and the blurred key frames the vision service sent. 2. Ask Claude with a 5-second limit. 3. Ignore the answer if it is late | `set_urgency` (lowering only) |
| **Incident report** | Alert status becomes closed | 1. Read the alert and all its incident events. 2. Ask Claude for a summary and timeline. 3. Check every line cites a real event ID; drop any line that doesn't | `save_report` |
| **Rule interpretation** | `POST /rules/interpret` from an app | 1. Send the text plus the room's named areas to Claude. 2. Receive a structured zone draft. 3. If no named area fits, return "needs drawing" | `save_zone_draft` |
| **Daily summary** | Closing time each day | Summarize the day's events for the director | `save_report` with type daily |
| **Recall check** (add-on) | Once a day | Run the Apify Actor, then match results against the daycare's inventory list (add an `inventory_item` table if you build this) | `recall_match` rows |
| **Escalation fallback** | Every second, only if Spacetime scheduling isn't used | Call `escalate` for alerts past `next_escalation_at` | Through `escalate` |

### Endpoints

| Endpoint | Caller | Purpose |
| --- | --- | --- |
| `POST /rules/interpret` | Dashboard, phone app | Plain-language rule to a zone draft |
| `POST /keyframes` | Vision service | Upload blurred key frames for an event; kept for 24 hours |
| `GET /audio/{job_id}` | Twilio | The Cartesia audio for a call |
| `POST /twilio/voice` | Twilio | Call instructions: play the audio, wait for one key press |
| `POST /twilio/gather` | Twilio | The key the backup pressed; 1 acknowledges |
| `POST /twilio/status` | Twilio | Ringing, answered, failed, no answer |
| `GET /health` | Monitoring | Connections to Spacetime, Claude, Cartesia and Twilio |

Twilio webhooks are checked with Twilio's request signature, and the app endpoints require a signed-in caregiver.

### Claude tools

Claude is called with tools whose outputs are structured, so the worker can check them before writing anything.

| Tool | Used in | Output fields | Checks before writing |
| --- | --- | --- | --- |
| `give_second_opinion` | Second opinion | verdict (confirm, lower, unsure), lower\_to, reason | Only for medium and low; lower\_to must be lower than the current severity |
| `draft_zone_rule` | Rule interpretation | area\_name, schedule, severity, escalation, needs\_drawing, question | area\_name must exist in the room; the draft is always inactive |
| `write_incident_report` | Incident report | summary, lines (each with event\_id and text) | Every event\_id must exist for this alert |

**Voice replies (optional, Moss):** the key press always works. If time allows, add spoken replies ("I'm on it") by sending the call audio to a Moss voice agent, which calls `acknowledge_alert` when it hears a clear yes.

## Caregiver dashboard

The dashboard is the room view on a laptop or tablet: it shows where everyone is, what needs attention and who is handling it, and it's where the provider sets up cameras and zones.

### Screens

| Screen | Route | What it shows | What the user can do |
| --- | --- | --- | --- |
| Room view | `/` | Live floor plan (zones, children as numbers, adults, blind spots, predicted path), the active alert card with escalation steps, today's events, camera status, head count | Press "I'm on it", view a clip, open a report, tap a person to tag them as an adult |
| Setup | `/setup` | Camera snapshots, the floor plan, existing zones | Click four floor points per camera, draw zone polygons, set name, severity and schedule, mark named areas |
| Rules | `/rules` | Active and draft rules | Describe a rule in plain words, confirm or adjust a draft, turn rules off |
| Reports | `/reports` | Incident reports and daily summaries | Read, add a note, share, print to PDF |
| Caregivers | `/caregivers` | Caregivers, roles, phone numbers, paired buzzers | Add caregivers, set primary and backup, pair a buzzer |

### Reads and writes

| Data | Source | How |
| --- | --- | --- |
| Positions, alerts, zones, cameras, today's events | Spacetime | Subscriptions, updated live |
| Snapshots, clips, key frames | Vision service | Local HTTP on the daycare network |
| Acknowledge, close alert, confirm zone, edit zone, caregiver note | Spacetime | Server function calls |
| Calibration points, adult tags | Vision service | Local HTTP |
| Rule text | Worker | `POST /rules/interpret` |

### Rendering the floor plan

Draw the floor plan as an SVG whose coordinates are meters (for a 4 × 3 m room, `viewBox="0 0 4 3"`), so positions from Spacetime need no conversion. Move dots with a short CSS transition (about 150 ms) so they glide between the 5–10 updates a second.

## Phone app

The phone app is the caregiver's pocket view, built as a mobile web app (PWA): it takes over the screen when an alert needs them, lets them set rules by typing or speaking, and shows reports.

### Screens

| Screen | Route | What it shows | What the user can do |
| --- | --- | --- | --- |
| Live alert | `/m/alert` | Full-screen alert: what, where, predicted time, blurred clip, buzzer status, countdown to the backup call; switches to "Handled" when an owner is set | "I'm on it", report a false alarm |
| Set a rule | `/m/rules/new` | Text box with a microphone button, then Claude's draft on a mini floor plan | Confirm or adjust the rule |
| Incident report | `/m/reports/:id` | Summary, timeline with clip links, caregiver note | Add a note, share with a parent, export to PDF |

### Reads and writes

| Data | Source | How |
| --- | --- | --- |
| Open alerts, own caregiver row, reports | Spacetime | Subscriptions |
| Acknowledge, confirm zone, caregiver note | Spacetime | Server function calls |
| Rule text | Worker | `POST /rules/interpret` |
| Clips and key frames | Vision service | Local HTTP; only on the daycare's Wi-Fi |

### Phone limits to plan around

- Vibration from a web page works on Android but not on iPhone, which is one reason the wrist buzzer exists.
- Web push notifications on iPhone need the app added to the home screen. For the demo, keep the page open.
- Clips load only on the daycare's Wi-Fi, because video never leaves the local network.

## Outside services

Every outside service is called only by the worker, and each one receives the least data it needs.

| Service | What it does for NestWatch | What it receives | What it never receives |
| --- | --- | --- | --- |
| Claude API | Second opinions, rule drafts, incident reports, daily summaries | Event logs, blurred key frames, rule text, named areas | Live video, unblurred images, phone numbers |
| Cartesia | Speaks the escalation message | The message text, such as "A child entered the stairs area 20 seconds ago. Press 1 if you're on it." | Images, names of children |
| Twilio | Places the call and reports the key press | The backup caregiver's phone number and the audio link | Images, event logs |
| Moss (optional) | Understands spoken replies during the call | Call audio | Images, event logs |
| Apify | Collects recall notices for children's products | Nothing from NestWatch; it scrapes public recall listings | Any daycare data |

**Model choice:** use a fast, low-cost Claude model for second opinions, where speed matters, and a stronger one for reports and rule drafts, where quality matters more than a few seconds.

## Connections

There are 16 links between components, and each one has one direction of authority: the component on the left starts the exchange.

| # | From → To | What's sent | Transport | How often |
| --- | --- | --- | --- | --- |
| 1 | Cameras → Vision service | Video frames | USB or RTSP | Every frame |
| 2 | Vision service → Spacetime | Child and adult positions | `update_positions` | 5–10 times a second |
| 3 | Vision service → Spacetime | Events | `report_event` | When a detector fires |
| 4 | Spacetime → Vision service | Zones, schedules, buzzer pairing, open alerts | Subscription | On change |
| 5 | Vision service ↔ Wrist buzzer | Buzz, stop, ack, ping | Local WebSocket | On alert; ping every 5 s |
| 6 | Vision service → Spacetime | Buzzer acknowledgments, camera health | `acknowledge_alert`, `camera_health` | On tap; health every 10 s |
| 7 | Vision service → Worker | Blurred key frames for an event | `POST /keyframes` over HTTPS | Once per event |
| 8 | Spacetime → Dashboard, phone app | Positions, alerts, zones, reports | Subscriptions | Live |
| 9 | Dashboard, phone app → Spacetime | Acknowledge, close, confirm zone, notes | Server function calls | On click |
| 10 | Dashboard → Vision service | Calibration points, adult tags, snapshot and clip requests | Local HTTP | During setup and review |
| 11 | Dashboard, phone app → Worker | Rule text | `POST /rules/interpret` over HTTPS | On request |
| 12 | Spacetime → Worker | Queued calls, new borderline alerts, closed alerts, zone drafts | Subscription | On change |
| 13 | Worker → Spacetime | Call results, backup acknowledgment, urgency, reports, zone drafts | Server function calls | After each job |
| 14 | Worker → Claude | Prompts with tools | HTTPS API | In the background |
| 15 | Worker → Cartesia → Twilio | Speech audio, then the phone call | HTTPS API | On escalation |
| 16 | Twilio → Worker | Call status and key press | Webhooks | During the call |

### Message formats

**Positions (link 2):**

```json
{
  "room_id": "main",
  "at": "2026-10-24T10:14:30.120-07:00",
  "positions": [
    {"track_id": "t4", "kind": "child", "label": "4", "x": 1.12, "y": 1.85, "vx": -0.21, "vy": 0.44, "visible": true},
    {"track_id": "t9", "kind": "adult", "label": "M", "x": 2.30, "y": 0.60, "vx": 0.0, "vy": 0.0, "visible": true}
  ]
}
```

**Event (link 3):**

```json
{
  "track_id": "t4",
  "event_type": "zone_entry_predicted",
  "zone_id": "stairs",
  "severity": "high",
  "predicted_entry_s": 2.8,
  "camera_id": "cam1",
  "clip_ref": "evt_20261024_101430_t4",
  "at": "2026-10-24T10:14:30.120-07:00"
}
```

`event_type` is one of `zone_entry_predicted`, `zone_entry`, `fall`, `climbing`, `stillness`, `unsupervised`, `possible_distress`, `child_not_visible`, `head_count_mismatch`.

**Acknowledge (links 6, 9, 13):**

```json
{"alert_id": "a_1042", "caregiver_id": "c_maria", "via": "buzzer"}
```

`via` is `buzzer`, `dashboard`, `phone_app`, `phone_call` or `voice`. The reply says either `owned_by_you` or `already_owned` with the owner's name.

**Key frames (link 7):** a multipart upload of two or three blurred JPEG images, keyed by the event's `clip_ref`, which the worker matches to the alert. The worker keeps them for 24 hours.

**Rule interpretation (link 11):**

```json
{"room_id": "main", "text": "Keep kids away from the kitchen gate during nap time."}
```

The reply is a draft for the app to show:

```json
{
  "zone_draft_id": "z_draft_17",
  "area_name": "Kitchen gate",
  "schedule": {"named": "nap_time"},
  "severity": "high",
  "escalation": "buzzer_then_call_after_20s",
  "needs_drawing": false,
  "question": null
}
```

**Call job (link 12):**

```json
{"job_id": "call_88", "alert_id": "a_1042", "caregiver_id": "c_backup", "attempt": 1, "status": "queued"}
```

## End-to-end flows

These four flows are what the demo shows; each step names the component and the link number from the Connections table.

### 1. Alert handled by the primary caregiver

1. **Vision service** tracks Child 4 heading for the stairs and predicts entry in 2.8 s; CUSUM crosses its threshold.
2. **Vision service → Spacetime** (link 3): `report_event`. Spacetime creates alert `a_1042`, status `notified`, escalation due in 20 s.
3. **Spacetime → vision service, dashboard, phone app** (links 4, 8): the new alert arrives everywhere at once.
4. **Vision service → wrist buzzer** (link 5): "buzz". The dashboard and phone show the alert card and countdown.
5. **Vision service → worker** (link 7): blurred key frames for the clips and the report.
6. Maria taps her buzzer. **Buzzer → vision service → Spacetime** (links 5, 6): `acknowledge_alert(via: buzzer)`.
7. **Spacetime**: owner set, status `owned`, escalation cancelled. Every screen switches to "Maria is handling Child 4" and the vision service sends "stop" to all buzzers.
8. Child 4 moves back to the play area. **Vision service → Spacetime**: `close_alert`.
9. **Spacetime → worker** (link 12): alert closed. **Worker → Claude** (link 14): write the report. **Worker → Spacetime** (link 13): `save_report`.

### 2. Alert escalated to the backup

1. Steps 1–5 above, but nobody acknowledges within 20 s.
2. **Spacetime timer**: `escalate` runs, status `escalated`, and a `call_job` is queued.
3. **Spacetime → worker** (link 12): the queued call arrives.
4. **Worker → Cartesia**: generate the message audio. **Worker → Twilio** (link 15): call the backup's phone.
5. **Twilio → worker** (link 16): the backup pressed 1. **Worker → Spacetime** (link 13): `acknowledge_alert(via: phone_call)`.
6. Every screen shows "Handled by the backup caregiver"; the flow continues as in steps 7–9 above.
7. If the backup doesn't answer within 30 s: `escalate` runs again, status `unanswered`, a second call is placed, the local alarm sounds and all staff are notified.

### 3. Setting a rule in plain words

1. The provider types "Keep kids away from the kitchen gate during nap time" in the **phone app**.
2. **Phone app → worker** (link 11): `POST /rules/interpret`.
3. **Worker → Claude** (link 14): the text plus the room's named areas, using the `draft_zone_rule` tool.
4. **Worker → Spacetime** (link 13): `save_zone_draft`, status `draft`. The reply goes back to the app.
5. The app shows the draft on the mini floor plan. The provider presses "Confirm rule".
6. **Phone app → Spacetime** (link 9): `confirm_zone`. **Spacetime → vision service** (link 4): the vision service starts checking the new zone.

### 4. Medium alert with a second opinion

1. **Vision service → Spacetime** (link 3): `report_event` for an unsupervised child, severity medium. The buzzer and app alert as usual.
2. **Spacetime → worker** (link 12): new medium alert. **Worker → Claude** (link 14): the key frames and recent events, with a 5-second limit.
3. If Claude sees the child is actually next to an adult the camera partly missed, **worker → Spacetime** (link 13): `set_urgency` lowers it to low with a note. The alert stays visible, and the caregiver still decides.

## Security, privacy and failure behavior

Each component protects the data it holds and fails in a way that keeps alerts reaching a person.

### Security and privacy

| Component | Protection |
| --- | --- |
| Vision service | Raw video never leaves the computer; faces are blurred before any clip or frame is saved; local endpoints answer only on the daycare network; clips are deleted after a set number of days |
| Wrist buzzer | Pairs only with its assigned caregiver; carries no personal data |
| Spacetime | Every server function checks the caller's identity; phone numbers are readable only by the worker; children appear only as track numbers |
| Worker | Holds all API keys; checks Twilio signatures; deletes key frames after 24 hours; checks every Claude output before writing it |
| Dashboard and phone app | Caregiver sign-in; no API keys; clips load only on the local network |
| Outside services | Receive only the fields listed in the Outside services section |

### Failure behavior

| Failure | What happens | Who notices |
| --- | --- | --- |
| A camera stops sending frames | The vision service marks it offline in Spacetime; its area turns grey on every screen | Dashboard banner, one buzzer alert |
| The pose model slows down | The capture module drops old frames so alerts stay current; health shows the frame rate | Dashboard health indicator |
| A child's track is lost | Last position kept for about 2 s, then a `child_not_visible` event | Low alert |
| Internet drops at the daycare | Detection, the buzzer and the local alarm keep working; events queue and sync when the connection returns | Dashboard "offline" banner |
| Spacetime is unreachable | Same as an internet drop; high alerts sound the local alarm immediately | Local alarm |
| The worker is down | Alerts, buzzer and screens still work; calls fall back to the local alarm at the unanswered step | Health check |
| Claude is slow or down | Second opinions are skipped; reports are written later | Nobody needs to act |
| Twilio or Cartesia fails | One retry, then the local alarm and all-staff notification | `call_job` shows failed |
| A buzzer's battery dies | It disconnects; the dashboard shows it, and alerts still reach the phone app | Dashboard caregiver list |

## Open questions

Settle these early, because each one changes how two components connect.

- [ ] Can a Mana-built dashboard use the Spacetime client library, or do we prototype in Mana and move the code into React?
- [ ] Does our Spacetime SDK version support scheduled server functions for the escalation timer, or does the worker run the fallback check?
- [ ] Which Spacetime module language do we use: TypeScript, Rust or C#?
- [ ] Does the worker run in the cloud or on the demo laptop? On the laptop it can reach the vision service directly, but it's less realistic.
- [ ] Do phones at the venue share a network with the demo laptop, so clips load?
- [ ] What escalation timeouts does a real provider think are right for each severity?
- [ ] Do we build Moss voice replies, or keep the key press only?
