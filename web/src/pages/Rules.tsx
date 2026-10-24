import { useReducer, useTable } from 'spacetimedb/react';
import { reducers, tables } from '../module_bindings';
import RuleForm from '../components/RuleForm';
import { useState } from 'react';

export default function Rules() {
  const [zones] = useTable(tables.zone);
  const confirm = useReducer(reducers.confirmZone);
  const update = useReducer(reducers.updateZone);
  const [error, setError] = useState('');

  async function act(fn: () => Promise<void>) {
    setError('');
    try { await fn(); } catch { setError('That change did not go through.'); }
  }
  const when = (z: (typeof zones)[number]) => z.schedule.named ? z.schedule.named.replace(/_/g, ' ') : z.schedule.startMin != null ? 'set hours' : 'always';

  return (
    <section className="secondary-page stack">
      <div>
        <span className="eyebrow">MAKE NESTWATCH YOURS</span>
        <h1>Rules</h1>
        <p className="page-lead">Say where children should not go, and when. Nothing is enforced until you confirm it.</p>
      </div>
      <RuleForm />
      <div className="card">
        <h2>Active and draft rules:</h2>
        {error && <div className="banner" role="alert">{error}</div>}
        {zones.length === 0 ? <p className="muted">No rules yet.</p> : (
          <table>
            <thead><tr><th>Area</th><th>Severity</th><th>When</th><th>Status</th><th /></tr></thead>
            <tbody>
              {zones.map(z => (
                <tr key={z.id}>
                  <td>{z.name}</td>
                  <td><span className={`pill ${z.severity}`}>{z.severity}</span></td>
                  <td className="small">{when(z)}</td>
                  <td><span className={`pill ${z.status === 'active' ? 'ok' : 'off'}`}>{z.status}</span></td>
                  <td style={{ textAlign: 'right' }}>
                    {z.status === 'draft' && <button className="btn" onClick={() => act(() => confirm({ zoneId: z.id }))}>Confirm</button>}
                    {z.status === 'active' && <button className="btn secondary" onClick={() => act(() => update({ zoneId: z.id, name: z.name, severity: z.severity, schedule: z.schedule, escalation: z.escalation, status: 'off' }))}>Turn off</button>}
                    {z.status === 'off' && <button className="btn secondary" onClick={() => act(() => update({ zoneId: z.id, name: z.name, severity: z.severity, schedule: z.schedule, escalation: z.escalation, status: 'active' }))}>Turn on</button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  );
}
