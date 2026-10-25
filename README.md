# ollo

ollo is a real-time safety monitoring system that connects to existing CCTV security cameras, detects potential safety incidents, and initiates a response through caregiver notifications and AI agent phone calls. The goal is to turn camera footage into timely action: reach a caregiver, confirm someone is responding, and escalate critical emergencies to 911 through a configured emergency-response workflow. (The repository and API keep the working name `lookout`.)

## Project goal

Connect the full loop from **CCTV feed → real-time event analysis → notification or AI phone call → confirmed response → incident record**. Daycares are the first use case; the core product is a safety monitoring and response layer for existing security cameras.

- **Connect:** ingest compatible CCTV streams, starting with RTSP and HTTP, and keep monitoring even when the dashboard is closed.
- **Analyze:** recognize configured safety events such as restricted-area entry, possible falls, signs of distress, and prolonged stillness, using observations over time to decide when to raise an incident.
- **Act:** notify the assigned caregiver immediately. An AI phone agent explains what was observed and where, asks whether the recipient can respond, and records their acknowledgment. Escalate to backup caregivers when nobody responds.
- **Escalate emergencies:** the intended product includes 911 escalation for critical incidents through an AI agent phone call, governed by an explicit emergency-response policy defining when a call is warranted, whether human confirmation is required, and what location and observed facts the agent must communicate.
- **Track the outcome:** preserve the event timeline, response ownership, call attempts, acknowledgment, resolution, and relevant evidence.

**Current prototype:** compatible camera-stream ingestion, local event analysis, dashboard alerts, caregiver call integrations, and incident records are implemented. Real provider calls require credentials and explicit session arming; calls otherwise remain simulated. External notification delivery and 911 calling are product goals, not implemented capabilities. Emergency-service integration and its escalation policy still need to be designed and validated; hackathon calls target consenting teammates only. Video observations are safety signals, not medical diagnoses.

Built for Cal Hacks 13.0. [docs/SPEC.md](docs/SPEC.md) is the source of truth: requirements with IDs, acceptance criteria, the tests that verify each one, and the build plan. `server/tests/test_spec.py` fails the suite if the spec and tests disagree. Background research is in the [implementation specification](docs/IMPLEMENTATION_SPEC.md), measured changes are in the [improvement log](docs/IMPROVEMENT_LOG.md), and the math behind every rule and optimization is explained in [docs/MATH.md](docs/MATH.md).

## Spacetime edition (a second build in this repository)

Alongside this prototype the repository holds a second implementation of the same product, built on a SpacetimeDB backend with a
Python vision service, a worker for calls and Claude, a wrist-buzzer simulator and firmware, and a dashboard and phone app of its own.
It lives in separate folders (`spacetime/`, `vision/`, `worker/`, `web/`, `firmware/`, `tools/`, `packages/`) and shares no code with
this one. Start with [README.spacetime.md](README.spacetime.md); the spec is [CLUADE.md](CLUADE.md), the math is [MATH.md](MATH.md), and
the integration and failure-drill results are in [docs/INTEGRATION.md](docs/INTEGRATION.md).

## Run locally

Requires Node.js 20.19+ and Python 3.12 (recommended). From this directory:

```sh
npm install
python3.12 -m venv .venv
.venv/bin/python -m pip install -r server/requirements.txt
.venv/bin/python -m pip install -r server/requirements-pose.txt
npm run models
npm start
```

The second install and `npm run models` add the local pose detector (YOLO26n-pose with ByteTrack IDs, CPU-only PyTorch, about 30 ms per frame). Weights are saved once to `models/`; the API never downloads at runtime. Skip both steps to run with the weaker OpenCV HOG fallback, or force it with `LOOKOUT_DETECTOR=hog`.

