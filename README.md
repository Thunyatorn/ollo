# Lookout

A dark, camera-first daycare monitoring prototype. Lookout combines an observable boundary-event workflow with experimental multi-frame distress review, caregiver acknowledgment, and phone escalation.

Built for Cal Hacks 13.0. Read the [implementation specification](docs/IMPLEMENTATION_SPEC.md) for the product scope and research.

## Run locally

Requires Node.js 20.19+ and Python 3.12 (recommended). From this directory:

```sh
npm install
python3.12 -m venv .venv
.venv/bin/python -m pip install -r server/requirements.txt
npm start
```

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

1. Open the monitoring view. The initial room is an AI-generated CCTV-style still with four illustrative tracking boxes, visibly labeled as a demo. Select cameras from the video header.
2. Open Settings → General to manage the video source and use demo scenarios to create a simulated restricted-area or possible-distress incident.
3. Acknowledge the incident, inspect its event-trace details, and explicitly resolve it. Answering a phone call is not acknowledgment.
4. Upload rights-cleared recorded footage to inspect your own video. Optional webcam access uses a browser permission prompt.
5. Without provider credentials, phone escalation remains simulated and visibly labeled. Real calls require configured credentials, an allowlisted recipient, and explicit session arming.

The desktop interface uses Tailwind's gray neutral palette, compact controls, a right-hand event trace, incident timeline markers, restrained status color, and a responsive mobile caregiver view.

## Providers and credentials

Copy `.env.example` to `.env` and fill in only the services you intend to use. Never commit `.env`. The API reads environment configuration at startup; see the example for the actual supported variables.

- **Video:** local OpenCV person-detection baseline. This is an adult-demo baseline with significant limitations for small, seated, crawling, or occluded people. It does not classify age or identity.
- **Experimental review:** Anthropic vision on sampled ordered frames, enabled explicitly in settings. Requires an API key and an available model ID. Cloud review transmits selected frames to the provider.
- **Speech:** Cartesia synthesizes the caregiver alert.
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
node scripts/media-smoke.mjs
```

`media-smoke.mjs` creates a short synthetic WebM and checks the real upload/frame-analysis path. It is a transport check, not a detection benchmark. If your bundled Playwright browser version differs, set `PLAYWRIGHT_CHROMIUM_EXECUTABLE` to an installed Chromium executable. Both scripts accept `LOOKOUT_URL` to override the default local address.

Run the app before browser checks. Browser screenshots and state are written beneath `test-results/`, which is ignored.

## Prototype boundaries

Possible choking/distress is an experimental caregiver-check signal, not a diagnosis. The prototype does not determine breathing or airway status, establish adequate supervision, or replace caregivers. A staged adult demonstration is not validation for infant or toddler emergencies.

Illustrations, developer fixtures, and cached results must retain their labels. No production daycare footage or child medical incidents are included. Do not publish private footage or present selected demo success as deployment accuracy.

For sponsor opportunities and the verification status of free-credit offers, see the parent specification and [event briefing](../CALHACKS_13_BRIEFING.md).

## Verified in this workspace

- Production TypeScript/Vite build.
- Backend tests for incident transitions, call gating, callback signatures/order, frame validation, temporal zone rules, and experimental review schema handling.
- Browser workflow: fixture incident → acknowledgment → resolution, history, preferences, source dialog, and responsive layout.
- Actual synthetic WebM upload, decoding, sampled-frame ingestion, and pause behavior.

Real provider calls, cloud model output, representative infant/toddler detection accuracy, RTSP cameras, and background mobile push were not verified. Desktop polling updates connected views; physical-phone delivery uses the configured call provider. Mobile response links currently use the local operator session, so remote caregiver authentication/pairing is still future work.

The playroom background was generated with the built-in imagegen tool and saved as `public/playroom-cctv.png`. Its full generation prompt is in `public/playroom-cctv.prompt.txt`. The overlaid boxes are static UI demonstration elements, not model detections.
