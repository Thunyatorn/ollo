import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useReducer, useTable } from 'spacetimedb/react';
import { Check, CheckCheck, ChevronDown, Circle, Film, Hand, Phone, ScanLine, Sparkles, X } from 'lucide-react';
import { reducers, tables } from '../module_bindings';
import type { Alert, Caregiver } from '../module_bindings/types';
import { useAlertActions } from './AlertCard';
import { eventLabel, formatClock, statusLabel, tsMs, useNow } from '../lib';
import { VISION_URL } from '../config';
import { useServices } from '../services';

const RANK: Record<string, number> = { high: 0, medium: 1, low: 2 };
const WAITING = ['notified', 'escalated', 'unanswered'];
const SHOWN = 8;

// The reference build's "Event trace" panel (commit 17cca7a, src/EventTrace.tsx), fed by our alerts in Spacetime.
export default function EventTrace({ me }: { me: Caregiver }) {
  const [alerts] = useTable(tables.alert);
  const [zones] = useTable(tables.zone);
  const [positions] = useTable(tables.trackPosition);
  const [caregivers] = useTable(tables.caregiver);
  const [reports] = useTable(tables.report);
  const { worker } = useServices();
  const closeAlert = useReducer(reducers.closeAlert);
  const [selected, setSelected] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);
  const [busyAll, setBusyAll] = useState(false);

  // open alerts first (most urgent, then oldest), then today's closed ones so the trace keeps a history
  const items = useMemo(() => {
    const start = new Date(); start.setHours(0, 0, 0, 0);
    const open = alerts.filter(a => WAITING.includes(a.status) || a.status === 'owned')
      .sort((a, b) => Number(b.status !== 'owned') - Number(a.status !== 'owned') || RANK[a.severity] - RANK[b.severity] || tsMs(a.createdAt) - tsMs(b.createdAt));
    const done = alerts.filter(a => (a.status === 'closed' || a.status === 'reported') && tsMs(a.createdAt) >= start.getTime())
      .sort((a, b) => tsMs(b.createdAt) - tsMs(a.createdAt)).slice(0, 10);
    return { open, done };
  }, [alerts]);
  const handled = items.open.filter(a => a.status === 'owned');
  const list = [...items.open, ...items.done];
  const listed = showAll ? list : list.slice(0, SHOWN);
  const live = worker?.calls === 'twilio' || worker?.calls?.startsWith('cartesia');

  async function resolveHandled() {
    setBusyAll(true);
    try { for (const a of handled) await closeAlert({ alertId: a.id, reason: 'resolved by caregiver' }); }
    finally { setBusyAll(false); }
  }

  return (
    <aside className="event-trace" aria-label="Event trace">
      <header>
        <div><ScanLine size={15} /><h2>Event trace</h2></div>
        <span>{items.open.length.toString().padStart(2, '0')}</span>
      </header>
      {(handled.length > 1 || list.length > SHOWN) && (
        <div className="trace-tools">
          {handled.length > 1 && (
            <button className="button" onClick={resolveHandled} disabled={busyAll}><CheckCheck size={13} />{busyAll ? 'Resolving…' : `Resolve ${handled.length} being handled`}</button>
          )}
          {list.length > SHOWN && (
            <button className="text-button" onClick={() => setShowAll(v => !v)}>{showAll ? 'Show fewer' : `Show all ${list.length}`}</button>
          )}
        </div>
      )}
      <div className="trace-scroll">
        {list.length === 0 ? (
          <div className="trace-empty">
            <span className="quiet-orbit"><Check size={18} /></span>
            <p>Things are chilling</p>
            <span>Alerts will appear here.</span>
          </div>
        ) : listed.map(a => {
          const expanded = selected === a.id || (selected === null && WAITING.includes(a.status));
          return (
            <TraceEvent key={a.id} alert={a} me={me} caregivers={caregivers} expanded={expanded} live={!!live}
              onToggle={() => setSelected(expanded ? 'collapsed' : a.id)}
              zoneName={zones.find(z => z.id === a.zoneId)?.name}
              childLabel={positions.find(p => p.trackId === a.trackId)?.label}
              reportId={reports.find(r => r.alertId === a.id)?.id} />
          );
        })}
      </div>
      <footer>
        <span className="status-dot" />
        Today
        <span>{worker === null ? 'Worker offline' : live ? 'Real calls' : 'Calls simulated'}</span>
      </footer>
    </aside>
  );
}

