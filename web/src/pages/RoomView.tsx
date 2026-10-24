import { useMemo, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useTable } from 'spacetimedb/react';
import { LockKeyhole, Map as MapIcon, Maximize2, Ruler, Settings2, Shield, Video } from 'lucide-react';
import { tables } from '../module_bindings';
import FloorPlan from '../components/FloorPlan';
import EventTrace from '../components/EventTrace';
import LiveCamera from '../components/LiveCamera';
import SystemStatus from '../components/SystemStatus';
import { OPEN_STATES, formatClock, tsMs, useMe } from '../lib';
import { VISION_URL } from '../config';
import { useServices } from '../services';

// The reference build's monitor (commit 17cca7a): the camera card with its toolbar and floor-plan inset, and the
// event trace beside it. Under the camera: what the system is doing, and today's log.
export default function RoomView() {
  const { me } = useMe();
  const navigate = useNavigate();
  const [rooms] = useTable(tables.room);
  const [zones] = useTable(tables.zone);
  const [positions] = useTable(tables.trackPosition);
  const [alerts] = useTable(tables.alert);
  const [cameras] = useTable(tables.camera);
  const [caregivers] = useTable(tables.caregiver);
  const [events] = useTable(tables.incidentEvent);
  const { vision } = useServices();
  const stage = useRef<HTMLDivElement>(null);
  const [floorOpen, setFloorOpen] = useState(true);
  const [selected, setSelected] = useState<string | null>(null);
  const [tagWho, setTagWho] = useState('');
  const [tagMsg, setTagMsg] = useState('');

  const room = rooms[0];
  const today = useMemo(() => {
    const start = new Date(); start.setHours(0, 0, 0, 0);
    return events.filter(e => tsMs(e.at) >= start.getTime()).sort((a, b) => tsMs(b.at) - tsMs(a.at)).slice(0, 30);
  }, [events]);

  if (!me) return null;
  if (!room) {
    return (
      <section className="secondary-page">
        <span className="eyebrow">MONITOR</span>
        <h1>No room yet</h1>
        <p className="page-lead">Create the room and its camera in <Link to="/settings">Settings</Link>.</p>
      </section>
    );
  }

  const roomPositions = positions.filter(p => p.roomId === room.id);
  const roomCameras = cameras.filter(c => c.roomId === room.id);
  const cam = roomCameras[0];
  const roomZones = zones.filter(z => z.roomId === room.id);
  const children = roomPositions.filter(p => p.kind === 'child' && p.visible);
  const adults = roomPositions.filter(p => p.kind === 'adult' && p.visible);
  const open = alerts.filter(a => OPEN_STATES.includes(a.status));
  const alertTracks = new Set(open.filter(a => a.status !== 'owned').map(a => a.trackId));
  const blind = roomCameras.flatMap(c => c.blindSpots.map(b => b.points));
  const camOffline = cam ? cam.status !== 'online' : true;
  const activeZones = roomZones.filter(z => z.status === 'active').length;
  const labelOf = (trackId: string) => positions.find(p => p.trackId === trackId)?.label;

  const badge = vision === null ? 'Camera computer not reachable'
    : camOffline || vision?.camera_online === false ? 'Analysis unavailable'
    : vision?.calibrated === false ? 'Monitoring · not calibrated' : 'Monitoring active';
  const badgeRed = vision === null || camOffline || vision?.camera_online === false;

  async function tagAdult() {
    setTagMsg('');
    const who = caregivers.find(c => c.id === tagWho);
    if (!selected || !who) return;
    try {
      const res = await fetch(`${VISION_URL}/tag-adult`, {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ track_id: selected, caregiver_id: who.id, caregiver_name: who.name }),
      });
      if (!res.ok) throw new Error(String(res.status));
      setTagMsg(`Tagged as ${who.name}.`);
      setSelected(null);
    } catch {
      setTagMsg('Could not reach the camera computer. Is it on this network?');
    }
  }

  return (
    <section className="monitor-grid">
      <div className="monitor-column">
        <div className="camera-card">
          <div className="camera-toolbar">
            <div>
              <Video size={16} />
              <span className="camera-name">{room.name}</span>
              {cam && <span className="camera-id">{cam.id.toUpperCase()}</span>}
            </div>
            <div>
              <span className="record-label"><span /> {cam ? 'LIVE CAMERA' : 'NO CAMERA'}</span>
              <button className={`icon-button ${floorOpen ? 'enabled' : ''}`} title="Floor plan" aria-label="Floor plan" onClick={() => setFloorOpen(v => !v)}><MapIcon size={16} /></button>
              <button className="icon-button" title="Rules and restricted areas" aria-label="Rules and restricted areas" onClick={() => navigate('/rules')}><Shield size={16} /></button>
              <button className="icon-button" title="Calibrate the floor" aria-label="Calibrate the floor" onClick={() => navigate('/settings')}><Ruler size={16} /></button>
              <button className="icon-button" title="Fullscreen" aria-label="Fullscreen" onClick={() => stage.current?.requestFullscreen?.()}><Maximize2 size={16} /></button>
            </div>
          </div>
          <div className={`camera-stage ${badgeRed ? 'offline' : ''}`} ref={stage}>
            {cam ? <LiveCamera cameraId={cam.id} name={cam.name} /> : <div className="server-frame waiting">No camera is set up yet. Add one in Settings.</div>}
            <div className="on-video-top">
              <div className="source-badge">
                <span className={`status-dot ${badgeRed ? 'red' : ''}`} />
                {badge}
                <span className="island-divider" />
                <span>{children.length} {children.length === 1 ? 'child' : 'children'} · {adults.length} {adults.length === 1 ? 'adult' : 'adults'}</span>
              </div>
            </div>
            {floorOpen && (
              <div className="floor-plan">
                <span className="floor-plan-title">Floor plan · meters</span>
                <FloorPlan room={room} zones={roomZones} positions={roomPositions} blindSpots={blind} alertTracks={alertTracks} showPath onTrackClick={setSelected} />
                <p>Circles are children, squares are adults. Click a mark to tag an adult.</p>
                {selected && (
                  <div className="tagger">
                    <span>Track {labelOf(selected) ?? selected} is:</span>
                    <select value={tagWho} onChange={e => setTagWho(e.target.value)} aria-label="Caregiver">
                      <option value="">choose…</option>
                      {caregivers.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
                    </select>
                    <div className="row">
                      <button className="btn" disabled={!tagWho} onClick={tagAdult}>Tag as adult</button>
                      <button className="btn secondary" onClick={() => setSelected(null)}>Cancel</button>
                    </div>
                  </div>
                )}
                {tagMsg && <p role="status">{tagMsg}</p>}
              </div>
            )}
            <div className="video-footer">
              <span><LockKeyhole size={11} /> Faces blurred · no identity recognition · stays on the daycare network</span>
              <span className={`analysis-rate ${vision?.fps !== undefined && vision.fps < 8 ? 'low' : ''}`}>
                {vision?.fps !== undefined ? `Pose · ${vision.fps.toFixed(1)} fps` : 'NESTWATCH / 01'}
              </span>
            </div>
          </div>
        </div>
        <div className="monitor-footer">
          <span>{room.name} · {activeZones} {activeZones === 1 ? 'zone' : 'zones'} enabled{camOffline && cam ? ` · ${cam.name} ${cam.status.replace('_', ' ')}` : ''}</span>
          <Link to="/settings"><Settings2 size={12} /> Monitoring settings</Link>
        </div>

        <div className="monitor-lower">
          <SystemStatus />
          <div className="card">
            <h2>Today</h2>
            {today.length === 0 ? <p className="muted small">Nothing yet.</p> : (
              <table><tbody>
                {today.map(e => (
                  <tr key={e.id}><td className="small muted mono" style={{ whiteSpace: 'nowrap' }}>{formatClock(tsMs(e.at))}</td><td className="small">{e.text}</td></tr>
                ))}
              </tbody></table>
            )}
          </div>
        </div>
      </div>
      <EventTrace me={me} />
    </section>
  );
}
