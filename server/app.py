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
from fastapi.responses import FileResponse, PlainTextResponse, Response as RawResponse
from typing import Literal

from pydantic import BaseModel, Field
from .store import KINDS, PRIMARY_CAMERA, Store, uid
from .providers import Calls, ready, allowed_numbers, token_hash
from .rules import DEFAULT_MODEL, draft_rule, validate_landmark
from .clips import ClipRecorder, blur_jpeg, prune, write_clip
from .report import ai_lines, build_facts, render
from .capture import CameraCapture, mask, parse_camera

DATA_DIR=Path(os.getenv('DATA_DIR',str(Path(__file__).resolve().parent.parent/'data')))
DATA_DIR.mkdir(parents=True,exist_ok=True)
store=Store(DATA_DIR/'lookout.sqlite3')
calls=Calls(DATA_DIR)
TOKEN=os.getenv('APP_SESSION_SECRET') or secrets.token_urlsafe(32)
vision=None
vision_state={'overlays':[],'health':{'tracking':'paused','review':'disabled'},'limitations':[]}
processing=False
recorder=ClipRecorder()
capture=None  # SRC-4 server camera, when that is the source. It is always cam-01.
MAX_CAMERAS=4  # SRC-5: cam-01 plus up to three more server cameras.


class Feed:
    """SRC-5: an additional server camera with its own capture, tracker and rule state, clip buffer and incidents."""

    def __init__(self,identifier,source,room_label,engine):
        self.id,self.source,self.room_label,self.label=identifier,source,room_label,mask(source)
        self.vision,self.recorder,self.capture=engine,ClipRecorder(),None
        self.state={'overlays':[],'health':{'tracking':'paused','review':'disabled'}}
        self.processing,self.frame_seq,self.last_frame_at=False,-1,None

    @property
    def camera(self):return {'id':self.id,'room':self.room_label}


feeds={}  # cam-02… → Feed, in the order they were added.
retired=[]  # Stopped feeds whose clips in progress still need finalizing.


def extra_settings(settings):
    """Zones, calibration and plain-language rules are drawn on cam-01's picture, so other cameras never inherit them."""
    extra={k:v for k,v in settings.items() if k not in ('calibration','rules','landmarks')}
    extra['zone']={**(settings.get('zone') or {}),'enabled':False}
    return extra


def configure_vision(settings):
    if vision:vision.configure(settings)
    for feed in feeds.values():feed.vision.configure(extra_settings(settings))


def reset_vision():
    if vision:vision.reset()
    for feed in feeds.values():feed.vision.reset();feed.state={'overlays':[],'health':{'tracking':'paused','review':'disabled'}}


def caregiver_name(step):
    settings=store.get('settings')
    return settings.get('backup_name','James Wilson') if step else settings.get('primary_name','Maya Chen')


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
                result=await calls.place(incident,job['step'],armed,still_authorized,caregiver=caregiver_name(job['step']))
                # Acknowledgment/reset can occur while TTS/call HTTP is in flight.
                current=store.incident(incident['id']); current_session=store.get('session')
                if result.get('call_sid') and (current['status']!='open' or current_session['id']!=session['id'] or current_session['epoch']!=incident['epoch'] or not current_session['calls_armed'] or (job['step']==0 and current.get('declined_at'))):
                    await calls.cancel(result['call_sid']); result['status']='canceled'
                store.finish_job(job['id'],result['status'],result)
                with store.db:store.event('call_'+result['status'],('Primary' if job['step']==0 else 'Backup')+' caregiver · '+('real call' if result.get('mode')=='real' else 'simulated call (not placed)'),incident['id'])
            except Exception as exc:
                store.finish_job(job['id'],'unknown',{'error':type(exc).__name__,'message':'Provider outcome unknown; no automatic retry.'})
                with store.db:store.event('call_failed','Call provider failed; check immediately. No retry was attempted.',incident['id'])
        await asyncio.sleep(.3)


async def save_clip(incident_id,frames):
    path=DATA_DIR/'clips'/f'{incident_id}.webm'
    if not await asyncio.to_thread(write_clip,path,frames):return
    incident=store.incident(incident_id)
    if not incident:return
    incident['clip_url']=f'/api/clips/{incident_id}.webm'
    with store.db:
        store.save_incident(incident)
        store.event('evidence_clip',f'Evidence clip saved · {len(frames)} frames, heads blurred',incident_id)


