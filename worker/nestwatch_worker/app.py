"""The worker's HTTP endpoints (CLUADE.md "Worker endpoints").

  POST /rules/interpret   dashboard, phone app (signed-in caregiver)   plain-language rule -> inactive zone draft
  POST /keyframes         vision service (vision identity)             two or three blurred JPEGs for an event
  GET  /audio/{token}     Twilio                                       the Cartesia audio of one call
  POST /webhooks/voice/ack  Cartesia voice agent (bearer secret)            {token, decision}: the caregiver said "I'm on it" or "I can't"
  POST /twilio/voice      Twilio (signed)                              the call instructions: play the audio, wait for one key press
  POST /twilio/gather     Twilio (signed)                              the key the backup pressed; 1 acknowledges
  POST /twilio/status     Twilio (signed)                              ringing, completed, no answer, ...
  GET  /watch/state      Garmin watch (pairing code)                  open alerts for that caregiver, and whether to buzz
  POST /watch/act        Garmin watch (pairing code)                  {alert_id, decision}: I'm on it / I can't respond
  POST /watch/pair       dashboard (signed-in caregiver)              a pairing code for the caregiver's watch
  GET  /health            monitoring                                   connections and counters, no secrets

Callers prove who they are with their Spacetime token as a bearer token; the worker asks Spacetime (my_role view).
"""
import contextlib
import logging
import re

import hmac

from fastapi import Body, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, Response

from . import ai
from .calls import TwilioCalls, twilio_outcome, valid_twilio_signature
from .spacetime import SAFE_ID, Rejected, opt, quoted
from .watch import WatchKeys, watch_state

log = logging.getLogger("nestwatch.api")
LOCAL_ORIGIN = r"https?://(localhost|127\.0\.0\.1|\[::1\]|10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+|[A-Za-z0-9-]+\.local)(:\d+)?"
NUM = re.compile(r"(\d+)$")


