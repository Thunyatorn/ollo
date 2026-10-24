"""SRC-5 several server cameras at once. Fake cameras stand in for cv2.VideoCapture; tests never open a real camera."""
import base64
import json
import time

from fastapi.testclient import TestClient

import server.capture as capture_module
from server.tests.test_capture import FakeCamera, wait_until
from server.vision import VisionEngine, jpeg_dimensions

PERSON = [{'x': .3, 'y': .2, 'width': .2, 'height': .6}]
URLS = {'rtsp://127.0.0.1:8554/daycare': 'cam-01', 'rtsp://127.0.0.1:8554/bourbon': 'cam-02', 'https://cams.example/times/index.m3u8': 'cam-03'}


def fake_cameras(monkeypatch):
    """One fake camera per source URL; a fast stand-in detector (the real engine still orders, rates and overlays frames)."""
    made = {}

    def opener(source):
        made[source] = FakeCamera(fps=30)
        return made[source]

    monkeypatch.setattr(capture_module, 'open_camera', opener)
    monkeypatch.setattr(VisionEngine, '_detect', lambda self, jpeg: (PERSON, 'active'))
    monkeypatch.setattr(VisionEngine, 'warm', lambda self: None)
    return made


def test_several_server_cameras_analyze_independently(monkeypatch):
    import server.app as api
    made = fake_cameras(monkeypatch)
    with TestClient(api.app) as client:
        client.get('/api/state')
        try:
            (first, second, third) = URLS
            assert client.post('/api/source', json={'source_type': 'server_camera', 'camera': first}).status_code == 200
            client.put('/api/settings', json={'room_label': 'Toddler room'})
            session = client.post('/api/session/start').json()['session']
            for url, room in ((second, 'Front door'), (third, 'Gas station')):
                added = client.post('/api/cameras', json={'camera': url, 'room_label': room})
                assert added.status_code == 200, added.text
            # Adding cameras never resets the session.
            assert client.get('/api/state').json()['session']['id'] == session['id']
            # Each camera is analyzed at the capture rate, with no browser and no shared "busy" flag.
            def rates():
                return {c['id']: c['analysis_fps'] for c in client.get('/api/cameras').json()['cameras']}
            assert wait_until(lambda: len(rates()) == 3 and all(r >= 10 for r in rates().values()), 6) is not None, rates()
            listed = client.get('/api/state').json()['cameras']
            assert [c['id'] for c in listed] == ['cam-01', 'cam-02', 'cam-03']
            assert [c['room_label'] for c in listed] == ['Toddler room', 'Front door', 'Gas station']
            assert all(c['health'] == 'active' and c['capture']['status'] == 'live' and c['capture']['camera_fps'] >= 15 for c in listed), listed  # Exact rates are SRC-4's test
            assert listed[0]['primary'] and not listed[1]['primary'] and all(c['people'] == 1 for c in listed)
            # Each camera's picture comes with the overlays computed from that picture.
            for camera in ('cam-01', 'cam-02', 'cam-03'):
                view = client.get('/api/camera/frame', params={'camera': camera, 'after': -1}).json()
                assert jpeg_dimensions(base64.b64decode(view['image'])) == (640, 360)
                assert view['overlays'] and view['overlays'][0]['media_time_ms'] == view['media_time_ms']
                assert view['overlays'][0]['epoch'] == session['epoch']
            assert client.get('/api/camera/frame', params={'camera': 'cam-09'}).status_code == 404
            assert client.get('/api/camera/frame').status_code == 200  # Default is cam-01, as in SRC-4.
            # One camera stalling takes only that camera offline.
            made[second].stalled = True
            assert wait_until(lambda: client.get('/api/state').json()['cameras'][1]['health'] == 'offline', 4) is not None
            others = client.get('/api/state').json()['cameras']
            assert others[0]['health'] == 'active' and others[2]['health'] == 'active'
            # Logged on that capture's next tick (1/12 s), naming the room.
            assert wait_until(lambda: any('Front door' in e['message'] for e in client.get('/api/state').json()['events'] if e['type'] == 'camera_offline'), 1) is not None
            made[second].stalled = False
            assert wait_until(lambda: client.get('/api/state').json()['cameras'][1]['health'] == 'active', 4) is not None
        finally:
            for camera in made.values():
                camera.finished = True
            client.post('/api/session/reset')


