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


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


class Calls:
    def __init__(self, data_dir):
        self.audio={}; self.data_dir=data_dir

    async def place(self, incident, step, armed, still_authorized=None, caregiver=''):
        if not armed or not ready():
            return {'status':'simulated','mode':'simulation','message':'Simulated phone escalation — no real call placed.'}
        numbers=allowed_numbers(); destination=numbers[min(step,len(numbers)-1)]
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
        base=os.environ['PUBLIC_CALLBACK_BASE_URL'].rstrip('/')
        text='This is a NestWatch alert for '+incident['room']+'. '+KINDS.get(incident['kind'],KINDS['boundary'])[1]+' Please check the room immediately. Press 1 to acknowledge, or 2 if you cannot respond.'
        async with httpx.AsyncClient(timeout=15) as client:
            response=await client.post('https://api.cartesia.ai/tts/bytes',headers={'Authorization':'Bearer '+os.environ['CARTESIA_API_KEY'],'Cartesia-Version':os.environ['CARTESIA_VERSION']},json={'model_id':os.environ['CARTESIA_MODEL_ID'],'transcript':text,'voice':os.environ['CARTESIA_VOICE_ID'],'output_format':{'container':'wav','encoding':'pcm_s16le','sample_rate':24000}})
            response.raise_for_status()
        token=secrets.token_urlsafe(32); self.audio[token]=(time.time()+900,response.content)
        twiml='<Response><Gather numDigits="1" timeout="8" action="'+escape(base+'/webhooks/twilio/digits')+'" method="POST"><Play>'+escape(base+'/call-media/'+token)+'</Play></Gather><Hangup/></Response>'
        from twilio.rest import Client
        def create():
            return Client(os.environ['TWILIO_ACCOUNT_SID'],os.environ['TWILIO_AUTH_TOKEN']).calls.create(to=destination,from_=os.environ['TWILIO_FROM_NUMBER'],twiml=twiml,status_callback=base+'/webhooks/twilio/status',status_callback_event=['initiated','ringing','answered','completed'],timeout=15)
        # A timeout is not retried: call creation may already have succeeded.
        if still_authorized is not None and not still_authorized():
            return {'status':'canceled','mode':'real','message':'Session changed before call creation.'}
        result=await asyncio.wait_for(asyncio.to_thread(create),timeout=20)
        return {'status':'initiated','mode':'real','provider':'twilio','call_sid':result.sid,'phone_last4':destination[-4:]}

    async def cancel(self, sid):
        if not sid or not os.getenv('TWILIO_AUTH_TOKEN'):return
        from twilio.rest import Client
        await asyncio.to_thread(lambda:Client(os.environ['TWILIO_ACCOUNT_SID'],os.environ['TWILIO_AUTH_TOKEN']).calls(sid).update(status='completed'))

    def valid_signature(self, url, form, signature):
        if not os.getenv('TWILIO_AUTH_TOKEN'):return False
        from twilio.request_validator import RequestValidator
        return RequestValidator(os.environ['TWILIO_AUTH_TOKEN']).validate(url,dict(form),signature or '')
