import { useRef, useState } from 'react';
import { useReducer, useTable } from 'spacetimedb/react';
import { reducers, tables } from '../module_bindings';
import { WORKER_URL } from '../config';
import { loadToken } from '../lib';
import FloorPlan from './FloorPlan';

interface Draft {
  zone_draft_id: string;
  area_name: string;
  schedule: unknown;
  severity: string;
  escalation: string;
  needs_drawing: boolean;
  question: string | null;
}

export default function RuleForm() {
  const [rooms] = useTable(tables.room);
  const [zones] = useTable(tables.zone);
  const confirm = useReducer(reducers.confirmZone);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [draft, setDraft] = useState<Draft | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [listening, setListening] = useState(false);
  const recRef = useRef<any>(null);

  const room = rooms[0];
  const SR = (window as any).SpeechRecognition ?? (window as any).webkitSpeechRecognition;

  function toggleMic() {
    if (listening) { recRef.current?.stop(); return; }
    const rec = new SR();
    rec.lang = navigator.language || 'en-US';
    rec.interimResults = false;
    rec.onresult = (e: any) => setText(prev => (prev ? prev + ' ' : '') + e.results[0][0].transcript);
    rec.onend = () => setListening(false);
    rec.onerror = () => setListening(false);
    recRef.current = rec;
    setListening(true);
    rec.start();
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!room) return;
    setBusy(true); setError(''); setDraft(null); setConfirmed(false);
    try {
      const res = await fetch(`${WORKER_URL}/rules/interpret`, {
        method: 'POST',
        headers: { 'content-type': 'application/json', authorization: `Bearer ${loadToken() ?? ''}` },
        body: JSON.stringify({ room_id: room.id, text }),
      });
      if (!res.ok) throw new Error(String(res.status));
      setDraft(await res.json());
    } catch {
      setError('The rule helper is not reachable right now. Your text was not lost; try again in a moment.');
    } finally { setBusy(false); }
  }

  const zone = draft ? zones.find(z => z.id === draft.zone_draft_id) : undefined;

  return (
    <div className="stack">
      <form className="card stack" onSubmit={submit}>
        <div>
          <label htmlFor="rule">Describe the rule in your own words</label>
          <textarea id="rule" rows={3} value={text} onChange={e => setText(e.target.value)} placeholder="Keep kids away from the kitchen gate during nap time." required />
        </div>
        <div className="row">
          <button className="btn" disabled={busy || !text.trim() || !room}>{busy ? 'Thinking…' : 'Make a rule'}</button>
          {SR && <button type="button" className="btn secondary" onClick={toggleMic} aria-pressed={listening}>{listening ? 'Stop listening' : 'Speak'}</button>}
        </div>
        {error && <div className="banner" role="alert">{error}</div>}
      </form>

      {draft && draft.needs_drawing && (
        <div className="card"><h3>I need a drawing</h3><p>{draft.question ?? 'That place is not marked on the floor plan yet.'} Draw it in Setup, then try again.</p></div>
      )}

      {draft && !draft.needs_drawing && (
        <div className="card stack">
          <h3>Here is the draft</h3>
          <p><strong>{draft.area_name}</strong> — <span className={`pill ${draft.severity}`}>{draft.severity}</span> — {draft.escalation.replace(/_/g, ' ')}</p>
          {room && zone && <FloorPlan room={room} zones={[zone]} />}
          <p className="small muted">This rule does nothing until you confirm it.</p>
          {confirmed ? <span className="pill ok">Rule is on</span> : (
            <button className="btn" disabled={!zone} onClick={async () => { try { await confirm({ zoneId: draft.zone_draft_id }); setConfirmed(true); } catch { setError('Could not confirm the rule.'); } }}>Confirm rule</button>
          )}
        </div>
      )}
    </div>
  );
}