def test_camera_api_validation_removal_and_release(monkeypatch):
    import server.app as api
    made = fake_cameras(monkeypatch)
    with TestClient(api.app) as client:
        client.get('/api/state')
        try:
            client.post('/api/session/reset')
            first, second, third = URLS
            # Only alongside a server camera session.
            assert client.post('/api/cameras', json={'camera': second}).status_code == 409
            client.post('/api/source', json={'source_type': 'server_camera', 'camera': first})
            client.post('/api/session/start')
            for bad in ('file:///etc/passwd', 'ftp://cam/x', '12', ''):
                assert client.post('/api/cameras', json={'camera': bad}).status_code == 422
            assert client.post('/api/cameras', json={'camera': first}).status_code == 409  # Already cam-01.
            assert client.post('/api/cameras', json={'camera': second, 'room_label': 'x' * 81}).status_code == 422
            assert client.post('/api/cameras', json={'camera': 'rtsp://nest:secret@10.0.0.7/live'}).status_code == 200
            state = client.get('/api/state').json()
            assert 'secret' not in json.dumps(state) and state['cameras'][1]['capture']['source'] == 'rtsp://nest:***@10.0.0.7/live'
            assert state['cameras'][1]['room_label'] == 'Camera 02'
            client.post('/api/cameras', json={'camera': second})
            client.post('/api/cameras', json={'camera': third})
            assert client.post('/api/cameras', json={'camera': 'rtsp://10.0.0.9/five'}).status_code == 409  # At most 4.
            assert client.delete('/api/cameras/cam-01').status_code == 409
            assert client.delete('/api/cameras/cam-07').status_code == 404
            removed = client.delete('/api/cameras/cam-03').json()
            assert [c['id'] for c in removed['cameras']] == ['cam-01', 'cam-02', 'cam-04']
            assert wait_until(lambda: made[second].released, 1) is not None
            assert client.get('/api/camera/frame', params={'camera': 'cam-03'}).status_code == 404
            # The freed ID is reused; the other cameras kept running.
            assert [c['id'] for c in client.post('/api/cameras', json={'camera': second}).json()['cameras']] == ['cam-01', 'cam-02', 'cam-03', 'cam-04']
            assert 'camera_removed' in [e['type'] for e in client.get('/api/state').json()['events']]
            # Another source stops and releases every camera.
            client.post('/api/demo/scenario', json={'scenario': 'normal'})
            assert wait_until(lambda: all(c.released for c in made.values()), 2) is not None
            assert [c['id'] for c in client.get('/api/state').json()['cameras']] == ['cam-01']
        finally:
            for camera in made.values():
                camera.finished = True
            client.post('/api/session/reset')


def test_incidents_are_tagged_and_deduplicated_per_camera():
    import server.app as api
    with TestClient(api.app) as client:
        client.get('/api/state')
        client.post('/api/session/reset')
        store = api.store
        primary = store.observe('fall', ['Possible fall.'], 'local_rule', 'high')
        door = store.observe('fall', ['Possible fall at the door.'], 'local_rule', 'high', camera={'id': 'cam-02', 'room': 'Front door'})
        assert primary['id'] != door['id'], 'The same kind on two cameras is two incidents'
        assert primary['camera_id'] == 'cam-01' and door['camera_id'] == 'cam-02' and door['room'] == 'Front door'
        again = store.observe('fall', ['Still down.'], 'local_rule', 'high', camera={'id': 'cam-02', 'room': 'Front door'})
        assert again['id'] == door['id'] and 'Still down.' in again['observations']
        review = {'assessment': 'insufficient_view', 'observations': []}
        assert store.annotate('fall', review, 'cam-02')['id'] == door['id']
        assert 'second_opinion' not in store.incident(primary['id'])
        assert 'Front door' in [e['message'] for e in store.events() if e['type'] == 'incident_opened'][0]
        # Zones, calibration and rules belong to cam-01's picture and never apply to other cameras.
        settings = {'zone': {'enabled': True, 'vertices': [[0, 0], [1, 0], [1, 1]]}, 'calibration': {}, 'rules': [1], 'landmarks': [1], 'stillness_seconds': 45, 'nap_mode': True}
        extra = api.extra_settings(settings)
        assert extra['zone']['enabled'] is False and not {'calibration', 'rules', 'landmarks'} & set(extra)
        assert extra['stillness_seconds'] == 45 and extra['nap_mode'] is True and settings['zone']['enabled'] is True
        client.post('/api/session/reset')
