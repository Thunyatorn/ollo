import asyncio
import base64
import contextlib
import json
import math
import os
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response, UploadFile, File
from fastapi.responses import FileResponse, Response as RawResponse
from pydantic import BaseModel, Field
from .store import Store, uid
from .providers import Calls, ready, allowed_numbers

DATA_DIR=Path(os.getenv('DATA_DIR',str(Path(__file__).resolve().parent.parent/'data')))
DATA_DIR.mkdir(parents=True,exist_ok=True)
store=Store(DATA_DIR/'lookout.sqlite3')
calls=Calls(DATA_DIR)
TOKEN=os.getenv('APP_SESSION_SECRET') or secrets.token_urlsafe(32)
vision=None
vision_state={'overlays':[],'health':{'tracking':'paused','review':'disabled'},'limitations':[]}
processing=False


async def coordinator():
    while True:
        job=store.claim_due()
        if job:
            incident=store.incident(job['incident_id']); session=store.get('session')
            try:
                count=sum(1 for a in store.attempts() if a['payload'].get('mode')=='real' and (store.incident(a['incident_id']) or {}).get('session_id')==session['id'])
                armed=session['calls_armed'] and count<6 and incident['status']=='open'
                if job['step']==1:
                    await cancel_calls(incident['id'])
                def still_authorized():
                    latest=store.get('session'); current=store.incident(incident['id'])
                    return latest['id']==session['id'] and latest['epoch']==incident['epoch'] and latest['calls_armed'] and current['status']=='open' and not (job['step']==0 and current.get('declined_at'))
                result=await calls.place(incident,job['step'],armed,still_authorized)
                # Acknowledgment/reset can occur while TTS/call HTTP is in flight.
                current=store.incident(incident['id']); current_session=store.get('session')
                if result.get('call_sid') and (current['status']!='open' or current_session['id']!=session['id'] or current_session['epoch']!=incident['epoch'] or not current_session['calls_armed'] or (job['step']==0 and current.get('declined_at'))):
                    await calls.cancel(result['call_sid']); result['status']='canceled'
                store.finish_job(job['id'],result['status'],result)
                with store.db:store.event('call_'+result['status'],('Primary' if job['step']==0 else 'Backup')+' caregiver · '+('real call' if result.get('mode')=='real' else 'simulated call (not placed)'))
            except Exception as exc:
                store.finish_job(job['id'],'unknown',{'error':type(exc).__name__,'message':'Provider outcome unknown; no automatic retry.'})
                with store.db:store.event('call_failed','Call provider failed; check immediately. No retry was attempted.')
        await asyncio.sleep(.3)


@asynccontextmanager
async def lifespan(app):
    global vision
    from .vision import VisionEngine
    vision=VisionEngine(store.get('settings'))
    task=asyncio.create_task(coordinator())
    yield
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):await task


app=FastAPI(title='Lookout API',lifespan=lifespan)


@app.middleware('http')
async def local_access(request:Request,call_next):
    path=request.url.path
    exempt=path in ('/health',) or path.startswith('/webhooks/twilio/') or path.startswith('/call-media/')
    origin=request.headers.get('origin')
    valid_origins={f'http://localhost:{p}' for p in (5173,4173,8000)}|{f'http://127.0.0.1:{p}' for p in (5173,4173,8000)}
    if not exempt:
        if origin and origin not in valid_origins and origin!=os.getenv('APP_ORIGIN'):
            return RawResponse('Origin rejected',403)
        authorized=secrets.compare_digest(request.cookies.get('lookout_session',''),TOKEN) or secrets.compare_digest(request.headers.get('authorization',''),'Bearer '+TOKEN)
        local=request.client and request.client.host in ('127.0.0.1','::1','localhost','testclient') and request.url.hostname in ('127.0.0.1','localhost','testserver','::1') and not request.headers.get('x-forwarded-for')
        # Bootstrap allowed only through loopback. A tunnel does not inherit trust.
        if not authorized and not (local and request.method=='GET' and path in ('/api/state','/api/bootstrap')):
            return RawResponse('Local operator session required',401)
    response=await call_next(request)
    if not exempt and local and request.method=='GET' and path in ('/api/state','/api/bootstrap'):
        response.set_cookie('lookout_session',TOKEN,httponly=True,samesite='strict',max_age=28800)
    response.headers['Cache-Control']='no-store'
    return response


