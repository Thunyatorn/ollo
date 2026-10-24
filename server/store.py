"""Small transactional SQLite coordinator. No provider secrets or phone numbers stored."""
import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path


def uid():
    return uuid.uuid4().hex


# Incident kind → (title, spoken phrase for calls, limitations shown with the evidence).
KINDS = {
    'boundary': ('Restricted-area activity', 'Restricted-area activity was observed.', []),
    'distress': ('Possible distress / choking concern', 'Possible distress was observed.', ['Airway status cannot be determined from video.']),
    'fall': ('Possible fall', 'A possible fall was observed.', ['Injury cannot be determined from video.']),
    'rhythmic': ('Unusual rhythmic movement', 'Unusual rhythmic movement was observed.', ['Not a seizure diagnosis. Consciousness and cause cannot be determined from video.']),
    'stillness': ('Prolonged stillness', 'A child has been very still for a long time.', ['Breathing cannot be determined from video.']),
}


class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS incidents (id TEXT PRIMARY KEY,session_id TEXT,epoch INTEGER,kind TEXT,status TEXT,payload TEXT,opened REAL);
        CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY,incident_id TEXT,step INTEGER,due REAL,status TEXT,payload TEXT,UNIQUE(incident_id,step));
        CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT,type TEXT,message TEXT,at REAL);
        ''')
        if 'incident_id' not in [c[1] for c in self.db.execute('PRAGMA table_info(events)')]:
            self.db.execute('ALTER TABLE events ADD COLUMN incident_id TEXT')  # Older databases.
        if not self.get('session'):
            self.put('session', {'id': uid(), 'epoch': 1, 'status': 'paused', 'calls_armed': False, 'source_type': 'demo', 'frame_seq': -1})
        session = self.get('session'); session['calls_armed'] = False; self.put('session', session)
        self.db.execute("UPDATE jobs SET status='unknown' WHERE status='initiating'")
        self.db.commit()
        if not self.get('settings'):
            self.put('settings', {'room_label': 'Toddler room', 'primary_delay_seconds': 8, 'backup_delay_seconds': 30, 'cloud_review_enabled': False, 'zone': {'enabled': True, 'vertices': [[.72,.15],[.94,.15],[.94,.88],[.72,.88]]}, 'audio_enabled': False})

    def get(self, key):
        row = self.db.execute('SELECT value FROM kv WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, key, value):
        with self.lock, self.db:
            self.db.execute('INSERT OR REPLACE INTO kv VALUES (?,?)', (key, json.dumps(value)))

    def event(self, kind, message, incident_id=None):
        self.db.execute('INSERT INTO events(id,type,message,at,incident_id) VALUES (?,?,?,?,?)', (uid(),kind,message,time.time(),incident_id))

    def events(self):
        return [dict(r) for r in self.db.execute('SELECT * FROM events ORDER BY seq DESC LIMIT 100')]

    def incident_events(self, incident_id):
        return [dict(r) for r in self.db.execute('SELECT * FROM events WHERE incident_id=? ORDER BY seq', (incident_id,))]

    def incidents(self):
        return [json.loads(r[0]) for r in self.db.execute('SELECT payload FROM incidents ORDER BY opened DESC LIMIT 100')]

    def incident(self, identifier):
        row = self.db.execute('SELECT payload FROM incidents WHERE id=?', (identifier,)).fetchone()
        return json.loads(row[0]) if row else None

    def save_incident(self, incident):
        self.db.execute('INSERT OR REPLACE INTO incidents VALUES (?,?,?,?,?,?,?)', (incident['id'],incident['session_id'],incident['epoch'],incident['kind'],incident['status'],json.dumps(incident),incident['opened_at']))

    def observe(self, kind, observations, origin='fixture', priority='high'):
        with self.lock, self.db:
            session = self.get('session'); now = time.time()
            recent = self.db.execute('SELECT payload FROM incidents WHERE session_id=? AND epoch=? AND kind=? ORDER BY opened DESC LIMIT 1', (session['id'],session['epoch'],kind)).fetchone()
            if recent:
                old = json.loads(recent[0])
                if old['status'] in ('open','acknowledged'):
                    old['observations'] = list(dict.fromkeys(old['observations'] + observations))[-12:]
                    old['revision'] += 1; self.save_incident(old); return old
                # An ongoing condition cannot immediately recreate a resolved episode.
                if now - old.get('closed_at',old['opened_at']) < 30:
                    return old
            settings = self.get('settings')
            incident = {'id':uid(),'session_id':session['id'],'epoch':session['epoch'],'kind':kind,'title':KINDS[kind][0],'room':settings['room_label'],'status':'open','opened_at':now,'acknowledged_at':None,'resolved_at':None,'observations':observations,'origin':origin,'priority':priority,'revision':1,'assigned_responder':None,'limitations':list(KINDS[kind][2]),'primary_due_at':now+settings['primary_delay_seconds'],'backup_due_at':now+settings['backup_delay_seconds']}
            self.save_incident(incident)
            for step,due in [(0,incident['primary_due_at']),(1,incident['backup_due_at'])]:
                self.db.execute('INSERT OR IGNORE INTO jobs VALUES (?,?,?,?,?,?)',(uid(),incident['id'],step,due,'queued',json.dumps({})))
            self.event('incident_opened',incident['title'] + (' · developer fixture' if origin=='fixture' else ''),incident['id'])
            return incident

    def annotate(self, kind, review):
        """Attach a second opinion to the newest incident of this kind in the current session. Status never changes."""
        with self.lock, self.db:
            session = self.get('session')
            row = self.db.execute('SELECT payload FROM incidents WHERE session_id=? AND epoch=? AND kind=? ORDER BY opened DESC LIMIT 1', (session['id'], session['epoch'], kind)).fetchone()
            if not row:
                return None
            incident = json.loads(row[0])
            incident['second_opinion'] = review
            incident['revision'] += 1
            self.save_incident(incident)
            self.event('second_opinion', f"Claude second opinion on {incident['title'].lower()}: {review['assessment'].replace('_', ' ')}", incident['id'])
            return incident

    def transition(self, identifier, action, actor='Operator', reason='', channel='dashboard'):
        with self.lock, self.db:
            incident = self.incident(identifier)
            if not incident: raise KeyError(identifier)
            target={'acknowledge':'acknowledged','resolve':'resolved','dismiss':'dismissed'}[action]
            if incident['status']==target: return incident
            valid = (action=='acknowledge' and incident['status']=='open') or (action=='resolve' and incident['status']=='acknowledged') or (action=='dismiss' and incident['status']=='open')
            if not valid: raise ValueError('Acknowledge before resolving; closed incidents cannot be changed.')
            incident['status']=target; incident['revision']+=1
            if action=='acknowledge': incident['acknowledged_at']=time.time(); incident['assigned_responder']=actor; incident['acknowledged_via']=channel
            if action=='resolve': incident['resolved_at']=time.time()
            if action in ('resolve','dismiss'): incident['closed_at']=time.time()
            if reason: incident['reason']=reason
            self.save_incident(incident)
            self.db.execute("UPDATE jobs SET status='canceled' WHERE incident_id=? AND status='queued'",(identifier,))
            self.event('incident_'+target,f'{actor} {target} the incident'+(f' via {channel}' if action=='acknowledge' else ''),identifier)
            return incident

    def decline(self, identifier, actor='Operator'):
        with self.lock, self.db:
            incident=self.incident(identifier);session=self.get('session')
            if not incident:raise KeyError(identifier)
            if incident['session_id']!=session['id'] or incident['epoch']!=session['epoch'] or incident['status']!='open':
                raise ValueError('Only a current open incident can be declined.')
            if incident.get('declined_at'):return incident
            incident['declined_at']=time.time();incident['declined_by']=actor;incident['revision']+=1
            self.save_incident(incident)
            self.db.execute("UPDATE jobs SET status='canceled' WHERE incident_id=? AND step=0 AND status='queued'",(identifier,))
            self.db.execute("UPDATE jobs SET due=? WHERE incident_id=? AND step=1 AND status='queued'",(time.time(),identifier))
            self.event('caregiver_declined',actor+' cannot respond · backup escalation requested',identifier)
            return incident

    def claim_due(self):
        with self.lock, self.db:
            row=self.db.execute("SELECT * FROM jobs WHERE status='queued' AND due<=? ORDER BY due LIMIT 1",(time.time(),)).fetchone()
            if not row:return None
            incident=self.incident(row['incident_id']); session=self.get('session')
            valid=incident and incident['status']=='open' and incident['session_id']==session['id'] and incident['epoch']==session['epoch'] and session['status']!='stopped'
            self.db.execute('UPDATE jobs SET status=? WHERE id=?',('initiating' if valid else 'canceled',row['id']))
            return dict(row) if valid else None

    def finish_job(self, identifier, status, payload):
        with self.lock, self.db:
            self.db.execute('UPDATE jobs SET status=?,payload=? WHERE id=?',(status,json.dumps(payload),identifier))

    def attempts(self):
        return [{**dict(r),'payload':json.loads(r['payload'])} for r in self.db.execute("SELECT * FROM jobs WHERE status!='queued' ORDER BY due DESC LIMIT 100")]

    def reset(self):
        with self.lock, self.db:
            old=self.get('session')
            session={'id':uid(),'epoch':old['epoch']+1,'calls_armed':False,'status':'paused','frame_seq':-1,'source_type':'demo'}
            self.db.execute("UPDATE jobs SET status='canceled' WHERE status='queued'")
            self.db.execute('INSERT OR REPLACE INTO kv VALUES (?,?)',('session',json.dumps(session)))
            self.event('session_reset','New session · calls disarmed')
            return session

    def accept_frame(self, frame):
        with self.lock, self.db:
            session=self.get('session')
            if frame['session_id']!=session['id'] or frame['epoch']!=session['epoch'] or frame['frame_seq']<=session.get('frame_seq',-1):return False
            if session['status']!='active':return False
            session['frame_seq']=frame['frame_seq']; session['last_frame_at']=time.time()
            self.db.execute('INSERT OR REPLACE INTO kv VALUES (?,?)',('session',json.dumps(session)))
            return True
