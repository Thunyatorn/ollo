"""Run the worker:  .venv/bin/python -m nestwatch_worker.main   (settings from the environment; see .env.example)"""
import logging
import sys

import uvicorn

from .ai import Claude
from .app import create_app
from .calls import AgentCalls, FallbackCalls, SimulatedCalls, TwilioCalls
from .config import Settings
from .jobs import Worker
from .spacetime import Spacetime
from .store import KeyframeStore, TokenChecker

log = logging.getLogger("nestwatch.worker")


def build(s: Settings):
    if not s.token:
        sys.exit("No worker token: run scripts/make_identity.py, then grant it the worker role (see README).")
    stdb = Spacetime(s.spacetime_url, s.db, s.token)
    claude = None
    if s.claude_enabled:
        from anthropic import AsyncAnthropic
        claude = Claude(AsyncAnthropic(), s.fast_model, s.strong_model)
    if s.agent_ready():
        calls = FallbackCalls(AgentCalls(s), TwilioCalls(s)) if s.twilio_ready() else AgentCalls(s)
    elif s.twilio_ready():
        calls = TwilioCalls(s)
    else:
        calls = SimulatedCalls(s.sim_outcome, s.sim_ring_s)
    if s.calls_enabled and isinstance(calls, SimulatedCalls):
        log.warning("CALLS_ENABLED is set but Twilio/Cartesia settings are incomplete: calls stay SIMULATED")
    keyframes = KeyframeStore(s.keyframe_ttl_s)
    worker = Worker(stdb, s, claude, calls, keyframes)
    return create_app(worker, TokenChecker(stdb), keyframes, s), worker


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    s = Settings()
    app, worker = build(s)
    log.info("worker on %s:%d; Spacetime %s/%s; Claude %s; calls %s", s.host, s.port, s.spacetime_url, s.db,
             "on" if worker.claude else "off", worker.calls.name)
    uvicorn.run(app, host=s.host, port=s.port, log_level="warning")


if __name__ == "__main__":
    main()