async def flush_clips():
    """Session changes finalize clips in progress with the frames they have."""
    for incident_id,frames in [c for r in [recorder,*(f.recorder for f in feeds.values()),*(f.recorder for f in retired)] for c in r.flush()]:
        await save_clip(incident_id,frames)
    retired.clear()


async def retention():
    while True:
        with contextlib.suppress(Exception):
            await asyncio.to_thread(prune,DATA_DIR,float(store.get('settings').get('clip_retention_days',7)),store)
        await asyncio.sleep(3600)


@asynccontextmanager
async def lifespan(app):
    global vision
    from .vision import VisionEngine
    vision=VisionEngine(store.get('settings'))
    vision.on_review=store.annotate
    warm=asyncio.create_task(asyncio.to_thread(vision.warm))
    task=asyncio.create_task(coordinator());cleanup=asyncio.create_task(retention())
    yield
    stop_capture()
    task.cancel();cleanup.cancel()
    with contextlib.suppress(asyncio.CancelledError):await task
    with contextlib.suppress(Exception):await warm


app=FastAPI(title='Lookout API',lifespan=lifespan)


@app.middleware('http')
async def local_access(request:Request,call_next):
    path=request.url.path
    # Webhooks authenticate themselves (Twilio signature, voice-agent bearer secret plus single-use token).
    exempt=path in ('/health',) or path.startswith('/webhooks/twilio/') or path.startswith('/webhooks/voice/') or path.startswith('/call-media/')
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


def floor_plan():
    """UI-4: calibration points, zones in force and landmarks in meters; None until the floor is calibrated."""
    if not vision or vision.calibration is None:return None
    vision._refresh_zones();cal=vision.calibration
    meters=lambda polygon:(lambda m:None if m is None else [[round(float(x),3),round(float(y),3)] for x,y in m])(cal.zone_to_floor(polygon))
    landmarks=[{'id':l['id'],'name':l['name'],'polygon':meters(l['vertices'])} for l in vision.settings.get('landmarks',[])]
    return {'points':[p['floor'] for p in cal.points],'zones':[{'id':z['id'],'name':z['name'],'polygon':meters(z['polygon'])} for z in vision.active if z['floor'] is not None],'landmarks':[l for l in landmarks if l['polygon']]}


def feed_summary(feed,session):
    camera=feed.capture.status()
    last=feed.last_frame_at
    health='offline' if camera['status']=='offline' else 'active' if last and time.time()-last<3 and session['status']=='active' else 'degraded' if session['status']=='active' else session['status']
    return {'id':feed.id,'room_label':feed.room_label,'health':health,'last_frame_at':last,'tracking':feed.state.get('health',{}).get('tracking','paused'),'detector':feed.vision.detector,'analysis_fps':feed.vision.analysis_fps(),'people':len(feed.state.get('overlays',[])),'capture':camera,'primary':False}


def cameras(primary=None):
    """SRC-5: every camera this server analyzes, cam-01 first."""
    session=store.get('session')
    primary=primary or state()['camera']
    return [{**{k:primary.get(k) for k in ('id','room_label','health','last_frame_at','tracking','detector','analysis_fps','capture')},'people':len(vision_state.get('overlays',[])),'primary':True}]+[feed_summary(feeds[k],session) for k in sorted(feeds)]