@app.get('/health')
def health():return {'status':'ok','purpose':'process health only'}


@app.get('/api/bootstrap')
def bootstrap():return {'ok':True}


def state():
    session=store.get('session'); settings=store.get('settings'); last=session.get('last_frame_at')
    health='offline' if session.get('forced_offline') else ('active' if last and time.time()-last<3 and session['status']=='active' else 'degraded' if session['status']=='active' else session['status'])
    caregivers=[{'id':'primary','name':settings.get('primary_name','Maya Chen'),'role':'Primary caregiver','phone_last4':allowed_numbers()[0][-4:] if allowed_numbers() else None},{'id':'backup','name':settings.get('backup_name','James Wilson'),'role':'Backup caregiver','phone_last4':allowed_numbers()[-1][-4:] if allowed_numbers() else None}]
    return {'session':session,'camera':{'id':'cam-01','room_label':settings['room_label'],'health':health,'last_frame_at':last,'tracking':vision_state.get('health',{}).get('tracking','paused'),'review':vision_state.get('health',{}).get('review','disabled')},'incidents':[i for i in store.incidents() if i['session_id']==session['id']],'caregivers':caregivers,'events':store.events(),'settings':settings,'overlays':vision_state.get('overlays',[]),'analysis':vision_state,'attempts':[a for a in store.attempts() if (store.incident(a['incident_id']) or {}).get('session_id')==session['id']],'call_provider':{'configured':ready(),'mode':'real' if session['calls_armed'] and ready() else 'simulation'},'server_time':time.time()}


@app.get('/api/state')
def get_state():return state()


@app.get('/api/history')
def history():return {'incidents':store.incidents(),'events':store.events()}


class Scenario(BaseModel):
    scenario:str
    media_time_ms:float=Field(default=0,ge=0,allow_inf_nan=False)


@app.post('/api/demo/scenario')
async def scenario(body:Scenario):
    if body.scenario not in ('boundary','distress','normal','offline'):raise HTTPException(400,'Unknown scenario')
    session=store.get('session')
    if session['source_type']!='fixture':
        session['epoch']+=1;session['frame_seq']=-1;session['calls_armed']=False
        store.put('session',session)
        if vision:vision.reset()
        await cancel_calls()
    session['source_type']='fixture'; session['forced_offline']=body.scenario=='offline';store.put('session',session)
    if body.scenario in ('boundary','distress'):
        observations=['Developer fixture: subject crossed the configured doorway boundary.'] if body.scenario=='boundary' else ['Developer fixture: actor holds hands near neck; possible benign explanations remain.']
        incident=store.observe(body.scenario,observations,'fixture','critical' if body.scenario=='distress' else 'high')
        if 'media_time_ms' not in incident:
            incident['media_time_ms']=body.media_time_ms
            incident['source_key']='fixture'
            with store.db:store.save_incident(incident)
    elif body.scenario not in ('normal','offline'):raise HTTPException(400,'Unknown scenario')
    with store.db:store.event('fixture_'+body.scenario,'Developer fixture · '+body.scenario)
    return state()


class Action(BaseModel):
    actor:str=Field(default='Operator',max_length=80)
    reason:str=Field(default='',max_length=500)


