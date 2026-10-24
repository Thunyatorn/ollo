# Phase 6: integration and failure drills

Everything below was run on 2026-10-24 against the local stack: Spacetime (`nestwatch-test`), the vision service,
the worker, and a stand-in buzzer. Calls were **simulated** (no Twilio or Cartesia credentials) and Claude was
**off** (no API key), so reports were the plain kind and rules used keyword matching. The local alarm ran in quiet mode.

## How to repeat

```bash
spacetime start                                                        # if it is not running
cd worker && SIM_CALL_OUTCOME=press1 SIM_RING_S=3 .venv/bin/python -m nestwatch_worker.main &
cd vision && .venv/bin/python -m nestwatch_vision.main out/empty_room.mp4 --demo-map --realtime --quiet-alarm \
    --worker-url http://127.0.0.1:8787 &                               # any clip; an empty room keeps alerts to the script's
cd worker && .venv/bin/python scripts/flows.py primary | escalation | rule | opinion
```

Drills: `flows.py call-failure` (worker started with `SIM_CALL_OUTCOME=error`), `flows.py worker-down` (worker
stopped first; the script starts it). Camera drop: `vision/scripts/mjpeg_server.py VIDEO --drop-at 20 --drop-for 12`
and point the vision service at `http://127.0.0.1:8090/video.mjpg`. Spacetime down: pause the server process
(`kill -STOP`, then `kill -CONT`) while the vision service runs a clip with people in it.

## The four flows

| Flow | Result | Measured |
| --- | --- | --- |
| 1. Primary handles it | pass (script and real vision service) | buzz to Maria's buzzer, tap, `owned via buzzer`, stop to buzzers; report 0.6 s after close |
| 2. Escalated to the backup | pass (script and real vision service) | `escalated` at 20.0 s, simulated call, press 1 at +3.3 s, `acknowledged via phone_call`, call job `answered`; report 0.6 s after close |
| 3. Rule in plain words | pass | "Keep kids away from the kitchen gate during nap time" became an inactive draft on Kitchen gate, `nap_time`, high; confirmed in the app, active, then turned off again. No token: 401 |
| 4. Medium alert, second opinion | partly | key frames reached the worker with the vision identity (the real service sent 9 sets in one run); the alert was left alone. Lowering by Claude is covered by unit tests only: no API key here |

With the real vision service on `out/pan_long.mp4` (demo map): 2 alerts tapped on the buzzer, 3 escalated to
phone calls, all acknowledged, 9 key-frame sets uploaded, every alert closed and reported.

## Failure drills (CLUADE.md "Failure behavior")

| Failure | Expected | Result |
| --- | --- | --- |
| Worker down | alerts, buzzer, screens still work; local alarm at unanswered | pass: escalated at 20.2 s and unanswered at 50.3 s on Spacetime's own timers; local alarm 0.3 s later. Worker restarted: the backup was rung **once** (newest attempt), pressed 1, acknowledged, report written |
| Twilio or Cartesia fails | one retry, then local alarm and all staff | pass: placing failed, one retry 3 s later, call marked failed, Spacetime moved to `unanswered` at once, local alarm on |
| Spacetime unreachable | detection, buzzer and alarm keep working; high alerts sound the alarm; events sync later | pass: 25 s freeze; detection went on at 16 to 18 fps, up to 5 events queued, every high event sounded the local alarm (the first one 2 s after it was raised), queued events reached Spacetime after it resumed |
| Camera stops | marked offline, one buzzer alert | pass: 12 s unplug of a network camera; noticed after 2 s, `cam1` offline in Spacetime during the drop, online again after; the service stayed up |

## What the drills found and what changed

1. **A camera drop shut the vision service down.** The frame stream ended after 2 s of silence and the main loop
   exited, taking the buzzers and the local API with it. Now `LiveSource.watch()` reports offline once, keeps
   waiting while the reader reconnects, and reports online when frames return; the primary's buzzer gets one
   `camera_<id>` notice (a tap just clears it).
2. **The first high event in an outage got no local alarm.** The service only learns Spacetime is gone when a request
   times out (3 s). Now any high event that has not reached Spacetime within 2 s sounds the alarm.
3. **A failed backup call waited out the 30 s timer.** The spec says one retry, then the alarm. The worker now retries
   once, and `update_call_job(failed)` on the first attempt moves the alert straight to `unanswered`.
4. **A restarted worker rang the backup twice at once** (attempts 1 and 2 were both queued). Now only the newest
   queued attempt per alert is dialled; older ones are marked failed.
5. **Nothing closed an alert when the child moved away** (flow 1, step 8). Now an owned zone alert closes by itself
   once its child has been seen at least 0.5 m clear of the zone for 10 s. An unseen child does not count as clear.
6. **"During nap time" rules could never switch on**: the vision service had no named schedules. It now has
   `nap_time` (`--nap-time 12:30-14:30` by default).

## Not tested here

- Claude: no API key on this machine. Second opinions, Claude-written reports and rule drafts are unit-tested with
  a fake client; the plain fallbacks were what ran live.
- Real calls: no Twilio or Cartesia credentials. The Twilio path (speech, dial, webhooks, signature) is unit-tested
  against mocked HTTP; Twilio's own validator agrees with our signature check.
- Auto-close was not seen live: in the test clip nobody stayed clear of the zone for 10 s. Unit tests cover it.
- The ESP32 firmware was not compiled (no Arduino toolchain); the browser buzzer at `/buzzer-sim` was used instead.
- `spacetime/scripts/test-local.sh` was not re-run (it needs per-role CLI logins not set up on this machine); the
  module changes (`my_role` view, failed call goes to unanswered) were exercised by the flows above.