def state():
    session=store.get('session'); settings=store.get('settings'); last=session.get('last_frame_at')
    camera=capture.status() if capture else None
    # SRC-4: a server camera with no new frame for 2 s is offline, whatever the session status.
    lost=session.get('source_type')=='server_camera' and (not camera or camera['status']=='offline')
    health='offline' if session.get('forced_offline') or lost else ('active' if last and time.time()-last<3 and session['status']=='active' else 'degraded' if session['status']=='active' else session['status'])
    caregivers=[{'id':'primary','name':settings.get('primary_name','Maya Chen'),'role':'Primary caregiver','phone_last4':allowed_numbers()[0][-4:] if allowed_numbers() else None},{'id':'backup','name':settings.get('backup_name','James Wilson'),'role':'Backup caregiver','phone_last4':allowed_numbers()[-1][-4:] if allowed_numbers() else None}]
    result={'session':session,'camera':{'id':PRIMARY_CAMERA,'room_label':settings['room_label'],'health':health,'last_frame_at':last,'tracking':vision_state.get('health',{}).get('tracking','paused'),'review':vision_state.get('health',{}).get('review','disabled'),'detector':vision.detector if vision else 'pending','analysis_fps':vision.analysis_fps() if vision else 0.0,'predictive':vision._predictive_status() if vision else 'needs calibration','capture':camera},'incidents':[i for i in store.incidents() if i['session_id']==session['id']],'caregivers':caregivers,'events':store.events(),'settings':settings,'overlays':vision_state.get('overlays',[]),'analysis':vision_state,'attempts':[a for a in store.attempts() if (store.incident(a['incident_id']) or {}).get('session_id')==session['id']],'call_provider':{'configured':ready(),'mode':'real' if session['calls_armed'] and ready() else 'simulation'},'floor_plan':floor_plan(),'server_time':time.time()}
    result['cameras']=cameras(result['camera'])
    return result


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
    stop_capture()
    session=store.get('session')
    if session['source_type']!='fixture':
        session['epoch']+=1;session['frame_seq']=-1;session['calls_armed']=False
        store.put('session',session)
        reset_vision()
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
    channel:Literal['dashboard','app']='dashboard'  # Keypad and voice arrive only through their verified webhooks.


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
    try:incident=store.transition(identifier,action,body.actor,body.reason,channel=body.channel)
    except KeyError:raise HTTPException(404,'Incident not found')
    except ValueError as exc:raise HTTPException(409,str(exc))
    await cancel_calls(identifier)
    return {'incident':incident,**state()}


@app.post('/api/session/reset')
async def reset():
    global vision_state
    stop_capture(); await flush_clips(); store.reset(); await cancel_calls(); vision_state={'overlays':[],'health':{'tracking':'paused','review':'disabled'}}
    reset_vision()
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
    camera:int|str|None=None  # server_camera only: webcam index or stream URL.


def stop_capture():
    """Stop every server camera: cam-01 and all SRC-5 cameras."""
    global capture
    if capture:capture.stop();capture=None
    for feed in feeds.values():
        feed.capture.stop();retired.append(feed)
    feeds.clear()


def start_capture(source):
    """SRC-4: the server reads the camera itself; stream health changes are logged."""
    global capture
    stop_capture()
    def changed(status):
        message=f'Camera live · {current.label}' if status=='live' else f'Camera offline · {current.label} · {current.error or "no new frames for 2 s"} · reconnecting'
        with store.db:store.event('camera_online' if status=='live' else 'camera_offline',message)
    current=capture=CameraCapture(source,submit_captured,on_status=changed)
    capture.start()


@app.post('/api/source')
async def change_source(body:Source):
    if body.source_type not in ('webcam','recorded','fixture','server_camera'):raise HTTPException(422,'Unsupported source')
    if body.source_type=='server_camera':
        try:camera=parse_camera(body.camera)
        except ValueError as exc:raise HTTPException(422,str(exc))
    await reset()
    session=store.get('session');session['source_type']=body.source_type
    if body.source_type=='server_camera':session['camera_label']=mask(camera)  # Never the URL password.
    store.put('session',session)
    if body.source_type=='server_camera':start_capture(camera)
    return state()


@app.get('/api/camera/frame')
async def camera_frame(after:int=-1,camera:str=PRIMARY_CAMERA):
    """SRC-4/SRC-5 live picture of one camera: the analyzed JPEG with the overlays computed from it, so boxes match the picture."""
    source=capture if camera==PRIMARY_CAMERA else (feeds[camera].capture if camera in feeds else None)
    if not source:raise HTTPException(404,'No server camera connected' if camera==PRIMARY_CAMERA else f'No camera {camera}')
    view=await source.next_view(after,timeout=1.0)
    return view if view else RawResponse(status_code=204)


def submit_feed_frame(feed,data):
    """SRC-5: the same ordering rules as SRC-3, per camera. Busy, paused or stale frames are skipped, never queued."""
    session=store.get('session')
    if feed.processing or session['status']!='active' or data['session_id']!=session['id'] or data['epoch']!=session['epoch'] or data['frame_seq']<=feed.frame_seq:return None
    feed.frame_seq,feed.last_frame_at,feed.processing=data['frame_seq'],time.time(),True
    return asyncio.create_task(process_frame(data,feed))