async def cancel_calls(identifier=None, step=None):
    for attempt in store.attempts():
        if identifier and attempt['incident_id']!=identifier:continue
        if step is not None and attempt['step']!=step:continue
        sid=attempt['payload'].get('call_sid')
        if sid and attempt['status'] in ('initiated','ringing','answered','in-progress'):
            try:await calls.cancel(sid);store.finish_job(attempt['id'],'canceled',attempt['payload'])
            except Exception:
                with store.db:store.event('cancel_failed','Could not confirm active call cancellation')


@app.get('/api/incidents/{identifier}')
def get_incident(identifier:str):
    incident=store.incident(identifier)
    if not incident:raise HTTPException(404,'Incident not found')
    return {'incident':incident,'attempts':[a for a in store.attempts() if a['incident_id']==identifier]}


@app.post('/api/incidents/{identifier}/{action}')
async def incident_action(identifier:str,action:str,body:Action=Action()):
    if action not in ('acknowledge','resolve','dismiss','decline'):raise HTTPException(404,'Unknown action')
    if action=='decline':
        try:incident=store.decline(identifier,body.actor)
        except KeyError:raise HTTPException(404,'Incident not found')
        except ValueError as exc:raise HTTPException(409,str(exc))
        await cancel_calls(identifier,step=0)
        return {'incident':incident,**state()}
    if action=='dismiss' and not body.reason.strip():raise HTTPException(422,'Dismissal reason required')
    try:incident=store.transition(identifier,action,body.actor,body.reason)
    except KeyError:raise HTTPException(404,'Incident not found')
    except ValueError as exc:raise HTTPException(409,str(exc))
    await cancel_calls(identifier)
    return {'incident':incident,**state()}


@app.post('/api/session/reset')
async def reset():
    global vision_state
    store.reset(); await cancel_calls(); vision_state={'overlays':[],'health':{'tracking':'paused','review':'disabled'}}
    if vision:vision.reset()
    return state()


class Armed(BaseModel):armed:bool


@app.post('/api/session/arm-calls')
def arm(body:Armed):
    if body.armed and not ready():raise HTTPException(409,'Real calling requires configured providers, HTTPS callbacks, CALLS_ENABLED=true and consenting E.164 allowlist.')
    session=store.get('session');session['calls_armed']=body.armed;store.put('session',session)
    with store.db:store.event('calls_armed' if body.armed else 'calls_disarmed','Real calls '+('armed by operator' if body.armed else 'disarmed'))
    return state()


class Source(BaseModel):
    source_type:str


@app.post('/api/source')
async def change_source(body:Source):
    if body.source_type not in ('webcam','recorded','fixture'):raise HTTPException(422,'Unsupported source')
    await reset()
    session=store.get('session');session['source_type']=body.source_type;store.put('session',session)
    return state()


@app.post('/api/session/{action}')
async def session_action(action:str):
    if action not in ('start','pause','stop'):raise HTTPException(404)
    session=store.get('session')
    session['status']={'start':'active','pause':'paused','stop':'stopped'}[action]
    session['forced_offline']=False
    if action!='pause':
        session['epoch']+=1;session['frame_seq']=-1
        store.put('session',session)
        await cancel_calls()
    if action=='stop':
        session['calls_armed']=False
        store.put('session',session)
        with store.db:store.db.execute("UPDATE jobs SET status='canceled' WHERE status='queued'")
        await cancel_calls()
    store.put('session',session)
    if vision:vision.reset()
    return state()


