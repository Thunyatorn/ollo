import { useEffect, useRef, useState } from 'react';
import { useReducer, useTable } from 'spacetimedb/react';
import { reducers, tables } from '../module_bindings';
import FloorPlan from '../components/FloorPlan';
import { VISION_URL } from '../config';

const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '');
type P = { x: number; y: number };

export default function Setup() {
  const [rooms] = useTable(tables.room);
  const [zones] = useTable(tables.zone);
  const [areas] = useTable(tables.namedArea);
  const [cameras] = useTable(tables.camera);
  const upsertRoom = useReducer(reducers.upsertRoom);
  const createZone = useReducer(reducers.createZone);
  const upsertArea = useReducer(reducers.upsertNamedArea);
  const upsertCamera = useReducer(reducers.upsertCamera);
  const room = rooms[0];

  const [msg, setMsg] = useState('');
  const say = (m: string) => setMsg(m);
  async function guard(fn: () => Promise<unknown>, ok: string) {
    setMsg('');
    try { await fn(); say(ok); } catch (e) { say(e instanceof Error ? e.message : 'That did not work.'); }
  }

  // room form
  const [rName, setRName] = useState('Main room');
  const [rW, setRW] = useState(4);
  const [rH, setRH] = useState(3);
  useEffect(() => { if (room) { setRName(room.name); setRW(room.widthM); setRH(room.heightM); } }, [room?.id]);

  // drawing
  const [pts, setPts] = useState<P[]>([]);
  const [zName, setZName] = useState('');
  const [sev, setSev] = useState('high');

  // camera calibration
  const [camId, setCamId] = useState('cam1');
  const [camName, setCamName] = useState('Camera 1');
  const [imgPts, setImgPts] = useState<P[]>([]);
  const [floorPts, setFloorPts] = useState<P[]>([]);
  const [snapOk, setSnapOk] = useState(true);
  const [snapVersion, setSnapVersion] = useState(0);            // the picture stays still while you click; "New picture" refreshes it
  const [calNote, setCalNote] = useState('');
  const imgRef = useRef<HTMLImageElement>(null);

  useEffect(() => {
    // 4 corners + 2 check points (wall midpoints): with only 4 points a mis-click cannot be detected (MATH.md 1.6)
    if (room) setFloorPts([{ x: 0, y: 0 }, { x: room.widthM, y: 0 }, { x: room.widthM, y: room.heightM }, { x: 0, y: room.heightM },
                           { x: room.widthM / 2, y: 0 }, { x: room.widthM / 2, y: room.heightM }]);
  }, [room?.id, room?.widthM, room?.heightM]);

  function clickImage(e: React.MouseEvent<HTMLImageElement>) {
    if (imgPts.length >= floorPts.length) return;
    const img = e.currentTarget;
    const r = img.getBoundingClientRect();
    // store in the image's own pixel coordinates, which is what the vision service expects
    const x = ((e.clientX - r.left) / r.width) * img.naturalWidth;
    const y = ((e.clientY - r.top) / r.height) * img.naturalHeight;
    setImgPts([...imgPts, { x: Math.round(x), y: Math.round(y) }]);
  }

  async function calibrate() {
    setCalNote('');
    await guard(async () => {
      const res = await fetch(`${VISION_URL}/calibrate/${camId}`, {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ image_points: imgPts.map(p => [p.x, p.y]), floor_points: floorPts.map(p => [p.x, p.y]) }),
      });
      const out = await res.json().catch(() => ({})) as {
        ok?: boolean; homography?: number[][]; reprojection_error?: number; warnings?: string[]; bad_point?: number | null; detail?: string;
      };
      if (!res.ok || !out.ok || !out.homography) {
        // the service explains itself: a named bad point, a degenerate layout, or bad input
        throw new Error(out.detail ?? (out.warnings?.join(' ') || 'The camera computer rejected the points.'));
      }
      await upsertCamera({ id: camId, roomId: room!.id, name: camName, homography: out.homography.flat(), blindSpots: [] });
      setImgPts([]);
      setCalNote(`Calibrated with ${floorPts.length} points: average error ${((out.reprojection_error ?? 0) * 100).toFixed(1)} cm.` +
                 (out.warnings?.length ? ' Note: ' + out.warnings.join(' ') : ''));
    }, '');
  }

  return (
    <div className="stack">
      <h1>Setup</h1>
      {msg && <div className="banner" role="status">{msg}</div>}

      <form className="card row" onSubmit={e => { e.preventDefault(); guard(() => upsertRoom({ id: room?.id ?? 'main', name: rName, widthM: rW, heightM: rH, floorPlan: room?.floorPlan ?? '' }), 'Room saved.'); }}>
        <div className="grow"><label htmlFor="rn">Room name</label><input id="rn" value={rName} onChange={e => setRName(e.target.value)} required /></div>
        <div><label htmlFor="rw">Width (m)</label><input id="rw" type="number" min="1" step="0.1" value={rW} onChange={e => setRW(+e.target.value)} /></div>
        <div><label htmlFor="rh">Depth (m)</label><input id="rh" type="number" min="1" step="0.1" value={rH} onChange={e => setRH(+e.target.value)} /></div>
        <button className="btn" style={{ alignSelf: 'end' }}>{room ? 'Save room' : 'Create room'}</button>
      </form>

      {room && (
        <div className="room-layout">
          <div className="stack">
            <h2>Draw an area:</h2>
            <FloorPlan room={room} zones={zones.filter(z => z.roomId === room.id)} draft={pts} onPoint={p => setPts([...pts, p])} />
            <p className="small muted">Click the corners of the area on the plan. Each square is 1 m.</p>
          </div>
          <div className="card stack">
            <div><label htmlFor="zn">Name</label><input id="zn" value={zName} onChange={e => setZName(e.target.value)} placeholder="Stairs" /></div>
            <div>
              <label htmlFor="zs">How serious is it if a child goes here?</label>
              <select id="zs" value={sev} onChange={e => setSev(e.target.value)}>
                <option value="high">High — buzz now, call the backup quickly</option>
                <option value="medium">Medium</option>
                <option value="low">Low — show in the app only</option>
              </select>
            </div>
            <div className="row">
              <button className="btn" disabled={pts.length < 3 || !zName} onClick={() => guard(async () => { await createZone({ roomId: room.id, name: zName, polygon: pts, severity: sev, schedule: { named: undefined, startMin: undefined, endMin: undefined }, escalation: 'buzzer_then_call' }); setPts([]); setZName(''); }, 'Zone is on.')}>Make it a zone</button>
              <button className="btn secondary" disabled={pts.length < 3 || !zName} onClick={() => guard(async () => { await upsertArea({ id: `na_${slug(zName)}`, roomId: room.id, name: zName, polygon: pts }); setPts([]); setZName(''); }, 'Saved as a named area for spoken rules.')}>Save as named area</button>
              <button className="btn secondary" onClick={() => setPts([])} disabled={!pts.length}>Clear</button>
            </div>
            <h3>Named areas:</h3>
            {areas.length === 0 ? <p className="small muted">None yet. Rules like "keep kids away from the kitchen gate" need the area saved here first.</p> : areas.map(a => <div key={a.id} className="small">{a.name}</div>)}
          </div>
        </div>
      )}

      {room && (
        <div className="card stack">
          <h2>Camera calibration:</h2>
          <div className="row">
            <div><label htmlFor="ci">Camera ID</label><input id="ci" value={camId} onChange={e => setCamId(e.target.value)} list="cams" /><datalist id="cams">{cameras.map(c => <option key={c.id} value={c.id} />)}</datalist></div>
            <div><label htmlFor="cm">Name</label><input id="cm" value={camName} onChange={e => setCamName(e.target.value)} /></div>
            <button className="btn secondary" style={{ alignSelf: 'end' }} onClick={() => guard(() => upsertCamera({ id: camId, roomId: room.id, name: camName, homography: [], blindSpots: [] }), 'Camera added.')}>Add camera</button>
          </div>
          <p className="small muted">Put a taped marker on the floor at each point below, measure it (meters from the room's top-left corner), then click the markers in the picture in the same order. Six points let the computer catch a wrong click.</p>
          <div className="room-layout">
            <div>
              {snapOk ? (
                <div style={{ position: 'relative' }}>
                  <img ref={imgRef} src={`${VISION_URL}/snapshot/${camId}?v=${snapVersion}`} alt="Camera view" onClick={clickImage} onError={() => setSnapOk(false)} onLoad={() => setSnapOk(true)} style={{ width: '100%', borderRadius: 12, cursor: 'crosshair' }} />
                  {imgPts.map((p, i) => imgRef.current && (
                    <span key={i} style={{ position: 'absolute', left: `${(p.x / imgRef.current.naturalWidth) * 100}%`, top: `${(p.y / imgRef.current.naturalHeight) * 100}%`, transform: 'translate(-50%,-50%)', background: 'var(--brand)', color: 'var(--brand-ink)', borderRadius: 99, width: 22, height: 22, display: 'grid', placeItems: 'center', fontSize: 12, fontWeight: 800 }}>{i + 1}</span>
                  ))}
                </div>
              ) : (
                <div className="banner" role="status">Cannot reach the camera computer at {VISION_URL}. It has to be running on this network.
                  <div><button className="btn secondary" onClick={() => setSnapOk(true)}>Try again</button></div></div>
              )}
            </div>
            <div className="stack">
              {floorPts.map((p, i) => (
                <div key={i} className="row small">
                  <strong>Point {i + 1}</strong>
                  <input aria-label={`Point ${i + 1} x`} type="number" step="0.01" value={p.x} onChange={e => setFloorPts(floorPts.map((q, j) => j === i ? { ...q, x: +e.target.value } : q))} style={{ width: 90 }} />
                  <input aria-label={`Point ${i + 1} y`} type="number" step="0.01" value={p.y} onChange={e => setFloorPts(floorPts.map((q, j) => j === i ? { ...q, y: +e.target.value } : q))} style={{ width: 90 }} />
                  <span className="muted">{imgPts[i] ? 'clicked' : 'not clicked'}</span>
                </div>
              ))}
              <div className="row">
                <button className="btn" disabled={imgPts.length !== floorPts.length || floorPts.length < 4} onClick={calibrate}>Calibrate</button>
                <button className="btn secondary" onClick={() => setImgPts([])} disabled={!imgPts.length}>Reset clicks</button>
                <button className="btn secondary" onClick={() => { setImgPts([]); setSnapVersion(v => v + 1); }}>New picture</button>
              </div>
              <div className="row">
                <button className="btn secondary" disabled={floorPts.length >= 12} onClick={() => setFloorPts([...floorPts, { x: 0, y: 0 }])}>Add point</button>
                <button className="btn secondary" disabled={floorPts.length <= 4} onClick={() => { setFloorPts(floorPts.slice(0, -1)); setImgPts(imgPts.slice(0, floorPts.length - 1)); }}>Remove last point</button>
              </div>
              <p className="small muted">{floorPts.length} points{floorPts.length < 6 ? ': with fewer than 6, a wrong click cannot be detected.' : '. The last two are check points: put markers there too.'}</p>
              {calNote && <div className="card small" role="status">{calNote}</div>}
              <div className="row">
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
