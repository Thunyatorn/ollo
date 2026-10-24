"""Optional real-call adapter. Configuration alone never arms calls."""
import asyncio
import os
import secrets
import time
from xml.sax.saxutils import escape
import httpx


def allowed_numbers():
    return [x.strip() for x in os.getenv('CALL_ALLOWLIST','').split(',') if x.strip()]


def ready():
    required=['TWILIO_ACCOUNT_SID','TWILIO_AUTH_TOKEN','TWILIO_FROM_NUMBER','PUBLIC_CALLBACK_BASE_URL','CARTESIA_API_KEY','CARTESIA_VOICE_ID','CARTESIA_MODEL_ID','CARTESIA_VERSION']
    return os.getenv('CALLS_ENABLED','false').lower()=='true' and all(os.getenv(k) for k in required) and bool(allowed_numbers()) and os.getenv('PUBLIC_CALLBACK_BASE_URL','').startswith('https://')


class Calls:
    def __init__(self, data_dir):
        self.audio={}; self.data_dir=data_dir

    async def place(self, incident, step, armed, still_authorized=None):
        if not armed or not ready():
            return {'status':'simulated','mode':'simulation','message':'Simulated phone escalation — no real call placed.'}
        numbers=allowed_numbers(); destination=numbers[min(step,len(numbers)-1)]
        # Phone destinations come only from server-side environment configuration.
        if not destination.startswith('+') or not destination[1:].isdigit() or not 8<=len(destination)<=16:raise ValueError('Invalid allowlisted E.164 destination')
        base=os.environ['PUBLIC_CALLBACK_BASE_URL'].rstrip('/')
        text='This is a Lookout demo alert for '+incident['room']+'. '+('Possible distress was observed.' if incident['kind']=='distress' else 'Restricted-area activity was observed.')+' Please check the room immediately. Press 1 to acknowledge, or 2 if you cannot respond.'
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
        return {'status':'initiated','mode':'real','call_sid':result.sid,'phone_last4':destination[-4:]}

    async def cancel(self, sid):
        if not sid or not os.getenv('TWILIO_AUTH_TOKEN'):return
        from twilio.rest import Client
        await asyncio.to_thread(lambda:Client(os.environ['TWILIO_ACCOUNT_SID'],os.environ['TWILIO_AUTH_TOKEN']).calls(sid).update(status='completed'))

    def valid_signature(self, url, form, signature):
        if not os.getenv('TWILIO_AUTH_TOKEN'):return False
        from twilio.request_validator import RequestValidator
        return RequestValidator(os.environ['TWILIO_AUTH_TOKEN']).validate(url,dict(form),signature or '')
