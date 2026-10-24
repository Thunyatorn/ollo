import { useEffect, useState } from 'react';
import { tables } from './module_bindings';
import { useTable } from 'spacetimedb/react';

export type Severity = 'high' | 'medium' | 'low';

/** Spacetime timestamp -> epoch milliseconds. */
export function tsMs(ts: { microsSinceUnixEpoch: bigint }): number {
  return Number(ts.microsSinceUnixEpoch / 1000n);
}

/** Re-renders on an interval so countdowns tick. */
export function useNow(intervalMs = 250): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}

/** The caregiver this browser is signed in as, if any. */
export function useMe() {
  const [rows, ready] = useTable(tables.myCaregiver);
  return { me: rows[0], ready };
}

export const OPEN_STATES = ['open', 'notified', 'escalated', 'unanswered', 'owned'];

export function statusLabel(status: string): string {
  switch (status) {
    case 'notified': return 'Needs attention';
    case 'escalated': return 'Calling backup';
    case 'unanswered': return 'Unanswered';
    case 'owned': return 'Being handled';
    case 'closed': return 'Closed';
    case 'reported': return 'Reported';
    default: return status;
  }
}

export function eventLabel(eventType: string): string {
  const labels: Record<string, string> = {
    zone_entry_predicted: 'About to enter a restricted area',
    zone_entry: 'Entered a restricted area',
    fall: 'Possible fall',
    climbing: 'Climbing',
    stillness: 'Not moving for a while',
    unsupervised: 'No adult nearby',
    possible_distress: 'Possible distress: both hands at the throat',
    rhythmic_movement: 'Repeated shaking movement',
    child_not_visible: 'Child out of sight',
    head_count_mismatch: 'Head count mismatch',
  };
  return labels[eventType] ?? eventType;
}

export function formatClock(ms: number): string {
  return new Date(ms).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

export function saveToken(token: string) {
  try { localStorage.setItem('nestwatch.token', token); } catch { /* storage can be blocked */ }
}
export function loadToken(): string | undefined {
  try { return localStorage.getItem('nestwatch.token') ?? undefined; } catch { return undefined; }
}
export function clearToken() {
  try { localStorage.removeItem('nestwatch.token'); } catch { /* ignore */ }
}

/** Number of alerts nobody has taken yet; also shown in the browser tab title so a background tab is noticed. */
export function useUnhandledCount(): number {
  const [alerts] = useTable(tables.alert);
  const n = alerts.filter(a => ['notified', 'escalated', 'unanswered'].includes(a.status)).length;
  useEffect(() => {
    document.title = n > 0 ? `(${n}) NestWatch — needs attention` : 'NestWatch';
    return () => { document.title = 'NestWatch'; };
  }, [n]);
  return n;
}

/** A readable title for a report: what happened, where and when (a daily summary shows its date). */
export function useReportTitle() {
  const [alerts] = useTable(tables.alert);
  const [zones] = useTable(tables.zone);
  return (r: { kind: string; alertId?: string | null; summary: string }): string => {
    if (r.kind === 'daily') return r.summary.match(/^Daily summary (\d{4}-\d{2}-\d{2})/)?.[0] ?? 'Daily summary';
    const a = alerts.find(x => x.id === r.alertId);
    if (!a) return `Incident ${r.alertId ?? ''}`.trim();
    const when = new Date(tsMs(a.createdAt)).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
    const where = zones.find(z => z.id === a.zoneId)?.name;
    return `${eventLabel(a.eventType)}${where ? ` at ${where}` : ''}, ${when}`;
  };
}
