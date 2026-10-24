import { useState } from 'react';
import { useReducer } from 'spacetimedb/react';
import { reducers } from '../module_bindings';
import type { Alert, Caregiver } from '../module_bindings/types';
import { eventLabel, statusLabel, tsMs, useNow } from '../lib';

interface Props {
  alert: Alert;
  me: Caregiver;
  caregivers: readonly Caregiver[];
  via: 'dashboard' | 'phone_app';
  zoneName?: string;
  childLabel?: string;
  /** phone layout: big full-width treatment */
  takeover?: boolean;
}

export function useAlertActions(alert: Alert, me: Caregiver, via: 'dashboard' | 'phone_app') {
  const ack = useReducer(reducers.acknowledgeAlert);
  const close = useReducer(reducers.closeAlert);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function run(fn: () => Promise<void>) {
    setBusy(true);
    setError('');
    try { await fn(); } catch (e) { setError(e instanceof Error ? e.message : 'That did not work. Try again.'); }
    finally { setBusy(false); }
  }
  return {
    error, busy,
    takeIt: () => run(() => ack({ alertId: alert.id, caregiverId: me.id, via })),
    resolve: (reason: string) => run(() => close({ alertId: alert.id, reason })),
    falseAlarm: () => run(async () => {
      if (!alert.ownerId) await ack({ alertId: alert.id, caregiverId: me.id, via });
      await close({ alertId: alert.id, reason: 'false alarm' });
    }),
  };
}

export default function AlertCard({ alert, me, caregivers, via, zoneName, childLabel, takeover }: Props) {
  const now = useNow();
  const actions = useAlertActions(alert, me, via);
  const owner = caregivers.find(c => c.id === alert.ownerId);
  const isOwned = alert.status === 'owned';
  const iOwnIt = alert.ownerId === me.id;

  const secs = alert.nextEscalationAt ? Math.max(0, Math.ceil((tsMs(alert.nextEscalationAt) - now) / 1000)) : null;
  const where = zoneName ? ` — ${zoneName}` : '';
  const who = childLabel ? `Child ${childLabel}` : 'A child';
  const level = alert.escalationLevel;
  const nextStep = level === 0 ? 'Backup caregiver gets a call' : level === 1 ? 'Alarm sounds and all staff are notified' : null;

  const steps = [
    { name: 'Buzzer + screens', done: true, now: level === 0 && !isOwned },
    { name: 'Backup called', done: level >= 1, now: level === 1 && !isOwned },
    { name: 'All staff + alarm', done: level >= 2, now: level === 2 && !isOwned },
  ];

  if (takeover) {
    return (
      <div className="stack">
        <div className={`takeover ${isOwned ? 'owned' : alert.severity === 'medium' ? 'medium' : alert.severity === 'low' ? 'low' : ''} ${!isOwned ? 'pulse' : ''}`} role="alert">
          <div className="small" style={{ opacity: .9 }}>{isOwned ? 'Handled' : statusLabel(alert.status).toUpperCase()}</div>
          <h1>{who}{where}</h1>
          <p style={{ margin: '0 0 .5rem' }}>
            {eventLabel(alert.eventType)}
            {alert.predictedEntryS != null && !isOwned && ` — about ${alert.predictedEntryS.toFixed(0)} s away`}
          </p>
          {isOwned ? (
            <h2>{iOwnIt ? 'You are handling it' : `${owner?.name ?? 'Someone'} is handling it`}</h2>
          ) : (
            secs != null && (
              <div>
                <div className="count" aria-live="off">{secs}s</div>
                <div className="small">until: {nextStep}</div>
              </div>
            )
          )}
        </div>
        {!isOwned && <button className="btn big" onClick={actions.takeIt} disabled={actions.busy}>I'm on it</button>}
        {isOwned && <button className="btn big secondary" onClick={() => actions.resolve('resolved by caregiver')} disabled={actions.busy}>{iOwnIt ? 'All clear — close alert' : 'Mark resolved'}</button>}
        {!isOwned && <button className="btn secondary" onClick={actions.falseAlarm} disabled={actions.busy}>False alarm</button>}
        {actions.error && <div className="banner" role="alert">{actions.error}</div>}
      </div>
    );
  }

  return (
    <table className={`alert-table ${isOwned ? 'owned' : alert.severity}`}>
      <caption>
        <strong>Alert {alert.id}</strong> <span className={`pill ${alert.severity}`}>{alert.severity}</span> {statusLabel(alert.status)}
      </caption>
      <tbody>
        <tr><th scope="row">Child</th><td>{childLabel ?? '?'}</td></tr>
        <tr><th scope="row">Where</th><td>{zoneName ?? 'not in a zone'}</td></tr>
        <tr><th scope="row">What</th><td>{eventLabel(alert.eventType)}{alert.predictedEntryS != null && !isOwned && ` (about ${alert.predictedEntryS.toFixed(0)} s)`}</td></tr>
        {alert.urgencyNote && <tr><th scope="row">Second opinion</th><td>{alert.urgencyNote}</td></tr>}
        {isOwned ? (
          <tr><th scope="row">Handled by</th><td><strong>{iOwnIt ? 'You' : owner?.name ?? 'Someone'}</strong>{alert.ackedVia ? ` (via ${alert.ackedVia.replace('_', ' ')})` : ''}</td></tr>
        ) : (
          <>
            <tr>
              <th scope="row">Escalation</th>
              <td className="steps">
                {steps.map(s => <span key={s.name} className={s.now ? 'now' : ''}>[{s.done ? 'x' : '\u00a0'}] {s.name}</span>)}
              </td>
            </tr>
            {secs != null && nextStep && <tr><th scope="row">Next</th><td><strong className="mono">{secs} s</strong> until: {nextStep}</td></tr>}
          </>
        )}
        <tr>
          <td colSpan={2}>
            <div className="actions">
              {!isOwned && <button className="btn" onClick={actions.takeIt} disabled={actions.busy}>I'm on it</button>}
              {isOwned && <button className="btn secondary" onClick={() => actions.resolve('resolved by caregiver')} disabled={actions.busy}>{iOwnIt ? 'Close alert' : 'Mark resolved'}</button>}
              {!isOwned && <button className="btn secondary" onClick={actions.falseAlarm} disabled={actions.busy}>False alarm</button>}
            </div>
            {actions.error && <div className="banner" role="alert">{actions.error}</div>}
          </td>
        </tr>
      </tbody>
    </table>
  );
}
