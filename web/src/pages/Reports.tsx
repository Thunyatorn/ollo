import { Link, useParams } from 'react-router-dom';
import { useTable } from 'spacetimedb/react';
import { tables } from '../module_bindings';
import ReportView from '../components/ReportView';
import { useReportTitle } from '../lib';

export default function Reports() {
  const { id } = useParams();
  const [reports] = useTable(tables.report);
  const title = useReportTitle();
  const current = id ? reports.find(r => r.id === id) : undefined;

  return (
    <div className="stack">
      <h1>Reports</h1>
      {reports.length === 0 ? (
        <div className="card"><p className="muted">No reports yet. A report is written after an alert is closed.</p></div>
      ) : (
        <div className="room-layout">
          <div className="card">
            {[...reports].reverse().map(r => (
              <div key={r.id} className="row" style={{ padding: '.5rem 0', borderBottom: '1px solid var(--line)' }}>
                <Link to={`/reports/${r.id}`} className="grow">{title(r)}</Link>
                <span className="pill off">{r.status}</span>
              </div>
            ))}
          </div>
          {current ? <ReportView report={current} /> : <div className="card muted">Choose a report.</div>}
        </div>
      )}
    </div>
  );
}
