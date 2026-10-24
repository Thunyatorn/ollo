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


def test_video_upload_validation(tmp_path):
    import cv2
    import numpy as np
    path = tmp_path / 'clip.mp4'
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'mp4v'), 10, (160, 120))
    for i in range(20):
        writer.write(np.full((120, 160, 3), i * 10, dtype=np.uint8))
    writer.release()
    with TestClient(app) as client:
        client.get('/api/state')
        assert client.post('/api/video', files={'file': ('clip.gif', b'GIF89a', 'image/gif')}).status_code == 415
        assert client.post('/api/video', files={'file': ('bad.mp4', b'not a video', 'video/mp4')}).status_code == 422
        ok = client.post('/api/video', files={'file': ('clip.mp4', path.read_bytes(), 'video/mp4')})
        assert ok.status_code == 200 and ok.json()['session']['source_type'] == 'recorded'
        assert client.get(ok.json()['media_url']).status_code == 200


def test_frame_response_carries_overlays():
    import base64
    import cv2
    import numpy as np
    _, raw = cv2.imencode('.jpg', np.zeros((360, 640, 3), dtype=np.uint8))
    with TestClient(app) as client:
        client.get('/api/state')
        session = client.post('/api/session/start').json()['session']
        frame = {'session_id': session['id'], 'epoch': session['epoch'], 'frame_seq': 1, 'media_time_ms': 0, 'image': base64.b64encode(raw).decode()}
        body = client.post('/api/frames', json=frame).json()
        assert body['accepted'] is True and isinstance(body['overlays'], list)
        again = client.post('/api/frames', json=frame)  # Same sequence number: rejected as busy (200) or stale (409).
        assert again.status_code == 409 or again.json()['accepted'] is False


def test_calibration_endpoint():
    corners = [((0.1, 0.1), (0.8, 0.8)), ((0.9, 0.1), (7.2, 0.8)), ((0.9, 0.9), (7.2, 7.2)), ((0.1, 0.9), (0.8, 7.2)), ((0.5, 0.5), (4.0, 4.0))]
    points = [{'image': list(i), 'floor': list(f)} for i, f in corners]
    with TestClient(app) as client:
        client.get('/api/state')
        saved = client.post('/api/calibration', json={'points': points})
        assert saved.status_code == 200
        calibration = saved.json()['settings']['calibration']
        assert calibration['error_m'] < 0.01 and calibration['ignored'] == []
        assert saved.json()['camera']['predictive'] == 'active'
        typo = [dict(p) for p in points]
        typo[4] = {'image': [0.5, 0.5], 'floor': [4.6, 4.0]}
        rejected = client.post('/api/calibration', json={'points': typo})
        assert rejected.status_code == 422 and 'Point 5' in rejected.json()['detail']
        assert client.get('/api/state').json()['settings']['calibration'] == calibration  # Nothing saved on rejection.
        assert client.post('/api/calibration', json={'points': points[:3]}).status_code == 422
        cleared = client.delete('/api/calibration').json()
        assert 'calibration' not in cleared['settings'] and cleared['camera']['predictive'] == 'needs calibration'


def test_approach_observation_logs_event_not_incident(monkeypatch):
    import asyncio
    import server.app as api
    with TestClient(app) as client:
        client.get('/api/state')
        session = client.post('/api/session/reset').json()['session']
    class Stub:
        async def process_frame(self, frame):
            return {'overlays': [], 'observations': [{'kind': 'approach', 'observations': ['Person 4 is heading for the restricted area.'], 'origin': 'local_rule', 'priority': 'medium'}]}
    monkeypatch.setattr(api, 'vision', Stub())
    before = len(api.store.incidents())
    asyncio.run(api.process_frame({'session_id': session['id'], 'epoch': session['epoch'], 'frame_seq': 1, 'media_time_ms': 0, 'image': ''}))
    assert len(api.store.incidents()) == before
    event = api.store.events()[0]
    assert event['type'] == 'approach_warning' and 'Person 4' in event['message']


def test_mobile_acknowledgment_records_app_channel():
    with TestClient(app) as client:
        client.get('/api/state')
        client.post('/api/session/reset')
        incident = client.post('/api/demo/scenario', json={'scenario': 'distress'}).json()['incidents'][0]
        assert client.post(f"/api/incidents/{incident['id']}/acknowledge", json={'actor': 'Maya Chen', 'channel': 'voice'}).status_code == 422
        acked = client.post(f"/api/incidents/{incident['id']}/acknowledge", json={'actor': 'Maya Chen', 'channel': 'app'}).json()['incident']
        assert acked['assigned_responder'] == 'Maya Chen' and acked['acknowledged_via'] == 'app'
