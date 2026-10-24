import { useState } from 'react';
import { useReducer, useTable } from 'spacetimedb/react';
import { reducers, tables } from '../module_bindings';
import type { Report } from '../module_bindings/types';
import { VISION_URL } from '../config';
import { formatClock, tsMs } from '../lib';

export default function ReportView({ report }: { report: Report }) {
  const [events] = useTable(tables.incidentEvent);
  const addNote = useReducer(reducers.addCaregiverNote);
  const [note, setNote] = useState(report.caregiverNote ?? '');
  const [saved, setSaved] = useState(false);
  const [msg, setMsg] = useState('');
  const byId = new Map(events.map(e => [e.id, e]));

  async function save() {
    setMsg('');
    try { await addNote({ reportId: report.id, text: note }); setSaved(true); }
    catch { setMsg('Could not save your note.'); }
  }
  async function share() {
    const text = `${report.summary}\n\n${report.lines.map(l => `- ${l.text}`).join('\n')}${note ? `\n\nNote: ${note}` : ''}`;
    try {
      if (navigator.share) await navigator.share({ title: 'Incident report', text });
      else { await navigator.clipboard.writeText(text); setMsg('Copied to the clipboard.'); }
    } catch { /* user cancelled */ }
  }

  return (
    <div className="card stack">
      <div className="row">
        <h2 className="grow">{report.kind === 'daily' ? 'Daily summary' : 'Incident report'}</h2>
        <span className="pill off">{report.status}</span>
      </div>
      <p>{report.summary}</p>
      {report.lines.length > 0 && (
        <table>
          <thead><tr><th>Time</th><th>What happened</th></tr></thead>
          <tbody>
            {report.lines.map((l, i) => {
              const ev = byId.get(l.eventId);
              return (
                <tr key={i}>
                  <td className="small muted" style={{ whiteSpace: 'nowrap' }}>{ev ? formatClock(tsMs(ev.at)) : ''}</td>
                  <td>{l.text}{ev?.clipRef && <> <a className="small" href={`${VISION_URL}/clips/${ev.clipRef}`} target="_blank" rel="noreferrer">clip</a></>}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      <div>
        <label htmlFor={`note-${report.id}`}>Your note (your own words)</label>
        <textarea id={`note-${report.id}`} rows={3} value={note} onChange={e => { setNote(e.target.value); setSaved(false); }} />
      </div>
      <div className="row">
        <button className="btn" onClick={save} disabled={saved || note === (report.caregiverNote ?? '')}>{saved ? 'Saved' : 'Save note'}</button>
        <button className="btn secondary" onClick={share}>Share</button>
        <button className="btn secondary" onClick={() => window.print()}>Print / PDF</button>
      </div>
      {msg && <div className="banner" role="status">{msg}</div>}
    </div>
  );
}
