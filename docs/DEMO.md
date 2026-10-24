# NestWatch demo playbook

A 2-minute live demo that ends with a teammate's phone ringing. Every step below uses a feature that is built and tested; the requirement IDs refer to [SPEC.md](SPEC.md).

## Night before

1. **Install and fetch the model:** `npm install`, Python setup, `npm run models` (README → Run locally).
2. **Fill `.env`:**
   - `ANTHROPIC_API_KEY`, `CLAUDE_MODEL` (rule drafting and reports) and `VISION_MODEL` (second opinion)
   - the Cartesia agent variables from [CARTESIA_AGENT.md](CARTESIA_AGENT.md)
   - `CALL_ALLOWLIST` with two **consenting teammates'** numbers
   - an HTTPS tunnel that exposes only `/webhooks/*`
3. **Create the Cartesia voice agent and its `acknowledge_alert` tool** (CARTESIA_AGENT.md). Place one real test call to a teammate.
4. **Run the browser suites:** `npm start`, then `npm run test:ui && npm run test:media && npm run test:design`. All three must pass.
5. **Record staged clips and run `npm run eval`** (README → Measuring accuracy). Put the table on the math slide.
6. **Record a backup video of the full flow below.** Use it if the venue network fails.

## On site (10 minutes before)

1. Point the laptop webcam at a clear floor area. Tape a rectangle on the floor as "the stairs", plus 5 marks whose positions you measure in meters. Connect the webcam as the server camera (Settings → Manage source → Camera read by the NestWatch server, index `0`), so analysis keeps running if the dashboard is minimized (SRC-4).
2. **Calibrate.** Use the ruler button: click the 5 marks and type their positions. The panel should report an error under 0.10 m (DET-9).
3. **Draw the landmark.** Shield button → Draw landmark: outline the taped rectangle and name it "Stairs" (AI-6).
4. Open the Map button, so the floor-plan inset is visible (UI-4).
5. Settings: primary and backup caregiver names, and the escalation delay (for example 8 s and 20 s). Turn on **Claude second opinion** only if the network is good.
6. Arm calls only after confirming that both teammates are ready.

## Script (2:00)

| Time | Say | Show |
|---|---|---|
| 0:00–0:15 | "A home daycare: one adult, six kids. Her fear is changing a diaper while another child heads for the stairs." | Title slide with the provider quote |
| 0:15–0:35 | "She sets it up in plain words." | Type "Keep kids away from the stairs" → Claude drafts it → the landmark is outlined in amber → **Confirm**. Nothing is enforced before Confirm. |
| 0:35–1:00 | "It predicts, not just reacts." | A teammate walks toward the tape. Their skeleton turns amber with "Restricted area in ~2 s" and a predicted path, also shown on the floor plan. They step in, and a **critical** incident opens. |
| 1:00–1:25 | "No one answered, so a second person is called." | The primary step passes. The backup phone rings with the Cartesia voice agent. The teammate says "I'm on it", and the trace shows **Handled by ⟨name⟩ via voice**. |
| 1:25–1:45 | "And it documents what happened." | Report button: a timeline where every line cites a logged fact, plus the face-blurred evidence clip and Claude's second opinion card. |
| 1:45–2:00 | "Detection is local and free per hour; Claude is never on the alert path." | Math slide: time-to-entry probability, CUSUM, cost table, the eval table with its intervals |

## If something fails

| Failure | What happens and what to say |
|---|---|
| Venue network down | Detection, alerts, the timeline and the plain report all work offline. Calls fall back to the labeled simulation. Play the backup video for the phone segment. |
| Claude unavailable | Drafting returns a clear error, so use a rule confirmed before the demo. The report falls back to the plain cited timeline (AI-7). The second opinion just doesn't appear; alerts are unaffected (AI-4). |
| Voice agent fails | The same step falls back to the Twilio keypad call: press 1 (ESC-3). |
| Pose model missing | The HOG person detector runs instead. Zone rules still work, but the keypoint rules do not (DET-1). |
| Hidden or minimized browser tab | With the server camera, nothing changes (SRC-4). With an uploaded clip or the browser webcam, analysis slows and the footer turns amber, so keep the tab visible (SRC-2). |
| Server camera stops sending | Within 3 s the video shows "Analysis unavailable", the footer says "no frames", and a camera_offline event is logged. It reconnects every 2 s on its own (SRC-4). |

## Likely questions

- **"What if it misses something?"** Show the eval table: precision and recall with 95% intervals, and false alarms per hour, on held-out staged clips. NestWatch supports supervision and never replaces it, and every alert says what video cannot tell.
- **"Privacy?"** Live video never leaves the laptop. Only a few face-blurred crops of the flagged person go to Claude, and only after an alert (opt-in). Clips are blurred and deleted after 7 days.
- **"Cost?"**
  - Detection: $0 per camera-hour (local CPU, about 1.3 cores at 12 fps).
  - Claude second opinion: about $0.0003 (Haiku 5.5) to $0.01 (Opus 5.5) per alert, and $0 while nothing happens.
  - Rule drafts and reports: cents.
  - Calls: provider per-minute rates.
- **"Why not a baby monitor?"** A monitor shows video. NestWatch predicts, alerts, makes sure someone owns the alert, and writes the record.

## Honesty rules for the stage

- Staged adult clips test the software, not child safety. Say so.
- Never call an alert a diagnosis. The labels are "possible fall", "unusual rhythmic movement" and "possible distress".
- Fixture, illustration and simulated states stay labeled on screen.