@app.put('/api/settings')
def settings(body:dict):
    current=store.get('settings')
    if 'escalation_seconds' in body:body['primary_delay_seconds']=body['escalation_seconds']
    for key in ('primary_name','backup_name'):
        if key in body:
            if not isinstance(body[key],str) or not 1<=len(body[key])<=80:raise HTTPException(422,'Invalid caregiver name')
            current[key]=body[key]
    for key in ('room_label','cloud_review_enabled','audio_enabled','zone','primary_delay_seconds','backup_delay_seconds'):
        if key in body:current[key]=body[key]
    if not isinstance(current['room_label'],str) or not 1<=len(current['room_label'])<=80:raise HTTPException(422,'Invalid room name')
    for key in ('primary_delay_seconds','backup_delay_seconds'):
        if isinstance(current[key],bool) or not isinstance(current[key],(int,float)) or not math.isfinite(current[key]) or not 1<=current[key]<=120:raise HTTPException(422,'Call delay must be 1–120 seconds')
    if current['backup_delay_seconds']<=current['primary_delay_seconds']:raise HTTPException(422,'Backup delay must exceed primary delay')
    if any(not isinstance(current[k],bool) for k in ('cloud_review_enabled','audio_enabled')):raise HTTPException(422,'Boolean settings must be true or false')
    zone=current['zone']
    if not isinstance(zone,dict) or not isinstance(zone.get('enabled'),bool) or not isinstance(zone.get('vertices'),list) or not 3<=len(zone['vertices'])<=12 or any(not isinstance(p,list) or len(p)!=2 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not 0<=v<=1 for v in p) for p in zone['vertices']):raise HTTPException(422,'Zone must be a normalized polygon')
    vertices=zone['vertices']
    area=abs(sum(vertices[i][0]*vertices[(i+1)%len(vertices)][1]-vertices[(i+1)%len(vertices)][0]*vertices[i][1] for i in range(len(vertices))))/2
    if area<.001:raise HTTPException(422,'Zone must enclose an area')
    store.put('settings',current)
    if vision:vision.configure(current)
    return state()


@app.post('/api/video')
async def upload(file:UploadFile=File(...)):
    if file.content_type not in ('video/mp4','video/quicktime','video/webm'):raise HTTPException(415,'Use MP4, MOV or WebM')
    identifier=uid();suffix={ 'video/mp4':'.mp4','video/quicktime':'.mov','video/webm':'.webm'}[file.content_type];path=DATA_DIR/(identifier+suffix)
    size=0
    try:
        with path.open('wb') as output:
            while chunk:=await file.read(1024*1024):
                size+=len(chunk)
                if size>100*1024*1024:raise HTTPException(413,'Maximum video size is 100 MB')
                output.write(chunk)
        import cv2
        def inspect():
            cap=cv2.VideoCapture(str(path));ok,frame=cap.read();fps=cap.get(cv2.CAP_PROP_FPS);count=cap.get(cv2.CAP_PROP_FRAME_COUNT);cap.release()
            return ok,fps,count
        ok,fps,count=await asyncio.to_thread(inspect)
        if not ok or not math.isfinite(fps) or not math.isfinite(count) or fps<=0 or count<=0 or count/fps>300:raise HTTPException(422,'Video must decode and be at most five minutes')
    except Exception:
        path.unlink(missing_ok=True);raise
    await reset()
    session=store.get('session');session.update({'source_type':'recorded','media_id':identifier+suffix,'media_url':'/api/media/'+identifier+suffix});store.put('session',session)
    return {'media_url':session['media_url'],**state()}


@app.get('/api/media/{identifier}')
def media(identifier:str):
    if '/' in identifier or '..' in identifier or not all(c.isalnum() or c=='.' for c in identifier):raise HTTPException(404)
    path=DATA_DIR/identifier
    if not path.is_file() or path.suffix not in ('.mp4','.mov','.webm','.jpg'):raise HTTPException(404)
    return FileResponse(path)


class Frame(BaseModel):
    session_id:str
    epoch:int
    frame_seq:int=Field(ge=0)
    media_time_ms:float=Field(ge=0,allow_inf_nan=False)
    image:str=Field(max_length=3000000)


