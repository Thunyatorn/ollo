import threading
import time
from server.store import Store


def test_incident_dedupe_and_lifecycle(tmp_path):
    store=Store(tmp_path/'test.sqlite3')
    first=store.observe('boundary',['Crossed doorway'],'local_rule')
    second=store.observe('boundary',['Still in zone'],'local_rule')
    assert first['id']==second['id']
    assert len(store.db.execute('SELECT * FROM jobs').fetchall())==2
    store.transition(first['id'],'acknowledge','Alex')
    # Repeated acknowledgment cannot change the selected first responder.
    assert store.transition(first['id'],'acknowledge','Jamie')['assigned_responder']=='Alex'
    assert all(a['status']=='canceled' for a in store.attempts())
    store.transition(first['id'],'resolve','Alex')
    assert store.observe('boundary',['Still in zone'])['status']=='resolved'


def test_reset_invalidates_frames_and_jobs(tmp_path):
    store=Store(tmp_path/'test.sqlite3');session=store.get('session');session['status']='active';store.put('session',session)
    frame={'session_id':session['id'],'epoch':session['epoch'],'frame_seq':1}
    assert store.accept_frame(frame)
    assert not store.accept_frame(frame)
    store.observe('distress',['Possible concerning gesture'])
    store.reset()
    assert not store.accept_frame({**frame,'frame_seq':2})
    assert not store.get('session')['calls_armed']
    assert store.claim_due() is None


def test_durable_single_job_claim(tmp_path):
    path=tmp_path/'test.sqlite3';store=Store(path)
    store.observe('boundary',['Entry'])
    with store.db:store.db.execute('UPDATE jobs SET due=?',(time.time()-1,))
    # Restart preserves deadlines but always disarms real calls.
    other=Store(path)
    first=other.claim_due(); second=other.claim_due();third=other.claim_due()
    assert first and second and first['id']!=second['id'] and third is None
    restarted=Store(path)
    assert all(a['status']=='unknown' for a in restarted.attempts())


def test_resolve_requires_acknowledgment(tmp_path):
    store=Store(tmp_path/'test.sqlite3');incident=store.observe('distress',['Gesture'])
    import pytest
    with pytest.raises(ValueError):store.transition(incident['id'],'resolve')


def test_decline_expedites_only_one_backup_and_rejects_stale(tmp_path):
    import pytest
    store=Store(tmp_path/'test.sqlite3');incident=store.observe('boundary',['Doorway'])
    first=store.decline(incident['id'],'Alex')
    second=store.decline(incident['id'],'Alex')
    assert first['revision']==second['revision']
    assert sum(e['type']=='caregiver_declined' for e in store.events())==1
    backup=store.claim_due()
    assert backup['step']==1
    assert store.claim_due() is None
    store.reset()
    with pytest.raises(ValueError):store.decline(incident['id'],'Alex')