Open [Lookout](http://127.0.0.1:5173). The combined launcher starts Vite on port 5173 and the API on port 8000. If your system has a different Python executable, use its full path to create the virtual environment.

Alternatively, run two terminals:

```sh
.venv/bin/python -m uvicorn server.app:app --host 127.0.0.1 --port 8000
```

```sh
npm run dev
```

The frontend also supports a clearly labeled local demonstration when the API is unavailable. Provider calls and actual frame analysis require the backend. This fallback is not evidence of a working detection model.

## Demo

The 2-minute live script, setup checklist, fallbacks and Q&A are in [docs/DEMO.md](docs/DEMO.md). Without any credentials, everything except real calls and Claude features runs offline:

1. Upload a recorded clip, start the browser webcam, or connect a camera the server reads itself (Settings → Manage source: a webcam index such as `0`, or an `rtsp://` or `http://` stream URL). With the server camera, analysis keeps running when the dashboard tab is hidden or closed (SRC-4).
2. Calibrate the floor (ruler button) and draw a landmark (shield button).
3. Use Settings → demo scenarios for fixture incidents.
4. Acknowledge and resolve incidents in the event trace, open a Report, and try `/respond/{id}` on a phone-sized window.

Calls stay simulated and labeled until real providers are configured and the operator arms them for the session.

## Sponsor tools

| Tool | Where it does real work | Code |
|---|---|---|
| **Anthropic Claude** | 1. A second opinion on each local alert: face-blurred crops of the flagged person, structured output, never on the alert path (AI-1 to AI-5). 2. Turning a typed rule into a draft that the operator confirms (AI-6). 3. Incident reports where every line must cite logged facts (AI-7). | `server/review.py`, `server/rules.py`, `server/report.py` |
| **Cartesia** | The escalation call. Sonic speech for the keypad call (ESC-2), and a voice agent that understands "I'm on it" and acknowledges through a webhook tool (ESC-3). | `server/providers.py`, [docs/CARTESIA_AGENT.md](docs/CARTESIA_AGENT.md) |
| Twilio | Keypad call and fallback when the voice agent fails | `server/providers.py` |
| Ultralytics YOLO (open source, AGPL-3.0) | Local pose detection and tracking | `server/vision.py` |

Considered and not used: Spacetime and Mana as the core backend and dashboard, because the tested FastAPI alert core is what the demo depends on (SPEC D-3). Wajo has no API for starting calls (D-4). The Apify recall checker is a post-M4 add-on.

## Providers and credentials

Copy `.env.example` to `.env` and fill in only the services you intend to use. Never commit `.env`. The API reads environment configuration at startup; see the example for the actual supported variables.

- **Video:** local YOLO26n-pose (17 body keypoints per person) with ByteTrack IDs, so each person has their own restricted-zone state. Ground position uses confident ankles, else the box's bottom center. Falls back to the OpenCV HOG person detector when the pose model is not installed. Pose models are trained mostly on adults and have significant limitations for small, seated, crawling, or occluded children. Nothing classifies age or identity. Ultralytics is AGPL-3.0.
- **Local event rules** (`server/events.py`) on each tracked person's keypoints: both hands at the throat (about 1.5 s), fast drop then lying (about 1 s after the drop), repetitive 1–5 Hz movement in two or more limbs (about 8 s, needs at least 8 analyzed frames per second), and prolonged stillness (configurable `stillness_seconds`, suppressed by `nap_mode`). Each integrates evidence over time, so one noisy frame never alerts. They are "check now" signals, never diagnoses, and their thresholds are tuned on synthetic skeletons, not real footage.
- **Claude second opinion** (`server/review.py`, official `anthropic` SDK): enabled explicitly in settings. Runs only after a local rule has already raised an incident, so it never delays, cancels, or downgrades an alert, and nothing is sent while nothing happens. It sends up to 4 frames cropped to the flagged person, with every visible head blurred first, and gets back a structured opinion (JSON-schema output) that is attached to the incident as context. Models with safety classifiers use server-side `fallbacks: "default"`. A per-session token and cost meter appears in settings. See `.env.example` for per-review cost by model.
- **Speech:** Cartesia synthesizes the caregiver alert.
- **Rules in plain words** (`server/rules.py`): draw and name landmarks on the video (shield button), then type a rule such as "Keep kids away from the kitchen gate during nap time". Claude (`CLAUDE_MODEL`, JSON-schema output) drafts a landmark, a schedule (always, a time window, or nap mode) and a severity. Anything it can't match to a real landmark or a valid time comes back as a question, and nothing is enforced until you confirm. Confirmed rules become extra restricted zones, each with its own entry state and predictive warning.
- **Evidence and reports:** when an incident opens, the analyzed frames from 5 s before to 5 s after are saved as a WebM clip with every head blurred (`server/clips.py`), and evidence stills are blurred too. Clips are deleted after `clip_retention_days` (default 7). The incident card's Report button builds a timeline from numbered facts taken only from logged data (`server/report.py`). With Claude configured, Claude phrases it, but every line must cite facts, and lines that assert a diagnosis are removed. The report downloads as Markdown.
- **Voice agent (optional):** with `CALL_PROVIDER=cartesia_agent`, a Cartesia voice agent places the call and the caregiver can just say "I'm on it". The agent's webhook tool presents a single-use token to `/webhooks/voice/ack`, which acknowledges through the same first-wins path, and the dashboard shows "Handled by ⟨name⟩ via voice". A failed agent call falls back to the keypad call. Setup: [docs/CARTESIA_AGENT.md](docs/CARTESIA_AGENT.md).
- **Phone:** Twilio places the call and receives signed delivery/DTMF callbacks. Verified recipients and account capabilities must be tested in the actual account. API credits for speech do not imply free phone minutes.

Real calls must only target consenting teammates during the hackathon. Never configure emergency-service numbers. A reachable HTTPS callback URL is required for phone providers; don't expose the entire local dashboard through an unauthenticated public tunnel.

## Verification

```sh
npm run build
.venv/bin/python -m pytest server/tests -q
```

Browser smoke checks use Playwright. If Playwright is not available in your environment, install it as a development dependency and install its Chromium browser before running the smoke script. Set `PLAYWRIGHT_MODULE` to an absolute module path when using a bundled runtime.

```sh
npm run test:ui
npm run test:media
npm run test:design
npm run test:camera
```

`test:camera` checks SRC-4 server capture. It serves a generated MJPEG stream over local HTTP, so the server's real OpenCV path reads it without opening a camera. It checks analysis with no dashboard tab open, and `offline` within 3 s of the stream stalling.

`test:design` checks UI-4, UI-5 and UI-6 in a real browser: branding, the floor-plan inset, skeletons, and the caregiver phone view. It injects overlays by intercepting the frame endpoint, so it tests rendering, not detection.

`media-smoke.mjs` creates a short synthetic WebM and checks the real upload/frame-analysis path. It is a transport check, not a detection benchmark. If your bundled Playwright browser version differs, set `PLAYWRIGHT_CHROMIUM_EXECUTABLE` to an installed Chromium executable. Both scripts accept `LOOKOUT_URL` to override the default local address.

Run the app before browser checks. Browser screenshots and state are written beneath `test-results/`, which is ignored.

## Measuring accuracy

Record staged clips with consenting teammates (positives, plus look-alikes such as eating, dancing and lying down on purpose), label them, and run:

```sh
npm run eval -- clips/labels.json --split test
```

`labels.json` lists each clip's path, split (`tune` or `test`), optional engine settings (zone, calibration, rules), and events (`kind`, `onset_s`). The real engine runs offline at 12 fps. A hit is an alert of the right kind 0–5 s after onset. The report gives precision and recall with Wilson 95% intervals, mean delay, and false alarms per hour of negative footage. Tune thresholds on `tune` and report `test`.

## Prototype boundaries

Possible choking/distress is an experimental caregiver-check signal, not a diagnosis. The prototype does not determine breathing or airway status, establish adequate supervision, or replace caregivers. A staged adult demonstration is not validation for infant or toddler emergencies.

Illustrations, developer fixtures, and cached results must retain their labels. No production daycare footage or child medical incidents are included. Do not publish private footage or present selected demo success as deployment accuracy.

Sponsor use is listed above. Spec decisions and their "revisit if" conditions are in [docs/SPEC.md](docs/SPEC.md).

## Verified in this workspace

- `pytest`: 71 tests, each named in [docs/SPEC.md](docs/SPEC.md); `test_spec.py` fails if the spec and tests disagree.
- Browser (Playwright): `test:ui`, `test:media`, `test:design` and `test:camera` all pass.
- Production TypeScript/Vite build.
- Live checks in a browser, recorded in [docs/IMPROVEMENT_LOG.md](docs/IMPROVEMENT_LOG.md):
  - 12 fps analysis, and 12 fps from the server camera with no dashboard tab open
  - floor calibration through the UI
  - a 2.76 s predictive lead
  - the rule confirm gate (draft not enforced, confirmed enforced)
  - face-blurred evidence clips and reports
  - "Handled by" ownership
- Evaluation harness on real YOLO output. It caught and fixed a ground-point bias.

**Not verified:** real Claude responses (no API key here; all Claude paths are tested with fakes), real Cartesia or Twilio calls, detection accuracy on children, a real RTSP camera or physical webcam through server capture (tested with a generated HTTP MJPEG stream through the same OpenCV path), and remote caregiver authentication. With a browser source (upload or browser webcam), analysis slows when the dashboard tab is hidden; the server camera does not.

The playroom background was generated with the built-in imagegen tool and saved as `public/playroom-cctv.png`. Its full generation prompt is in `public/playroom-cctv.prompt.txt`. The overlaid boxes are static UI demonstration elements, not model detections.