async def process_frame(frame):
    global vision_state,processing
    try:
        result=await vision.process_frame(frame)
        session=store.get('session')
        if session['id']!=frame['session_id'] or session['epoch']!=frame['epoch']:return
        vision_state=result
        for observation in result.get('observations',[]):
            kind=observation.get('kind')
            if kind in ('boundary','distress'):
                incident=store.observe(kind,observation.get('observations',[]),observation.get('origin','local_rule'),observation.get('priority','high'))
                if 'media_time_ms' not in incident:
                    incident['media_time_ms']=frame['media_time_ms']
                    incident['source_key']=session.get('media_id') if session['source_type']=='recorded' else session['source_type']
                    with store.db:store.save_incident(incident)
                if not incident.get('evidence_url'):
                    evidence=observation.get('evidence_image') if observation.get('origin')=='model' else frame['image']
                    if not evidence:continue
                    raw=base64.b64decode(evidence.split(',')[-1]); filename=uid()+'.jpg';(DATA_DIR/filename).write_bytes(raw)
                    incident['evidence_url']='/api/media/'+filename
                    with store.db:store.save_incident(incident)
    except Exception as exc:
        vision_state={'overlays':[],'health':{'tracking':'degraded','review':'degraded'},'limitations':['Analysis failed: '+type(exc).__name__]}
    finally:processing=False


@app.post('/api/frames')
async def frame(body:Frame):
    global processing
    data=body.model_dump()
    if processing:return {'accepted':False,'reason':'busy; latest frame wins'}
    if not store.accept_frame(data):raise HTTPException(409,'Stale frame, epoch, or inactive session')
    if not vision:raise HTTPException(503,'Vision not initialized')
    processing=True;asyncio.create_task(process_frame(data))
    return {'accepted':True}


async def callback(request):
    form=await request.form();base=os.getenv('PUBLIC_CALLBACK_BASE_URL','').rstrip('/')
    if not calls.valid_signature(base+request.url.path,form,request.headers.get('x-twilio-signature')):raise HTTPException(403,'Invalid signature')
    sid=form.get('CallSid');attempt=next((a for a in store.attempts() if a['payload'].get('call_sid')==sid),None)
    if not attempt:raise HTTPException(404,'Unknown call')
    return form,attempt


@app.post('/webhooks/twilio/status')
async def call_status(request:Request):
    form,attempt=await callback(request)
    status=form.get('CallStatus','unknown');terminal=('completed','busy','no-answer','failed','canceled')
    ranks={'initiated':0,'queued':0,'ringing':1,'answered':2,'in-progress':2,'completed':3,'busy':3,'no-answer':3,'failed':3,'canceled':3}
    if status in ranks and attempt['status'] not in terminal and ranks[status]>=ranks.get(attempt['status'],0):
        store.finish_job(attempt['id'],status,attempt['payload'])
    incident=store.incident(attempt['incident_id']);session=store.get('session')
    if attempt['step']==0 and status in terminal and incident and incident['status']=='open' and incident['session_id']==session['id'] and incident['epoch']==session['epoch']:
        with store.db:store.db.execute("UPDATE jobs SET due=? WHERE incident_id=? AND step=1 AND status='queued'",(time.time(),incident['id']))
    return RawResponse('<Response/>',media_type='application/xml')


@app.post('/webhooks/twilio/digits')
async def digits(request:Request):
    form,attempt=await callback(request);incident=store.incident(attempt['incident_id']);session=store.get('session')
    if incident and incident['session_id']==session['id'] and incident['epoch']==session['epoch'] and incident['status']=='open':
        if form.get('Digits')=='1':
            store.transition(incident['id'],'acknowledge','Primary caregiver' if attempt['step']==0 else 'Backup caregiver');await cancel_calls(incident['id'])
        elif form.get('Digits')=='2':
            store.decline(incident['id'],'Primary caregiver' if attempt['step']==0 else 'Backup caregiver')
    return RawResponse('<Response><Say>Thank you.</Say><Hangup/></Response>',media_type='application/xml')


@app.get('/call-media/{token}')
def audio(token:str):
    entry=calls.audio.get(token)
    if not entry or entry[0]<time.time():raise HTTPException(404)
    return RawResponse(entry[1],media_type='audio/wav')
