import { useMemo, useState } from 'react';
import { useReducer, useTable } from 'spacetimedb/react';
import { reducers, tables } from '../module_bindings';
import FloorPlan from '../components/FloorPlan';
import AlertCard from '../components/AlertCard';
import LiveCamera from '../components/LiveCamera';
import SystemStatus from '../components/SystemStatus';
import { OPEN_STATES, eventLabel, formatClock, tsMs, useMe } from '../lib';
import { VISION_URL } from '../config';

const RANK: Record<string, number> = { high: 0, medium: 1, low: 2 };

export default function RoomView() {
  const { me } = useMe();
  const [rooms] = useTable(tables.room);
  const [zones] = useTable(tables.zone);
  const [positions] = useTable(tables.trackPosition);
  const [alerts] = useTable(tables.alert);
  const [cameras] = useTable(tables.camera);
  const [caregivers] = useTable(tables.caregiver);
  const [events] = useTable(tables.incidentEvent);
  const [selected, setSelected] = useState<string | null>(null);
  const [tagWho, setTagWho] = useState('');
  const [tagMsg, setTagMsg] = useState('');
  const [showAll, setShowAll] = useState(false);
  const [busyAll, setBusyAll] = useState(false);
  const closeAlert = useReducer(reducers.closeAlert);

  const room = rooms[0];
  const open = useMemo(
    () => alerts.filter(a => OPEN_STATES.includes(a.status)).sort((a, b) => RANK[a.severity] - RANK[b.severity] || tsMs(a.createdAt) - tsMs(b.createdAt)),
    [alerts]
  );
  const today = useMemo(() => {
    const start = new Date(); start.setHours(0, 0, 0, 0);
    return events.filter(e => tsMs(e.at) >= start.getTime()).sort((a, b) => tsMs(b.at) - tsMs(a.at)).slice(0, 40);
  }, [events]);

  if (!me) return null;
  if (!room) return <div className="card"><h2>No room yet</h2><p className="muted">Create one in Setup.</p></div>;

  const roomPositions = positions.filter(p => p.roomId === room.id);
  const roomCameras = cameras.filter(c => c.roomId === room.id);
  const children = roomPositions.filter(p => p.kind === 'child' && p.visible);
  const adults = roomPositions.filter(p => p.kind === 'adult' && p.visible);
  const alertTracks = new Set(open.filter(a => a.status !== 'owned').map(a => a.trackId));
  const blind = roomCameras.flatMap(c => c.blindSpots.map(b => b.points));
  const offline = roomCameras.filter(c => c.status !== 'online');
  const zoneName = (id: string) => zones.find(z => z.id === id)?.name;
  const labelOf = (trackId: string) => positions.find(p => p.trackId === trackId)?.label;

  const handled = open.filter(a => a.status === 'owned');
  const SHOWN = 4;
  const listed = showAll ? open : open.slice(0, SHOWN);

  async function resolveHandled() {
    setBusyAll(true);
    try { for (const a of handled) await closeAlert({ alertId: a.id, reason: 'resolved by caregiver' }); }
    finally { setBusyAll(false); }
  }

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
    <div className="stack">
      {offline.length > 0 && (
        <div className="banner" role="status">
          Camera problem: {offline.map(c => `${c.name} (${c.status.replace('_', ' ')})`).join(', ')}. Part of the room may not be watched.
        </div>
      )}
      <div className="page-head">
        <h1 className="grow">{room.name}</h1>
        <span className="count">{children.length} {children.length === 1 ? 'child' : 'children'} in view</span>
        <span className="count">{adults.length} {adults.length === 1 ? 'adult' : 'adults'}</span>
      </div>

      <div className="figure-row">
        {roomCameras.length === 0
          ? <div className="card muted">No camera is set up yet. Add one in Setup.</div>
          : roomCameras.map(c => <LiveCamera key={c.id} cameraId={c.id} name={c.name} />)}
        <div className="stack">
          <FloorPlan
            room={room} zones={zones.filter(z => z.roomId === room.id)} positions={roomPositions}
            blindSpots={blind} alertTracks={alertTracks} showPath onTrackClick={setSelected}
          />
          <p className="small muted figcap">Figure 2. Circles are children, squares are adults, hatched areas are restricted zones, grey hatching is not covered by a camera. Click a mark to tag an adult.</p>
          {selected && (
            <div className="card row">
              <span>Track {labelOf(selected) ?? selected}: this is</span>
              <select value={tagWho} onChange={e => setTagWho(e.target.value)} style={{ width: 'auto' }} aria-label="Caregiver">
                <option value="">choose…</option>
                {caregivers.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
              <button className="btn" disabled={!tagWho} onClick={tagAdult}>Tag as adult</button>
              <button className="btn secondary" onClick={() => setSelected(null)}>Cancel</button>
            </div>
          )}
          {tagMsg && <div className="banner" role="status">{tagMsg}</div>}
        </div>
      </div>

      <div className="room-layout">
        <section className="stack" aria-label="Open alerts">
          <h2 className="section-title">Open alerts <span className="muted">({open.length})</span></h2>
          {open.length === 0 ? (
            <div className="card"><p style={{ margin: 0 }}>None. All clear.</p></div>
          ) : (
            <>
              <div className="alert-grid">
                {listed.map(a => (
                  <div key={a.id}>
                    <AlertCard alert={a} me={me} caregivers={caregivers} via="dashboard" zoneName={zoneName(a.zoneId)} childLabel={labelOf(a.trackId)} />
                    {a.clipRef && <p className="small"><a href={`${VISION_URL}/clips/${a.clipRef}`} target="_blank" rel="noreferrer">View blurred clip</a> <span className="muted">(only on the daycare network)</span></p>}
                  </div>
                ))}
              </div>
              {(open.length > SHOWN || handled.length > 1) && (
                <div className="row small list-controls">
                  {open.length > SHOWN && (
                    <span>Showing {listed.length} of {open.length}, most urgent first.{' '}
                      <button className="linkbtn" onClick={() => setShowAll(v => !v)}>{showAll ? 'Show fewer' : `Show all ${open.length}`}</button></span>
                  )}
                  {handled.length > 1 && (
                    <button className="btn secondary" onClick={resolveHandled} disabled={busyAll}>{busyAll ? 'Resolving…' : `Resolve all ${handled.length} that are being handled`}</button>
                  )}
                </div>
              )}
            </>
          )}
        </section>

        <div className="stack">
          <SystemStatus />

          <div className="card">
            <h2>Cameras:</h2>
            {roomCameras.length === 0 ? <p className="muted small">No cameras set up.</p> : roomCameras.map(c => (
              <div key={c.id} className="row small"><span className="grow">{c.name}</span><span className={`pill ${c.status === 'online' ? 'ok' : 'medium'}`}>{c.status.replace('_', ' ')}</span></div>
            ))}
          </div>

          <div className="card">
            <h2>Today:</h2>
            {today.length === 0 ? <p className="muted small">Nothing yet.</p> : (
              <table><tbody>
                {today.map(e => (
                  <tr key={e.id}><td className="small muted" style={{ whiteSpace: 'nowrap' }}>{formatClock(tsMs(e.at))}</td><td className="small">{e.text}</td></tr>
                ))}
              </tbody></table>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
