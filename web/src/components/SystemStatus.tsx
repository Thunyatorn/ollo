import { useEffect, useState } from 'react';
import { VISION_URL, WORKER_URL } from '../config';

type Level = 'ok' | 'warn' | 'bad';
interface Vision { camera_online?: boolean; fps?: number; calibrated?: boolean; spacetime_online?: boolean | null; buzzers?: Record<string, unknown>; alarm?: { active: boolean; reasons: string[] } }
interface Worker { claude?: string; calls?: string }

async function probe<T>(url: string): Promise<T | null> {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), 2500);
  try {
    const r = await fetch(url, { signal: ctl.signal, cache: 'no-store' });
    return r.ok ? await r.json() as T : null;
  } catch { return null; } finally { clearTimeout(timer); }
}

function Row({ label, level, children }: { label: string; level: Level; children: React.ReactNode }) {
  const pill = level === 'ok' ? 'ok' : level === 'warn' ? 'medium' : 'high';
  return <tr><th scope="row" className="small">{label}</th><td className="small"><span className={`pill ${pill}`}>{level === 'ok' ? 'OK' : level === 'warn' ? 'CHECK' : 'PROBLEM'}</span> {children}</td></tr>;
}

// What is running, in plain words, so a failure is noticed here instead of during an alert.
export default function SystemStatus() {
  const [vision, setVision] = useState<Vision | null | undefined>(undefined);
  const [worker, setWorker] = useState<Worker | null | undefined>(undefined);

  useEffect(() => {
    let live = true;
    const tick = async () => {
      const [v, w] = await Promise.all([probe<Vision>(`${VISION_URL}/health`), probe<Worker>(`${WORKER_URL}/health`)]);
      if (live) { setVision(v); setWorker(w); }
    };
    void tick();
    const id = setInterval(tick, 5000);
    return () => { live = false; clearInterval(id); };
  }, []);

  if (vision === undefined || worker === undefined) return <div className="card"><h2>System:</h2><p className="muted small">Checking…</p></div>;
  const buzzers = Object.keys(vision?.buzzers ?? {});
  return (
    <div className="card">
      <h2>System:</h2>
      <table><tbody>
        {vision === null ? (
          <Row label="Camera computer" level="bad">Not reachable. Start the vision service on the camera computer (and be on the same network).</Row>
        ) : (<>
          <Row label="Camera" level={vision.camera_online ? 'ok' : 'bad'}>
            {vision.camera_online ? `Sending pictures${vision.fps ? `, ${vision.fps.toFixed(0)} per second` : ''}.` : 'The camera is not sending pictures.'}
          </Row>
          {vision.calibrated === false && <Row label="Floor positions" level="warn">Not calibrated, so the dots on the floor plan are not real. Calibrate in Setup.</Row>}
          {vision.spacetime_online === false && <Row label="Database link" level="bad">The camera computer cannot reach the database. Events wait, and high alerts sound the local alarm.</Row>}
          <Row label="Wrist buzzers" level={buzzers.length ? 'ok' : 'warn'}>{buzzers.length ? `${buzzers.length} connected (${buzzers.join(', ')}).` : 'None connected.'}</Row>
          {vision.alarm?.active && <Row label="Local alarm" level="bad">Sounding: {vision.alarm.reasons.join(', ')}.</Row>}
        </>)}
        {worker === null ? (
          <Row label="Worker" level="warn">Not reachable. Phone calls, reports and rule drafts are paused; alerts, buzzers and screens still work.</Row>
        ) : (<>
          <Row label="Phone calls" level={worker.calls === 'twilio' ? 'ok' : 'warn'}>
            {worker.calls === 'twilio' ? 'Real phone calls are on.' : 'Simulated: no real call is made.'}
          </Row>
          <Row label="Claude" level={worker.claude === 'on' ? 'ok' : 'warn'}>
            {worker.claude === 'on' ? 'On: second opinions, rule drafts and written reports.' : 'Off: plain reports and keyword rules.'}
          </Row>
        </>)}
      </tbody></table>
    </div>
  );
}