def feed_submitter(feed):
    async def submit(image,frame_seq,media_time_ms):
        session=store.get('session')
        task=submit_feed_frame(feed,{'session_id':session['id'],'epoch':session['epoch'],'frame_seq':frame_seq,'media_time_ms':media_time_ms,'image':image})
        if task is None:return None
        result=await asyncio.shield(task)
        return result.get('overlays',[]) if result else None
    return submit


class CameraBody(BaseModel):
    camera:int|str
    room_label:str|None=Field(default=None,max_length=200)


@app.get('/api/cameras')
async def list_cameras():return {'cameras':cameras()}


@app.post('/api/cameras')
async def add_camera(body:CameraBody):
    """SRC-5: add another server camera to the running server-camera session, without resetting it."""
    if store.get('session').get('source_type')!='server_camera' or not capture:raise HTTPException(409,'Connect the first server camera (Settings → Manage source) before adding more')
    try:source=parse_camera(body.camera)
    except ValueError as exc:raise HTTPException(422,str(exc))
    if 1+len(feeds)>=MAX_CAMERAS:raise HTTPException(409,f'At most {MAX_CAMERAS} cameras per server')
    if source==capture.source or any(f.source==source for f in feeds.values()):raise HTTPException(409,'That camera is already connected')
    identifier=next(f'cam-{i:02d}' for i in range(2,MAX_CAMERAS+1) if f'cam-{i:02d}' not in feeds)
    label=(body.room_label or '').strip() or f'Camera {identifier[-2:]}'
    if len(label)>80:raise HTTPException(422,'Invalid room name')
    from .vision import VisionEngine
    feed=Feed(identifier,source,label,VisionEngine(extra_settings(store.get('settings'))))
    feed.vision.on_review=lambda kind,review,camera_id=identifier:store.annotate(kind,review,camera_id)
    def changed(status):
        message=f'Camera live · {label} · {feed.label}' if status=='live' else f'Camera offline · {label} · {feed.capture.error or "no new frames for 2 s"} · reconnecting'
        with store.db:store.event('camera_online' if status=='live' else 'camera_offline',message)
    feeds[identifier]=feed
    feed.capture=CameraCapture(source,feed_submitter(feed),on_status=changed)
    feed.capture.start()
    asyncio.get_running_loop().run_in_executor(None,feed.vision.warm)  # Load weights off the event loop.
    with store.db:store.event('camera_added',f'Camera added · {identifier} · {label} · {feed.label}')
    return state()


@app.delete('/api/cameras/{identifier}')
async def remove_camera(identifier:str):
    if identifier==PRIMARY_CAMERA:raise HTTPException(409,'cam-01 is the session source; choose another source to stop it')
    feed=feeds.pop(identifier,None)
    if not feed:raise HTTPException(404,'Camera not found')
    feed.capture.stop()
    for incident_id,frames in feed.recorder.flush():await save_clip(incident_id,frames)
    with store.db:store.event('camera_removed',f'Camera removed · {identifier} · {feed.room_label}')
    return state()


@app.post('/api/session/{action}')
async def session_action(action:str):
    if action not in ('start','pause','stop'):raise HTTPException(404)
    if action!='pause':await flush_clips()
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
    reset_vision()
    return state()


@app.put('/api/settings')
def settings(body:dict):
    current=store.get('settings')
    if 'escalation_seconds' in body:body['primary_delay_seconds']=body['escalation_seconds']
    for key in ('primary_name','backup_name'):
        if key in body:
            if not isinstance(body[key],str) or not 1<=len(body[key])<=80:raise HTTPException(422,'Invalid caregiver name')
            current[key]=body[key]
    for key in ('room_label','cloud_review_enabled','audio_enabled','zone','primary_delay_seconds','backup_delay_seconds','stillness_seconds','nap_mode','clip_retention_days'):
        if key in body:current[key]=body[key]
    retention_days=current.get('clip_retention_days',7)
    if isinstance(retention_days,bool) or not isinstance(retention_days,(int,float)) or not 1<=retention_days<=90:raise HTTPException(422,'Clip retention must be 1–90 days')
    stillness=current.get('stillness_seconds',30)
    if isinstance(stillness,bool) or not isinstance(stillness,(int,float)) or not math.isfinite(stillness) or not 10<=stillness<=600:raise HTTPException(422,'Stillness alert must be 10–600 seconds')
    if not isinstance(current.get('nap_mode',False),bool):raise HTTPException(422,'Nap mode must be true or false')
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
    configure_vision(current)
    return state()