def create_app(worker, checker, keyframes, settings, start_loop: bool = True, watch_keys=None) -> FastAPI:
    @contextlib.asynccontextmanager
    async def lifespan(app):
        task = worker.spawn(worker.run(), "poll loop") if start_loop else None
        yield
        if task:
            task.cancel()

    app = FastAPI(title="ollo worker", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    extra = [re.escape(o.strip().rstrip("/")) for o in settings.app_origins.split(",") if o.strip()]
    app.add_middleware(CORSMiddleware, allow_origin_regex="^(" + "|".join([LOCAL_ORIGIN, *extra]) + ")$",
                       allow_methods=["GET", "POST"], allow_headers=["authorization", "content-type"])
    stdb, claude, calls = worker.stdb, worker.claude, worker.calls

    def caller(*roles: str):
        async def check(request: Request) -> dict:
            auth = request.headers.get("authorization", "")
            token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
            try:
                who = await checker.who(token)
            except Exception:
                raise HTTPException(503, "cannot check who you are right now (Spacetime unreachable)")
            if not who or who["role"] not in roles:
                raise HTTPException(401, "sign in first" if not who else f"needs role: {' or '.join(roles)}")
            return who
        return check

    @app.get("/health")
    def health():
        return {"claude": "on" if claude else "off (plain reports, keyword rules)",
                "calls": calls.name, "public_url": settings.public_base_url or None, **worker.health()}

    # ---------- rules ----------
    @app.post("/rules/interpret")
    async def interpret(body: dict, who: dict = Depends(caller("caregiver", "admin"))):
        room_id, text = str(body.get("room_id", "")), str(body.get("text", "")).strip()
        if not SAFE_ID.match(room_id) or not 1 <= len(text) <= 500:
            raise HTTPException(422, "need room_id and a rule of 1 to 500 characters")
        areas = [a["name"] for a in await stdb.sql(f"SELECT name FROM named_area WHERE room_id = {quoted(room_id)}")]
        result, drafted_by = None, "keyword match"
        if claude:
            try:
                data = await claude.draft_rule(text, areas)
                if data is not None:
                    result, drafted_by = ai.check_rule(data, areas), "claude"
            except Exception as e:
                log.warning("Claude rule draft failed, using the keyword match: %s", e)
        result = result or ai.keyword_rule(text, areas)
        if result.get("needs_drawing") or result.get("unclear_time"):
            return {"zone_draft_id": None, "area_name": None, "schedule": None, "severity": None, "escalation": None,
                    "needs_drawing": bool(result.get("needs_drawing")), "needs": "drawing" if result.get("needs_drawing") else "detail",
                    "question": result["question"], "drafted_by": drafted_by}

        async def drafts() -> set[str]:
            return {z["id"] for z in await stdb.sql(f"SELECT id FROM zone WHERE room_id = {quoted(room_id)} AND status = 'draft'")}
        before = await drafts()
        sch = result["schedule"]
        try:
            await stdb.call("save_zone_draft", [room_id, result["area_name"], [opt(sch["named"]), opt(sch["startMin"]), opt(sch["endMin"])],
                                                result["severity"], result["escalation"]])
        except Rejected as e:
            raise HTTPException(422, f"could not save the draft: {e}")
        new = sorted(await drafts() - before, key=lambda z: int(NUM.search(z).group(1)) if NUM.search(z) else 0)
        return {"zone_draft_id": new[-1] if new else None, "area_name": result["area_name"],
                "schedule": {"named": sch["named"], "start_min": sch["startMin"], "end_min": sch["endMin"]},
                "severity": result["severity"], "escalation": result["escalation"], "needs_drawing": False,
                "question": None, "drafted_by": drafted_by}

    # ---------- Garmin watch (garmin/ollo) ----------
    keys = watch_keys or WatchKeys(settings.watch_keys_file)

    @app.post("/watch/pair")
    async def watch_pair(who: dict = Depends(caller("caregiver"))):
        """A signed-in caregiver gets a pairing code for their watch (a new one replaces the old)."""
        cg = next((c for c in await stdb.sql("SELECT id, name FROM caregiver") if c["id"] == who["caregiverId"]), None)
        if cg is None:
            raise HTTPException(404, "no caregiver for this sign-in")
        return {"code": keys.pair(cg["id"]), "caregiver": cg["name"]}

    async def watch_caregiver(request: Request) -> dict:
        if keys.throttled():
            raise HTTPException(429, "too many wrong codes; wait a minute")
        cid = keys.who(request.headers.get("x-watch-key", ""))
        if cid is None:
            raise HTTPException(401, "unknown pairing code; pair the watch again from the dashboard")
        cg = next((c for c in await stdb.sql("SELECT id, name FROM caregiver") if c["id"] == cid), None)
        if cg is None:
            raise HTTPException(401, "that caregiver no longer exists")
        return cg

    @app.get("/watch/state")
    async def watch_get_state(request: Request):
        me = await watch_caregiver(request)
        alerts = await stdb.sql("SELECT * FROM alert WHERE status = 'notified' OR status = 'escalated' OR status = 'unanswered' OR status = 'owned'")
        zones = {z["id"]: z["name"] for z in await stdb.sql("SELECT id, name FROM zone")}
        labels = {p["trackId"]: p["label"] for p in await stdb.sql("SELECT track_id, label FROM track_position")}
        names = {c["id"]: c["name"] for c in await stdb.sql("SELECT id, name FROM caregiver")}
        return watch_state(me, alerts, zones, labels, names, worker.clock())

    @app.post("/watch/act")
    async def watch_act(request: Request, body: dict = Body(...)):
        me = await watch_caregiver(request)
        alert_id, decision = str(body.get("alert_id", "")), str(body.get("decision", ""))
        if not SAFE_ID.match(alert_id) or decision not in ("acknowledge", "decline"):
            raise HTTPException(422, "need alert_id and decision acknowledge or decline")
        try:
            await stdb.call("acknowledge_alert" if decision == "acknowledge" else "decline_alert", [alert_id, me["id"], "watch"])
        except Rejected as e:
            raise HTTPException(409, f"not recorded: {str(e)[:120]}")
        rows = await stdb.sql(f"SELECT owner_id, status FROM alert WHERE id = {quoted(alert_id)}")
        owner = rows[0]["ownerId"] if rows else None
        if decision == "acknowledge":
            if owner == me["id"]:
                return {"ok": True, "say": "You have it"}
            names = {c["id"]: c["name"] for c in await stdb.sql("SELECT id, name FROM caregiver")}
            return {"ok": True, "say": f"{names.get(owner, 'Someone')} has it" if owner else "Not recorded"}
        return {"ok": True, "say": "Next person told"}

    # ---------- key frames from the vision service ----------
    @app.post("/keyframes")
    async def put_keyframes(clip_ref: str = Form(...), frames: list[UploadFile] = File(...),
                            who: dict = Depends(caller("vision"))):
        data = [await f.read(1_500_001) for f in frames[:4]]
        problem = keyframes.check(clip_ref, data)
        if problem:
            raise HTTPException(422, problem)
        keyframes.put(clip_ref, data)
        return {"ok": True, "clip_ref": clip_ref, "frames": len(data)}

    # ---------- Twilio ----------
    def twilio() -> TwilioCalls:
        provider = calls if isinstance(calls, TwilioCalls) else getattr(calls, "fallback", None)     # the keypad call, alone or as the agent's fallback
        if not isinstance(provider, TwilioCalls):
            raise HTTPException(404, "real calls are not enabled")
        return provider

    async def signed_form(request: Request, job: str = "", token: str = "") -> dict:
        """Twilio's webhook form, checked. A signed request must carry a valid signature. Trial accounts' requests arrive
        UNSIGNED, so those are accepted only when everything below holds: the one-time token we put in the address
        belongs to this job, the account is ours, and Twilio confirms the call is one we placed from our number."""
        provider = twilio()
        form = {k: str(v) for k, v in (await request.form()).items()}
        signature = request.headers.get("x-twilio-signature")
        if signature:
            url = settings.public_base_url + request.url.path + (f"?{request.url.query}" if request.url.query else "")
            if valid_twilio_signature(provider.s.twilio_token, url, form, signature):
                return form
            log.warning("refused a Twilio webhook with a bad signature")
            raise HTTPException(403, "bad signature")
        known = bool(token) and provider.token_job.get(token) == job and provider.audio_for(token) is not None
        if known and form.get("AccountSid") == provider.s.twilio_sid and await provider.call_is_ours(form.get("CallSid", "")):
            return form
        log.warning("refused an unsigned Twilio webhook that did not match a call we placed")
        raise HTTPException(403, "not a call of ours")

    @app.get("/audio/{token}")
    def audio(token: str):
        wav = twilio().audio_for(token)
        if wav is None:
            raise HTTPException(404, "no such audio (it expires after 15 minutes)")
        return Response(wav, media_type="audio/wav", headers={"Cache-Control": "no-store"})

    @app.post("/webhooks/voice/ack")
    async def voice_ack(request: Request, body: dict = Body(...)):
        """The Cartesia voice agent's webhook tool `acknowledge_alert`: {token, decision: acknowledge | decline}."""
        secret = settings.voice_webhook_secret
        if not secret or not hmac.compare_digest(request.headers.get("authorization", ""), f"Bearer {secret}"):
            raise HTTPException(401, "bad secret")
        if not hasattr(calls, "take_token"):
            raise HTTPException(404, "the voice agent is not enabled")
        decision = str(body.get("decision", ""))
        if decision not in ("acknowledge", "decline"):
            raise HTTPException(422, "decision must be acknowledge or decline")
        return PlainTextResponse(await worker.on_voice_decision(str(body.get("token", "")), decision))

    @app.post("/twilio/voice")
    async def voice(request: Request, job: str, t: str):
        """Twilio fetches this when the call is answered: play the message, wait for one key press."""
        await signed_form(request, job, t)
        provider = twilio()
        if not SAFE_ID.match(job) or provider.audio_for(t) is None:
            raise HTTPException(404, "no such call")
        return Response(provider.twiml(job, t), media_type="application/xml")

    @app.post("/twilio/gather")
    async def gather(request: Request, job: str, t: str = ""):
        form = await signed_form(request, job, t)
        pressed = form.get("Digits", "") == "1"
        await worker.on_call_result(job, "pressed_1" if pressed else "no_answer")
        say = "Thank you. You are handling the alert now." if pressed else "Okay. ollo will keep trying other staff."
        return Response(f'<?xml version="1.0" encoding="UTF-8"?><Response><Say>{say}</Say><Hangup/></Response>',
                        media_type="application/xml")

    @app.post("/twilio/status")
    async def status(request: Request, job: str):
        form = await signed_form(request)
        outcome = twilio_outcome(form.get("CallStatus", ""))
        if outcome:
            await worker.on_call_result(job, outcome)
        return Response(status_code=204)

    return app
