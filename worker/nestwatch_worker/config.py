"""Every setting comes from the environment (see .env.example). API keys live only here, in the worker (CLUADE.md rule 2)."""
from dataclasses import dataclass, field
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _flag(name: str, default: bool = False) -> bool:
    return _env(name, "true" if default else "false").lower() in ("1", "true", "yes", "on")


def _token() -> str:
    if _env("WORKER_TOKEN"):
        return _env("WORKER_TOKEN")
    path = Path(_env("WORKER_TOKEN_FILE", str(HERE / ".worker-token")))
    return path.read_text().strip() if path.exists() else ""


@dataclass
class Settings:
    spacetime_url: str = field(default_factory=lambda: _env("STDB_HTTP", "http://127.0.0.1:3000"))
    db: str = field(default_factory=lambda: _env("STDB_DB", "nestwatch-test"))
    token: str = field(default_factory=_token)
    host: str = field(default_factory=lambda: _env("WORKER_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: int(_env("WORKER_PORT", "8787")))
    app_origins: str = field(default_factory=lambda: _env("APP_ORIGINS"))   # extra allowed browser origins, comma-separated
    poll_s: float = 0.5

    # Claude. A fast model where speed matters (second opinion), a stronger one for rules and reports (CLUADE.md).
    claude_enabled: bool = field(default_factory=lambda: _flag("CLAUDE_ENABLED", bool(_env("ANTHROPIC_API_KEY") or _env("ANTHROPIC_AUTH_TOKEN"))))
    fast_model: str = field(default_factory=lambda: _env("CLAUDE_FAST_MODEL", "claude-haiku-4-5"))
    strong_model: str = field(default_factory=lambda: _env("CLAUDE_STRONG_MODEL", "claude-opus-5-5"))
    second_opinion_timeout_s: float = 5.0
    keyframe_wait_s: float = 12.0         # how long a second opinion waits for the vision service's key frames
    keyframe_ttl_s: float = 24 * 3600     # the worker keeps key frames for 24 hours
    closing_time: str = field(default_factory=lambda: _env("CLOSING_TIME", "18:00"))   # local time of the daily summary
    escalation_backstop: bool = field(default_factory=lambda: _flag("ESCALATION_BACKSTOP", True))

    # Calls. Nothing real is dialled unless CALLS_ENABLED=true AND the provider's credentials are all present.
    calls_enabled: bool = field(default_factory=lambda: _flag("CALLS_ENABLED"))
    call_provider: str = field(default_factory=lambda: _env("CALL_PROVIDER", "twilio"))
    public_base_url: str = field(default_factory=lambda: _env("PUBLIC_BASE_URL").rstrip("/"))   # https URL Twilio can reach
    twilio_sid: str = field(default_factory=lambda: _env("TWILIO_ACCOUNT_SID"))
    twilio_token: str = field(default_factory=lambda: _env("TWILIO_AUTH_TOKEN"))
    twilio_from: str = field(default_factory=lambda: _env("TWILIO_FROM_NUMBER"))
    cartesia_key: str = field(default_factory=lambda: _env("CARTESIA_API_KEY"))
    cartesia_voice: str = field(default_factory=lambda: _env("CARTESIA_VOICE_ID"))
    cartesia_model: str = field(default_factory=lambda: _env("CARTESIA_MODEL_ID", "sonic-3.6"))
    cartesia_version: str = field(default_factory=lambda: _env("CARTESIA_VERSION", "2026-08-14"))
    cartesia_agent_id: str = field(default_factory=lambda: _env("CARTESIA_AGENT_ID"))
    cartesia_from_number_id: str = field(default_factory=lambda: _env("CARTESIA_FROM_NUMBER_ID"))
    voice_webhook_secret: str = field(default_factory=lambda: _env("VOICE_WEBHOOK_SECRET"))
    sim_outcome: str = field(default_factory=lambda: _env("SIM_CALL_OUTCOME", "no_answer"))   # no_answer | press1 | error
    sim_ring_s: float = field(default_factory=lambda: float(_env("SIM_RING_S", "6")))
    call_retries: int = 1                 # one retry when placing a call fails outright (CLUADE.md failure table)
    call_retry_delays_s: tuple = (3.0,)

    def agent_ready(self) -> bool:
        need = [self.cartesia_key, self.cartesia_version, self.cartesia_agent_id, self.cartesia_from_number_id, self.voice_webhook_secret]
        return self.calls_enabled and self.call_provider == "cartesia_agent" and all(need) and self.public_base_url.startswith("https://")

    def twilio_ready(self) -> bool:
        need = [self.twilio_sid, self.twilio_token, self.twilio_from, self.cartesia_key, self.cartesia_voice, self.cartesia_model, self.cartesia_version]
        return self.calls_enabled and self.call_provider in ("twilio", "cartesia_agent") and all(need) and self.public_base_url.startswith("https://")