_claude=None


def claude_client():
    global _claude
    if _claude is None:
        from anthropic import AsyncAnthropic
        _claude=AsyncAnthropic(timeout=30.0,max_retries=1)
    return _claude


def save_settings(current,event_type,message):
    store.put('settings',current)
    with store.db:store.event(event_type,message)
    configure_vision(current)
    return state()


class LandmarkBody(BaseModel):
    name:str=Field(max_length=200)
    vertices:list=Field(max_length=50)


@app.post('/api/landmarks')
def add_landmark(body:LandmarkBody):
    current=store.get('settings');landmarks=current.get('landmarks',[])
    try:landmark=validate_landmark(body.name,body.vertices,landmarks)
    except ValueError as exc:raise HTTPException(422,str(exc))
    current['landmarks']=landmarks+[landmark]
    return save_settings(current,'landmark_added',f"Landmark added · {landmark['name']}")


@app.delete('/api/landmarks/{identifier}')
def remove_landmark(identifier:str):
    current=store.get('settings');landmark=next((l for l in current.get('landmarks',[]) if l['id']==identifier),None)
    if not landmark:raise HTTPException(404,'Landmark not found')
    rules=current.get('rules',[]);kept=[r for r in rules if r['landmark_id']!=identifier]
    current['landmarks']=[l for l in current['landmarks'] if l['id']!=identifier];current['rules']=kept
    return save_settings(current,'landmark_removed',f"Landmark removed · {landmark['name']}"+(f' · {len(rules)-len(kept)} rule(s) removed' if len(kept)<len(rules) else ''))


class RuleText(BaseModel):
    text:str=Field(min_length=3,max_length=300)


@app.post('/api/rules/draft')
async def draft(body:RuleText):
    """Claude drafts; nothing is enforced until the operator confirms."""
    if not os.getenv('ANTHROPIC_API_KEY'):raise HTTPException(503,'Claude is not configured. Set ANTHROPIC_API_KEY to draft rules from text.')
    landmarks=store.get('settings').get('landmarks',[])
    if not landmarks:return {'question':'Draw and name a landmark on the video first, for example the kitchen gate.',**state()}
    try:result=await draft_rule(claude_client(),os.getenv('CLAUDE_MODEL',DEFAULT_MODEL),body.text.strip(),landmarks)
    except Exception:result={'question':'Claude could not draft this rule right now. Try again, or rephrase it.'}  # Provider or output error: create nothing.
    if 'rule' not in result:return {**result,**state()}
    current=store.get('settings');current['rules']=current.get('rules',[])+[result['rule']]
    return {**result,**save_settings(current,'rule_drafted',f"Rule drafted · {result['rule']['summary']} (not active until confirmed)")}


@app.post('/api/rules/{identifier}/confirm')
def confirm_rule(identifier:str):
    current=store.get('settings');rule=next((r for r in current.get('rules',[]) if r['id']==identifier),None)
    if not rule:raise HTTPException(404,'Rule not found')
    rule['status']='active';rule['confirmed_at']=time.time()
    return save_settings(current,'rule_confirmed',f"Rule active · {rule['summary']}")


@app.delete('/api/rules/{identifier}')
def delete_rule(identifier:str):
    current=store.get('settings');rule=next((r for r in current.get('rules',[]) if r['id']==identifier),None)
    if not rule:raise HTTPException(404,'Rule not found')
    current['rules']=[r for r in current['rules'] if r['id']!=identifier]
    return save_settings(current,'rule_removed',f"Rule removed · {rule['summary']}")


class CalibrationBody(BaseModel):
    points:list[dict]=Field(max_length=20)


