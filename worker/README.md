# NestWatch worker

The only component that talks to outside services (Claude, Cartesia, Twilio). It watches Spacetime, does slow work in
the background and writes results back through server functions. It is never on the alert path: if it is down,
buzzers, screens and escalation timers still work; calls and reports wait until it is back.

| Job | Trigger | Result |
| --- | --- | --- |
| Escalation call | `call_job` queued | Simulated by default. Real: Cartesia speech, Twilio call, press 1 → `acknowledge_alert(via: phone_call)`. A call that fails to place is retried twice, then marked failed (escalation goes on) |
| Second opinion | new medium or low alert with key frames | Claude (fast model), hard 5 s limit, may only lower it (`set_urgency`); high alerts are never touched |
| Incident report | alert closed | Claude (strong model); every line must cite a real event id, others are dropped; without Claude a plain report from the event log |
| Rule interpretation | `POST /rules/interpret` | inactive zone draft on a named area (`save_zone_draft`); "needs drawing" if no area fits; without Claude a keyword match |
| Daily summary | `CLOSING_TIME` | `save_report` (daily), once per day |
| Key frames | `POST /keyframes` from the vision service | kept 24 h in memory for second opinions |

Callers send their Spacetime token as a bearer token; the worker asks Spacetime who it belongs to (the `my_role`
view, read with the caller's token). Twilio webhooks are checked with Twilio's request signature.

## Run

```bash
cd worker
uv venv .venv --python 3.12 && uv pip install --python .venv/bin/python -e ".[test]"
.venv/bin/python scripts/make_identity.py              # creates .worker-token (git-ignored)
spacetime call --no-config nestwatch-test grant_role '"0x<identity it printed>"' '"worker"' '{"none":[]}' --server local
.venv/bin/python -m nestwatch_worker.main               # http://127.0.0.1:8787/health
```

Settings are environment variables; see `.env.example`. The vision service sends key frames when started with
`--worker-url http://127.0.0.1:8787`.

## Check

```bash
.venv/bin/python -m pytest                              # unit tests (fake Spacetime)
SIM_CALL_OUTCOME=press1 SIM_RING_S=3 .venv/bin/python -m nestwatch_worker.main &
.venv/bin/python scripts/flows.py primary               # flow 1: buzzer tap, close, report
.venv/bin/python scripts/flows.py escalation            # flow 2: backup call, press 1
.venv/bin/python scripts/flows.py rule                  # flow 3: plain-language rule
.venv/bin/python scripts/flows.py opinion               # flow 4: medium alert with key frames
```

`flows.py call-failure` needs the worker started with `SIM_CALL_OUTCOME=error`.

## Real calls

Set `CALLS_ENABLED=true`, the Twilio and Cartesia values and `PUBLIC_BASE_URL` (an https tunnel to the worker, used
for `/audio`, `/twilio/gather` and `/twilio/status`). Missing anything means calls stay simulated; `/health` says which.
Wajo has no public API yet; a Wajo provider would be one more class next to `TwilioCalls` in `calls.py`.
