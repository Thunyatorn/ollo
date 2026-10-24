import { useServices } from '../services';

type Level = 'ok' | 'warn' | 'bad';

function Row({ label, level, children }: { label: string; level: Level; children: React.ReactNode }) {
  const pill = level === 'ok' ? 'ok' : level === 'warn' ? 'medium' : 'high';
  return <tr><th scope="row" className="small">{label}</th><td className="small"><span className={`pill ${pill}`}>{level === 'ok' ? 'OK' : level === 'warn' ? 'CHECK' : 'PROBLEM'}</span> {children}</td></tr>;
}

// What is running, in plain words, so a failure is noticed here instead of during an alert.
export default function SystemStatus() {
  const { vision, worker } = useServices();

  if (vision === undefined || worker === undefined) return <div className="card"><h2>System</h2><p className="muted small">Checking…</p></div>;
  const buzzers = Object.keys(vision?.buzzers ?? {});
  return (
    <div className="card">
      <h2>System</h2>
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
            {worker.claude === 'on' ? `On: second opinions, rule drafts and written reports.${worker.claude_cost_usd != null ? ` About $${worker.claude_cost_usd.toFixed(3)} spent in ${worker.claude_calls ?? 0} calls since the worker started.` : ''}` : 'Off: plain reports and keyword rules.'}
          </Row>
        </>)}
      </tbody></table>
    </div>
  );
}