@app.post('/api/calibration')
def calibrate(body:CalibrationBody):
    from .predict import Calibration
    try:calibration=Calibration.fit(body.points)
    except ValueError as exc:raise HTTPException(422,str(exc))
    current=store.get('settings');current['calibration']=calibration.as_dict();store.put('settings',current)
    ignored=f' · {len(calibration.ignored)} point(s) ignored' if calibration.ignored else ''
    with store.db:store.event('calibration_saved',f'Floor calibration saved · average error {calibration.error_m:.2f} m{ignored}')
    configure_vision(current)
    return state()


@app.delete('/api/calibration')
def uncalibrate():
    current=store.get('settings');current.pop('calibration',None);store.put('settings',current)
    with store.db:store.event('calibration_cleared','Floor calibration removed · predictive warnings off')
    configure_vision(current)
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


@app.get('/api/clips/{name}')
def clip(name:str):
    if not name.endswith('.webm') or not name[:-5].isalnum():raise HTTPException(404)
    path=DATA_DIR/'clips'/name
    if not path.is_file():raise HTTPException(404)
    return FileResponse(path,media_type='video/webm')


@app.get('/api/incidents/{identifier}/report')
async def incident_report(identifier:str,ai:bool=True):
    """Facts come only from stored data; Claude may phrase them, with every line citing facts."""
    incident=store.incident(identifier)
    if not incident:raise HTTPException(404,'Incident not found')
    attempts=[a for a in store.attempts() if a['incident_id']==identifier]
    facts=build_facts(incident,store.incident_events(identifier),attempts,[caregiver_name(0),caregiver_name(1)])
    lines,removed=None,0
    if ai and os.getenv('ANTHROPIC_API_KEY'):
        try:lines,removed=await ai_lines(claude_client(),os.getenv('CLAUDE_MODEL',DEFAULT_MODEL),facts)
        except Exception:lines=None  # Claude failed: the plain timeline is still a complete report.
    return {'markdown':render(incident,facts,lines or None),'source':'claude' if lines else 'facts','removed_lines':removed,'facts':facts}


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


async def process_frame(frame,feed=None):
    """Analyze one frame. `feed` is an SRC-5 camera with its own engine, clip buffer and incident tag; None is cam-01."""
    global vision_state,processing
    engine,clips=(feed.vision,feed.recorder) if feed else (vision,recorder)
    try:
        result=await engine.process_frame(frame)
        session=store.get('session')
        if session['id']!=frame['session_id'] or session['epoch']!=frame['epoch']:return None
        if feed:feed.state=result
        else:vision_state=result
        people=result.get('overlays',[])
        jpeg=base64.b64decode(frame['image'].split(',')[-1]) if frame.get('image') else b''
        finished=clips.add(frame['media_time_ms'],jpeg,people) if jpeg else []
        for observation in result.get('observations',[]):
            kind=observation.get('kind')
            if kind=='review':
                store.annotate(observation['target_kind'],observation['review'],feed.id if feed else PRIMARY_CAMERA)
            elif kind=='approach':
                # A pre-warning is transient: history only, never an incident or a call.
                with store.db:store.event('approach_warning',observation['observations'][0])
            elif kind in KINDS:
                incident=store.observe(kind,observation.get('observations',[]),observation.get('origin','local_rule'),observation.get('priority','high'),camera=feed.camera if feed else None)
                if 'media_time_ms' not in incident:
                    incident['media_time_ms']=frame['media_time_ms']
                    incident['source_key']=feed.id if feed else session.get('media_id') if session['source_type']=='recorded' else session['source_type']
                    with store.db:store.save_incident(incident)
                if jpeg and not incident.get('clip_requested') and incident['status']=='open':
                    clips.start(incident['id'],frame['media_time_ms']);incident['clip_requested']=True
                    with store.db:store.save_incident(incident)
                if not incident.get('evidence_url'):
                    evidence=observation.get('evidence_image') if observation.get('origin')=='model' else frame['image']
                    if not evidence:continue
                    raw=await asyncio.to_thread(blur_jpeg,base64.b64decode(evidence.split(',')[-1]),people); filename=uid()+'.jpg';(DATA_DIR/filename).write_bytes(raw)
                    incident['evidence_url']='/api/media/'+filename
                    with store.db:store.save_incident(incident)
        for incident_id,frames in finished:
            await save_clip(incident_id,frames)
        return result
    except Exception as exc:
        failed={'overlays':[],'health':{'tracking':'degraded','review':'degraded'},'limitations':['Analysis failed: '+type(exc).__name__]}
        if feed:feed.state=failed
        else:vision_state=failed
    finally:
        if feed:feed.processing=False
        else:processing=False
