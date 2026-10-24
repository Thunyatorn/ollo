import { Link, useParams } from 'react-router-dom';
import { useTable } from 'spacetimedb/react';
import { tables } from '../module_bindings';
import ReportView from '../components/ReportView';
import { useReportTitle } from '../lib';

export default function PhoneReports() {
  const { id } = useParams();
  const [reports] = useTable(tables.report);
  const title = useReportTitle();
  const current = id ? reports.find(r => r.id === id) : undefined;

  if (current) return (
    <div className="stack"><Link to="/m/reports">← All reports</Link><ReportView report={current} /></div>
  );
  return (
    <div className="card stack">
      <h2>Reports</h2>
      {reports.length === 0 && <p className="muted">No reports yet.</p>}
      {[...reports].reverse().map(r => (
        <Link key={r.id} to={`/m/reports/${r.id}`} className="row" style={{ padding: '.5rem 0', textDecoration: 'none' }}>
          <span className="grow">{title(r)}</span><span className="pill off">{r.status}</span>
        </Link>
      ))}
    </div>
  );
}
