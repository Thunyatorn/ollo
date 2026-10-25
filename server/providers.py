"""Optional real-call adapters. Configuration alone never arms calls.

Providers: `twilio` (Cartesia voice message, keypad 1 or 2) and `cartesia_agent` (a
Cartesia voice agent that understands "I'm on it" and calls /webhooks/voice/ack). A failed
agent call falls back to the keypad call when Twilio is configured.
"""
import asyncio
import hashlib
import os
import secrets
import time
from xml.sax.saxutils import escape
import httpx

from .store import KINDS

CARTESIA_AGENT_CALLS = 'https://api.cartesia.ai/agents/calls'


def allowed_numbers():
    return [x.strip() for x in os.getenv('CALL_ALLOWLIST','').split(',') if x.strip()]


def provider():
    return os.getenv('CALL_PROVIDER','twilio')


def _base_ready():
    return os.getenv('CALLS_ENABLED','false').lower()=='true' and bool(allowed_numbers()) and os.getenv('PUBLIC_CALLBACK_BASE_URL','').startswith('https://')


def twilio_ready():
    required=['TWILIO_ACCOUNT_SID','TWILIO_AUTH_TOKEN','TWILIO_FROM_NUMBER','CARTESIA_API_KEY','CARTESIA_VOICE_ID','CARTESIA_MODEL_ID','CARTESIA_VERSION']
    return _base_ready() and all(os.getenv(k) for k in required)


def agent_ready():
    required=['CARTESIA_API_KEY','CARTESIA_AGENT_ID','CARTESIA_FROM_NUMBER_ID','VOICE_WEBHOOK_SECRET']
    return _base_ready() and all(os.getenv(k) for k in required)


def ready():
    return (agent_ready() or twilio_ready()) if provider()=='cartesia_agent' else twilio_ready()


def _twilio_url(path):
    return 'https://api.twilio.com/2010-04-01/Accounts/'+os.environ['TWILIO_ACCOUNT_SID']+path


def _twilio_auth():
    return (os.environ['TWILIO_ACCOUNT_SID'],os.environ['TWILIO_AUTH_TOKEN'])


def _twilio_reason(response):
    """Twilio's own reason for a refusal (code and message), so the event log says what to fix."""
    try:
        body=response.json()
        return f"Twilio {response.status_code} {body.get('code','')}: {body.get('message','')}"[:200]
    except ValueError:
        return f'Twilio {response.status_code}'


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


