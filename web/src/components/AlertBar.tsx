import { Link } from 'react-router-dom';
import { useTable } from 'spacetimedb/react';
import { tables } from '../module_bindings';
import type { Alert, Caregiver } from '../module_bindings/types';
import { useAlertActions } from './AlertCard';
import { eventLabel, tsMs, useMe, useNow } from '../lib';

const WAITING = ['notified', 'escalated', 'unanswered'];
const RANK: Record<string, number> = { high: 0, medium: 1, low: 2 };

// A strip across the top of every page for the most urgent alert nobody has taken yet, so it is seen from any page,
// with the countdown and the buttons right there.
export default function AlertBar() {
  const { me } = useMe();
  const [alerts] = useTable(tables.alert);
  const [zones] = useTable(tables.zone);
  const [positions] = useTable(tables.trackPosition);
  const waiting = alerts.filter(a => WAITING.includes(a.status))
    .sort((a, b) => RANK[a.severity] - RANK[b.severity] || tsMs(a.createdAt) - tsMs(b.createdAt));
  if (!me || waiting.length === 0) return null;
  const a = waiting[0];
  return <Bar alert={a} me={me} more={waiting.length - 1}
              zoneName={zones.find(z => z.id === a.zoneId)?.name}
              childLabel={positions.find(p => p.trackId === a.trackId)?.label} />;
}

function Bar({ alert, me, more, zoneName, childLabel }: { alert: Alert; me: Caregiver; more: number; zoneName?: string; childLabel?: string }) {
  const now = useNow(500);
  const actions = useAlertActions(alert, me, 'dashboard');
  const secs = alert.nextEscalationAt ? Math.max(0, Math.ceil((tsMs(alert.nextEscalationAt) - now) / 1000)) : null;
  const next = alert.escalationLevel === 0 ? 'the backup caregiver is called' : alert.escalationLevel === 1 ? 'the alarm sounds and all staff are told' : null;
  return (
    <div className={`alertbar ${alert.severity}`} role="alert">
      <div className="alertbar-text">
        <strong>{alert.severity.toUpperCase()}:</strong> {childLabel ? `Child ${childLabel}` : 'A child'}
        {zoneName ? ` at ${zoneName}` : ''} — {eventLabel(alert.eventType)}.
        {secs != null && next && <> In <strong className="mono">{secs} s</strong> {next}.</>}
        {more > 0 && <> <Link to="/">+{more} more</Link></>}
        {actions.error && <> <em>{actions.error}</em></>}
      </div>
      <div className="alertbar-buttons">
        <button className="btn" onClick={actions.takeIt} disabled={actions.busy}>I'm on it</button>
        <button className="btn secondary" onClick={actions.falseAlarm} disabled={actions.busy}>False alarm</button>
      </div>
    </div>
  );
}