recorder=ClipRecorder()


def submit_frame(data):
    """One path for browser and server-captured frames: latest frame wins, stale frames never change state."""
    global processing
    if processing:return None
    if not store.accept_frame(data):raise HTTPException(409,'Stale frame, epoch, or inactive session')
    if not vision:raise HTTPException(503,'Vision not initialized')
    processing=True
    return asyncio.create_task(process_frame(data))


@app.post('/api/frames')
async def frame(body:Frame):
    if store.get('session').get('source_type')=='server_camera':raise HTTPException(409,'The server camera is the source; browser frames are not analyzed')
    # Each response carries the latest overlays, so boxes refresh at the frame rate rather than the 1.5 s state poll.
    if submit_frame(body.model_dump()) is None:return {'accepted':False,'reason':'busy; latest frame wins','overlays':vision_state.get('overlays',[])}
    return {'accepted':True,'overlays':vision_state.get('overlays',[])}


async def submit_captured(image,frame_seq,media_time_ms):
    """SRC-4: a server-captured frame, stamped with the current session. Returns its overlays, or None if not analyzed."""
    session=store.get('session')
    try:task=submit_frame({'session_id':session['id'],'epoch':session['epoch'],'frame_seq':frame_seq,'media_time_ms':media_time_ms,'image':image})
    except HTTPException:return None  # Paused, stopped or stale: the picture still updates, without overlays.
    if task is None:return None
    result=await asyncio.shield(task)  # Stopping capture never cuts an analysis short.
    return result.get('overlays',[]) if result else None


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
            store.transition(incident['id'],'acknowledge',caregiver_name(attempt['step']),channel='keypad');await cancel_calls(incident['id'])
        elif form.get('Digits')=='2':
            store.decline(incident['id'],caregiver_name(attempt['step']))
    return RawResponse('<Response><Say>Thank you.</Say><Hangup/></Response>',media_type='application/xml')


class VoiceAck(BaseModel):
    token:str=Field(min_length=8,max_length=200)
    decision:Literal['acknowledge','decline']


@app.post('/webhooks/voice/ack')
async def voice_ack(request:Request,body:VoiceAck):
    """Called by the Cartesia agent's webhook tool. The reply is plain text the agent can say."""
    secret=os.getenv('VOICE_WEBHOOK_SECRET','')
    if not secret or not secrets.compare_digest(request.headers.get('authorization',''),'Bearer '+secret):raise HTTPException(403,'Invalid voice webhook credentials')
    digest=token_hash(body.token)
    attempt=next((a for a in store.attempts() if secrets.compare_digest(a['payload'].get('ack_token_sha256',''),digest)),None)
    if not attempt or attempt['payload'].get('ack_used'):raise HTTPException(409,'Unknown or already used acknowledgment token')
    store.finish_job(attempt['id'],attempt['status'],{**attempt['payload'],'ack_used':True})  # Single use, before acting.
    incident=store.incident(attempt['incident_id']);session=store.get('session');name=caregiver_name(attempt['step'])
    if not incident or incident['session_id']!=session['id'] or incident['epoch']!=session['epoch']:
        return PlainTextResponse('This alert is no longer active. Thank you, you can hang up.')
    if incident['status']!='open':
        return PlainTextResponse(f"This alert is already handled by {incident.get('assigned_responder') or 'another caregiver'}. Thank you, you can hang up.")
    if body.decision=='acknowledge':
        store.transition(incident['id'],'acknowledge',name,channel='voice');await cancel_calls(incident['id'])
        return PlainTextResponse(f"Acknowledged. {name} is now responsible for this alert. Please go to the {incident['room']} now.")
    try:store.decline(incident['id'],name)
    except ValueError:return PlainTextResponse('This alert can no longer be passed on. Thank you.')
    return PlainTextResponse('Understood. The backup caregiver will be called now.')


@app.get('/call-media/{token}')
def audio(token:str):
    entry=calls.audio.get(token)
    if not entry or entry[0]<time.time():raise HTTPException(404)
    return RawResponse(entry[1],media_type='audio/wav')