function TraceEvent({ alert: a, me, caregivers, expanded, live, onToggle, zoneName, childLabel, reportId }: {
  alert: Alert; me: Caregiver; caregivers: readonly Caregiver[]; expanded: boolean; live: boolean; onToggle: () => void;
  zoneName?: string; childLabel?: string; reportId?: string;
}) {
  const now = useNow(500);
  const actions = useAlertActions(a, me, 'dashboard');
  const waiting = WAITING.includes(a.status);
  const owned = a.status === 'owned';
  const owner = caregivers.find(c => c.id === a.ownerId);
  const secs = a.nextEscalationAt ? Math.max(0, Math.ceil((tsMs(a.nextEscalationAt) - now) / 1000)) : null;
  const level = a.escalationLevel;
  const steps = [
    { name: 'Buzzer and screens', done: true, now: level === 0 },
    { name: 'Backup caregiver called', done: level >= 1, now: level === 1 },
    { name: 'All staff and local alarm', done: level >= 2, now: level === 2 },
  ];
  const title = `${eventLabel(a.eventType)}${zoneName ? ` · ${zoneName}` : ''}`;
  const traceStatus = waiting ? 'open' : owned ? 'acknowledged' : 'resolved';

  return (
    <article className={`trace-event ${a.severity === 'high' ? 'critical' : ''} ${expanded ? 'expanded' : ''}`}>
      <button className="trace-summary" onClick={onToggle} aria-expanded={expanded}>
        <span className="trace-node"><Circle size={7} fill="currentColor" /></span>
        <div>
          <span className="trace-meta">
            <time>{formatClock(tsMs(a.createdAt))}</time>
            <span>{a.severity.toUpperCase()}</span>
          </span>
          <h3>{title}</h3>
          <span className={`trace-status ${traceStatus}`}>{waiting ? statusLabel(a.status) : owned ? 'Being handled' : 'Closed'}</span>
          {a.ownerId && <span className="trace-owner">Handled by {a.ownerId === me.id ? 'you' : owner?.name ?? 'someone'}{a.ackedVia ? ` via ${a.ackedVia.replace('_', ' ')}` : ''}</span>}
        </div>
        <ChevronDown size={13} />
      </button>
      {expanded && (
        <div className="trace-detail">
          <p>
            {childLabel ? `Child ${childLabel}` : 'A child'}{zoneName ? ` at ${zoneName}` : ''}.
            {a.predictedEntryS != null && waiting && ` About ${a.predictedEntryS.toFixed(0)} s from entering.`}
          </p>
          <p className="trace-limitation">Possible concern only: a camera rule, not a diagnosis. Check the child.</p>
          {a.urgencyNote && (
            <div className="trace-opinion">
              <div><Sparkles size={13} /><strong>Claude second opinion</strong></div>
              <span>Urgency lowered to {a.severity}</span>
              <p>{a.urgencyNote.replace(/^Second opinion \(Claude\): /, '')}</p>
              <small>Context only. A caregiver still decides. Faces blurred.</small>
            </div>
          )}
          {(waiting || level > 0) && (
            <div className="trace-call">
              <div><Phone size={13} /><strong>Caregiver escalation</strong></div>
              <span>{live ? 'Live calling enabled' : 'Simulation · no real call placed'}</span>
              {steps.map(s => (
                <div className={`trace-call-step ${waiting && s.now ? 'now' : ''}`} key={s.name}>
                  <span>{s.name}</span>
                  <span>{s.done ? 'Done' : waiting && s.now && secs != null ? `In ${secs}s` : waiting ? 'Waiting' : '—'}</span>
                </div>
              ))}
            </div>
          )}
          {a.clipRef && (
            <figure className="trace-clip">
              <video src={`${VISION_URL}/clips/${a.clipRef}`} controls muted playsInline preload="none" />
              <figcaption><Film size={10} /> Evidence clip · 5 s before to 5 s after · faces blurred · daycare network only</figcaption>
            </figure>
          )}
          <div className="trace-actions">
            {waiting && <button className="button amber-button" onClick={actions.takeIt} disabled={actions.busy}><Check size={13} />I'm on it</button>}
            {(a.status === 'notified' || a.status === 'escalated') && (
              <button className="button" onClick={actions.cannotRespond} disabled={actions.busy} title="Skip the wait: the next person is told now"><Hand size={13} />I can't respond</button>
            )}
            {owned && <button className="button" onClick={() => actions.resolve('resolved by caregiver')} disabled={actions.busy}><CheckCheck size={13} />Resolve</button>}
            {(waiting || owned) && (
              <button className="icon-button" aria-label="False alarm" title="False alarm" onClick={actions.falseAlarm} disabled={actions.busy}><X size={14} /></button>
            )}
            {reportId && <Link className="text-button" to={`/reports/${reportId}`}>Report</Link>}
          </div>
          {actions.error && <p className="trace-limitation" role="alert">{actions.error}</p>}
        </div>
      )}
    </article>
  );
}
