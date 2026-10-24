import threading
import time
from server.store import Store


def test_concurrent_reads_and_writes_never_fail(tmp_path):
    # Mirrors the server: /api/state reads in worker threads while the coordinator and frames write.
    store=Store(tmp_path/'test.sqlite3');session=store.get('session');session['status']='active';store.put('session',session)
    store.put('settings',{**store.get('settings'),'primary_delay_seconds':0,'backup_delay_seconds':0})
    errors=[];stop=threading.Event()

    def guarded(work):
        def run():
            try:
                while not stop.is_set(): work()
            except Exception as error:
                errors.append(repr(error));stop.set()
        return threading.Thread(target=run)

    seq=iter(range(1,10**9))
    def write():
        incident=store.observe('fall',['Dropped quickly'],'local_rule')
        store.accept_frame({'session_id':session['id'],'epoch':session['epoch'],'frame_seq':next(seq)})
        store.event('frame_note','still writing',incident['id'])
        store.put('settings',store.get('settings'))
        job=store.claim_due()
        if job: store.finish_job(job['id'],'completed',{'sid':'CA1'})
        if incident['status']=='open': store.transition(incident['id'],'acknowledge','Alex')
        elif incident['status']=='acknowledged': store.transition(incident['id'],'resolve','Alex')

    def read():
        for incident in store.incidents():
            assert store.incident(incident['id'])['id']==incident['id']
            store.incident_events(incident['id'])
        assert all('seq' in event for event in store.events())
        assert all(isinstance(attempt['payload'],dict) for attempt in store.attempts())
        assert store.get('session')['id']==session['id']

    threads=[guarded(write)]+[guarded(read) for _ in range(4)]
    for thread in threads: thread.start()
    time.sleep(2);stop.set()
    for thread in threads: thread.join(5)
    assert not errors,errors[:5]
