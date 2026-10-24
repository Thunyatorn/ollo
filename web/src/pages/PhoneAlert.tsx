import { useEffect, useMemo } from 'react';
import { useTable } from 'spacetimedb/react';
import { tables } from '../module_bindings';
import AlertCard from '../components/AlertCard';
import { OPEN_STATES, tsMs, useMe, eventLabel } from '../lib';
import { VISION_URL } from '../config';

const RANK: Record<string, number> = { high: 0, medium: 1, low: 2 };

export default function PhoneAlert() {
  const { me } = useMe();
  const [alerts] = useTable(tables.alert);
  const [caregivers] = useTable(tables.caregiver);
  const [zones] = useTable(tables.zone);
  const [positions] = useTable(tables.trackPosition);

  const open = useMemo(
    () => alerts.filter(a => OPEN_STATES.includes(a.status))
      // unhandled first, then by severity, then oldest
      .sort((a, b) => Number(a.status === 'owned') - Number(b.status === 'owned') || RANK[a.severity] - RANK[b.severity] || tsMs(a.createdAt) - tsMs(b.createdAt)),
    [alerts]
  );
  const top = open[0];
  const needsAttention = !!top && top.status !== 'owned';

  // Android can vibrate from a page; iPhone cannot, which is why the wrist buzzer exists.
  useEffect(() => {
    if (!needsAttention || !('vibrate' in navigator)) return;
    const id = setInterval(() => navigator.vibrate(top.severity === 'high' ? [400, 150, 400] : [150, 150]), 1500);
    return () => { clearInterval(id); navigator.vibrate(0); };
  }, [needsAttention, top?.id, top?.severity]);

  if (!me) return null;
  const labelOf = (trackId: string) => positions.find(p => p.trackId === trackId)?.label;
  const zoneName = (id: string) => zones.find(z => z.id === id)?.name;

  if (!top) {
    const kids = positions.filter(p => p.kind === 'child' && p.visible).length;
    return (
      <div className="card stack">
        <h1>All clear</h1>
        <p className="muted">{kids} {kids === 1 ? 'child' : 'children'} in view. You will be alerted here.</p>
        <p className="small muted">{me.buzzerId ? `Wrist buzzer: ${me.buzzerId}` : 'No wrist buzzer paired.'}</p>
      </div>
    );
  }

  return (
    <div className="stack">
      <AlertCard takeover alert={top} me={me} caregivers={caregivers} via="phone_app" zoneName={zoneName(top.zoneId)} childLabel={labelOf(top.trackId)} />
      <p className="small muted">{me.buzzerId ? `Wrist buzzer ${me.buzzerId}: ${needsAttention ? 'buzzing' : 'quiet'}` : 'No wrist buzzer paired.'}</p>
      {top.clipRef && <p className="small"><a href={`${VISION_URL}/clips/${top.clipRef}`} target="_blank" rel="noreferrer">View blurred clip</a> <span className="muted">(daycare Wi-Fi only)</span></p>}
      {open.length > 1 && (
        <div className="card">
          <h3>{open.length - 1} more</h3>
          {open.slice(1).map(a => (
            <div key={a.id} className="row small"><span className={`pill ${a.severity}`}>{a.severity}</span><span className="grow">Child {labelOf(a.trackId) ?? '?'} — {zoneName(a.zoneId) ?? eventLabel(a.eventType)}</span><span className="muted">{a.status === 'owned' ? 'handled' : 'open'}</span></div>
          ))}
        </div>
      )}
    </div>
  );
}