class Calls:
    def __init__(self, data_dir):
        self.audio={}; self.data_dir=data_dir; self._trial=None
        self.pending={}       # call token -> (expires, speech task, text): ESC-5, speech made while the phone rings
        self.speech_cache={}  # message text -> Cartesia audio, so one message never asks Cartesia twice
        self.speech_wait=10.0
        self._callback_ok_at=0.0   # last time PUBLIC_CALLBACK_BASE_URL answered /health (ESC-1)

    def forget_callback_check(self):
        self._callback_ok_at=0.0

    async def callback_problem(self):
        """ESC-1: None when Twilio can reach this server through PUBLIC_CALLBACK_BASE_URL, else what to fix.
        A success is trusted for 30 s; a failure is never cached, so starting the tunnel fixes it at once."""
        if time.time()-self._callback_ok_at<30:return None
        base=os.getenv('PUBLIC_CALLBACK_BASE_URL','').rstrip('/')
        try:
            async with httpx.AsyncClient(timeout=6) as client:
                response=await client.get(base+'/health')
            ok=response.status_code==200 and response.json().get('status')=='ok'
        except (httpx.HTTPError,ValueError):
            ok=False
        if ok:
            self._callback_ok_at=time.time();return None
        return f'Twilio cannot reach this server at {base}: start the tunnel in a terminal (ngrok http 127.0.0.1:8000 --pooling-enabled), then try again.'

    def message(self, incident):
        return 'This is an ollo alert for '+incident['room']+'. '+KINDS.get(incident['kind'],KINDS['boundary'])[1]+' Please check the room immediately. Press 1 to acknowledge, or 2 if you cannot respond.'

    async def speech(self, text):
        """Cartesia audio for a message, reused once made."""
        if text in self.speech_cache:return self.speech_cache[text]
        async with httpx.AsyncClient(timeout=20) as client:
            response=await client.post('https://api.cartesia.ai/tts/bytes',headers={'Authorization':'Bearer '+os.environ['CARTESIA_API_KEY'],'Cartesia-Version':os.environ['CARTESIA_VERSION']},json={'model_id':os.environ['CARTESIA_MODEL_ID'],'transcript':text,'voice':os.environ['CARTESIA_VOICE_ID'],'output_format':{'container':'wav','encoding':'pcm_s16le','sample_rate':24000}})
            response.raise_for_status()
        self.speech_cache[text]=response.content
        return response.content

    async def prepare(self, room):
        """ESC-5, on arming: learn the account type and make the speech for every alert kind, off the alert path."""
        async with httpx.AsyncClient(timeout=15) as client:
            await self._is_trial(client)
        await asyncio.gather(*(self.speech(self.message({'room':room,'kind':kind})) for kind in KINDS),return_exceptions=True)

    async def audio_for(self, token):
        """The call's audio, waiting for speech still being made; None if unknown, expired or failed."""
        entry=self.audio.get(token)
        if entry and entry[0]>=time.time():return entry[1]
        pending=self.pending.get(token)
        if not pending or pending[0]<time.time():return None
        try:
            audio=await asyncio.wait_for(asyncio.shield(pending[1]),self.speech_wait)
        except Exception:
            return None
        self.audio[token]=(pending[0],audio)
        return audio

    async def place(self, incident, step, armed, still_authorized=None, caregiver=''):
        if not armed or not ready():
            return {'status':'simulated','mode':'simulation','message':'Simulated phone escalation — no real call placed.'}
        numbers=allowed_numbers(); destination=numbers[min(step,len(numbers)-1)]
        problem=await self.callback_problem()
        if problem:return {'status':'failed','mode':'real','message':problem}   # no phone rings into a dead tunnel
        # Phone destinations come only from server-side environment configuration.
        if not destination.startswith('+') or not destination[1:].isdigit() or not 8<=len(destination)<=16:raise ValueError('Invalid allowlisted E.164 destination')
        if provider()=='cartesia_agent' and agent_ready():
            try:
                result=await self._place_agent(incident,step,destination,caregiver,still_authorized)
            except (httpx.HTTPError,ValueError,KeyError) as exc:
                result={'status':'failed','mode':'real','provider':'cartesia_agent','message':type(exc).__name__}
            if result['status']!='failed' or not twilio_ready():
                return result
            fallback=await self._place_twilio(incident,step,destination,still_authorized)
            return {**fallback,'fallback_from':'cartesia_agent','fallback_reason':result.get('message','')}
        return await self._place_twilio(incident,step,destination,still_authorized)

    async def _place_agent(self, incident, step, destination, caregiver, still_authorized=None):
        """Cartesia voice agent call; its webhook tool presents a single-use token to /webhooks/voice/ack."""
        token=secrets.token_urlsafe(24)
        if still_authorized is not None and not still_authorized():
            return {'status':'canceled','mode':'real','provider':'cartesia_agent','message':'Session changed before call creation.'}
        variables={'room':incident['room'],'alert':incident.get('title') or KINDS.get(incident['kind'],KINDS['boundary'])[0],'caregiver':caregiver or 'caregiver','ack_token':token}
        async with httpx.AsyncClient(timeout=15) as client:
            response=await client.post(CARTESIA_AGENT_CALLS,headers={'X-API-Key':os.environ['CARTESIA_API_KEY'],'Cartesia-Version':os.getenv('CARTESIA_VERSION','2026-08-14')},
                json={'agent_id':os.environ['CARTESIA_AGENT_ID'],'from_number_id':os.environ['CARTESIA_FROM_NUMBER_ID'],'ringing_timeout_seconds':30,'outbound_calls':[{'to_number':destination,'dynamic_variables':variables}]})
            response.raise_for_status()
        entry=(response.json().get('calls') or [{}])[0]
        if not entry.get('agent_call_id'):
            return {'status':'failed','mode':'real','provider':'cartesia_agent','message':str(entry.get('error','No call created'))[:200]}
        # Only the hash is stored; the raw token lives in the call's dynamic variables.
        return {'status':'initiated','mode':'real','provider':'cartesia_agent','agent_call_id':entry['agent_call_id'],'ack_token_sha256':token_hash(token),'phone_last4':destination[-4:]}

    async def _place_twilio(self, incident, step, destination, still_authorized=None):
        """ESC-2/ESC-4/ESC-5: Twilio fetches the instructions from /webhooks/twilio/voice/<token>; Cartesia speech is made meanwhile.
        Trial accounts refuse inline TwiML and status callbacks, so those are only sent on paid accounts."""
        base=os.environ['PUBLIC_CALLBACK_BASE_URL'].rstrip('/')
        text=self.message(incident);token=secrets.token_urlsafe(32)
        # ESC-5: dial first. Twilio asks for the audio only once the phone is answered.
        speech=asyncio.create_task(self.speech(text));speech.add_done_callback(lambda task:task.cancelled() or task.exception())
        self.pending[token]=(time.time()+900,speech,text)
        async with httpx.AsyncClient(timeout=15) as client:
            form={'To':destination,'From':os.environ['TWILIO_FROM_NUMBER'],'Url':base+'/webhooks/twilio/voice/'+token}
            if not await self._is_trial(client):
                form.update({'Timeout':'15','StatusCallback':base+'/webhooks/twilio/status','StatusCallbackMethod':'POST','StatusCallbackEvent':['initiated','ringing','answered','completed']})
            if still_authorized is not None and not still_authorized():
                return {'status':'canceled','mode':'real','message':'Session changed before call creation.'}
            # A timeout is not retried: call creation may already have succeeded.
            created=await client.post(_twilio_url('/Calls.json'),data=form,auth=_twilio_auth())
        if created.status_code>=400:
            return {'status':'failed','mode':'real','provider':'twilio','message':_twilio_reason(created)}
        return {'status':'initiated','mode':'real','provider':'twilio','call_sid':created.json()['sid'],'call_token_sha256':token_hash(token),'phone_last4':destination[-4:]}

    async def _is_trial(self, client):
        """Twilio account type, checked once. Unknown counts as trial, the stricter case."""
        if self._trial is None:
            try:
                response=await client.get(_twilio_url('.json'),auth=_twilio_auth())
            except httpx.HTTPError:
                return True
            self._trial=response.status_code!=200 or response.json().get('type','Trial')=='Trial'
        return self._trial

    async def twiml(self, token):
        """The call instructions for /webhooks/twilio/voice/<token>, or None for an unknown or expired token.
        If the Cartesia speech failed or is late, Twilio's own voice reads the same message (ESC-5)."""
        known=[entry for entry in (self.audio.get(token),self.pending.get(token)) if entry and entry[0]>=time.time()]
        if not known:return None
        base=os.environ['PUBLIC_CALLBACK_BASE_URL'].rstrip('/')
        spoken='<Play>'+escape(base+'/call-media/'+token)+'</Play>' if await self.audio_for(token) else '<Say>'+escape(self.pending[token][2])+'</Say>'
        return '<?xml version="1.0" encoding="UTF-8"?><Response><Gather numDigits="1" timeout="8" action="'+escape(base+'/webhooks/twilio/digits/'+token)+'" method="POST">'+spoken+'</Gather><Hangup/></Response>'

    async def call_status(self, sid):
        """ESC-4: Twilio's status for a call we placed (no status callbacks on trial accounts), or None if unreadable."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response=await client.get(_twilio_url('/Calls/'+sid+'.json'),auth=_twilio_auth())
        except httpx.HTTPError:
            return None
        return response.json().get('status') if response.status_code==200 else None

    async def cancel(self, sid):
        if not sid or not os.getenv('TWILIO_AUTH_TOKEN'):return
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(_twilio_url('/Calls/'+sid+'.json'),data={'Status':'completed'},auth=_twilio_auth())

    def valid_signature(self, url, form, signature):
        if not os.getenv('TWILIO_AUTH_TOKEN'):return False
        from twilio.request_validator import RequestValidator
        return RequestValidator(os.environ['TWILIO_AUTH_TOKEN']).validate(url,dict(form),signature or '')
