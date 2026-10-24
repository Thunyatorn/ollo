import os
import tempfile
os.environ['DATA_DIR']=tempfile.mkdtemp(prefix='lookout-test-')
os.environ['CALLS_ENABLED']='false'
from fastapi.testclient import TestClient
from server.app import app
from server.providers import Calls


def test_auth_and_fixture_flow():
    with TestClient(app) as client:
        assert client.post('/api/demo/scenario',json={'scenario':'boundary'}).status_code==401
        initial=client.get('/api/state');assert initial.status_code==200
        assert initial.json()['call_provider']['mode']=='simulation'
        assert client.post('/api/session/arm-calls',json={'armed':True}).status_code==409
        result=client.post('/api/demo/scenario',json={'scenario':'distress','media_time_ms':30500}).json()
        incident=result['incidents'][0];assert incident['origin']=='fixture'
        assert incident['media_time_ms']==30500
        identifier=incident['id']
        assert client.post(f'/api/incidents/{identifier}/resolve',json={}).status_code==409
        assert client.post(f'/api/incidents/{identifier}/acknowledge',json={'actor':'Test teammate'}).status_code==200
        assert client.post(f'/api/incidents/{identifier}/resolve',json={}).status_code==200
        assert client.post('/api/session/reset').json()['session']['calls_armed'] is False
        assert client.post('/webhooks/twilio/digits',data={'CallSid':'forged','Digits':'1'}).status_code==403
        assert client.get('/api/state',headers={'Origin':'https://attacker.example'}).status_code==403


def test_simulation_cannot_place_call(monkeypatch):
    import asyncio
    monkeypatch.setenv('CALLS_ENABLED','true')
    monkeypatch.setenv('CALL_ALLOWLIST','+15551234567')
    calls=Calls(None)
    result=asyncio.run(calls.place({'room':'Demo','kind':'boundary'},0,False))
    assert result['status']=='simulated'


def test_signed_callbacks_order_and_answer_is_not_ack(monkeypatch):
    from server.app import store
    from twilio.request_validator import RequestValidator
    monkeypatch.setenv('TWILIO_AUTH_TOKEN','test-secret')
    monkeypatch.setenv('PUBLIC_CALLBACK_BASE_URL','https://lookout.example')
    with TestClient(app) as client:
        client.get('/api/state');client.post('/api/session/reset')
        incident=client.post('/api/demo/scenario',json={'scenario':'boundary'}).json()['incidents'][0]
        job=dict(store.db.execute('SELECT * FROM jobs WHERE incident_id=? AND step=0',(incident['id'],)).fetchone())
        store.finish_job(job['id'],'ringing',{'call_sid':'CA-test','mode':'real'})
        def callback(status):
            data={'CallSid':'CA-test','CallStatus':status}
            signature=RequestValidator('test-secret').compute_signature('https://lookout.example/webhooks/twilio/status',data)
            return client.post('/webhooks/twilio/status',data=data,headers={'X-Twilio-Signature':signature})
        assert callback('initiated').status_code==200
        attempt=next(a for a in store.attempts() if a['id']==job['id'])
        assert attempt['status']=='ringing'
        assert callback('completed').status_code==200
        assert store.incident(incident['id'])['status']=='open'
        assert callback('ringing').status_code==200
        attempt=next(a for a in store.attempts() if a['id']==job['id'])
        assert attempt['status']=='completed'
