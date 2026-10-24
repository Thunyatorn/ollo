// Pretends to be the vision service so the backend and screens can be tested without a camera.
//   pnpm --filter @nestwatch/tools fake-vision
// Keys while running:  e = send a "child about to enter zone" event now
//                      u = send a medium "unsupervised" event
//                      b = tap the buzzer for the newest open alert (acknowledges as BUZZER_CAREGIVER)
import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import { DbConnection } from '../web/src/module_bindings/index.ts';

const URI = process.env.STDB_URI ?? 'ws://127.0.0.1:3000';
const DB = process.env.STDB_DB ?? 'nestwatch-test';
const ROOM = process.env.ROOM_ID ?? 'main';
const BUZZER_CAREGIVER = process.env.BUZZER_CAREGIVER ?? 'c_maria';
const TOKEN_FILE = new URL('./.vision-token', import.meta.url).pathname;
const HZ = 8;

type Kid = { id: string; label: string; x: number; y: number; vx: number; vy: number };
const rand = (a: number, b: number) => a + Math.random() * (b - a);
const token = existsSync(TOKEN_FILE) ? readFileSync(TOKEN_FILE, 'utf8').trim() : undefined;

const conn = DbConnection.builder()
  .withUri(URI)
  .withDatabaseName(DB)
  .withToken(token)
  .onConnect((c, identity, tok) => {
    writeFileSync(TOKEN_FILE, tok);
    console.log(`connected as ${identity.toHexString()}`);
    c.subscriptionBuilder()
      .onApplied(() => start(identity.toHexString()))
      .subscribe(['SELECT * FROM room', 'SELECT * FROM zone', 'SELECT * FROM alert', 'SELECT * FROM caregiver']);
  })
  .onConnectError((_c, err) => { console.error('connect error', err.message); process.exit(1); })
  .build();

function start(identityHex: string) {
  const room = [...conn.db.room.iter()].find(r => r.id === ROOM);
  if (!room) { console.error(`No room "${ROOM}". Run scripts/seed-local.sh first.`); process.exit(1); }
  const W = room.widthM, H = room.heightM;
  const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

  const kids: Kid[] = ['1', '2', '3', '4'].map((label, i) => ({
    id: `t${label}`, label, x: rand(0.4, W - 0.4), y: rand(0.4, H - 0.4), vx: rand(-0.25, 0.25), vy: rand(-0.25, 0.25),
  }));
  const adult: Kid = { id: 't9', label: 'M', x: W * 0.7, y: H * 0.3, vx: 0, vy: 0 };

  const dangerZones = () => [...conn.db.zone.iter()].filter(z => z.roomId === ROOM && z.status === 'active' && z.severity === 'high');
  const centroid = (poly: { x: number; y: number }[]) => ({ x: poly.reduce((s, p) => s + p.x, 0) / poly.length, y: poly.reduce((s, p) => s + p.y, 0) / poly.length });
  const inside = (p: { x: number; y: number }, poly: { x: number; y: number }[]) => {
    let c = false;
    for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
      if ((poly[i].y > p.y) !== (poly[j].y > p.y) && p.x < ((poly[j].x - poly[i].x) * (p.y - poly[i].y)) / (poly[j].y - poly[i].y) + poly[i].x) c = !c;
    }
    return c;
  };

  const hero = kids[3]; // child 4 is the one who heads for danger
  let heroMode: 'wander' | 'approach' | 'retreat' = 'wander';
  let heroZoneId = '';
  let safeSince = 0;
  const reported = new Map<string, number>(); // `${track}:${zone}` -> last report ms (cooldown)

  const report = (track: string, type: string, zoneId: string, severity: string, eta: number | undefined) => {
    const key = `${track}:${zoneId}`;
    if (Date.now() - (reported.get(key) ?? 0) < 60_000) return;
    reported.set(key, Date.now());
    console.log(`event: ${type} ${track} ${zoneId} (${severity})`);
    conn.reducers.reportEvent({ trackId: track, eventType: type, zoneId, severity, predictedEntryS: eta, clipRef: `evt_${Date.now()}_${track}` }).catch(errHandler);
  };
  const errHandler = (e: unknown) => {
    const m = e instanceof Error ? e.message : String(e);
    console.error('reducer failed:', m);
    if (/requires role/.test(m)) console.error(`\nGrant this identity the vision role:\n  spacetime call ${DB} grant_role '"0x${identityHex}"' '"vision"' '{"none":[]}' --server local\n`);
  };

  // hero walks toward a danger zone 12 s after start, then repeats whenever it is safe again
  setTimeout(() => { heroMode = 'approach'; }, 12_000);

  setInterval(() => {
    const dt = 1 / HZ;
    const zones = dangerZones();

    for (const k of kids) {
      if (k === hero && heroMode !== 'wander' && zones.length) {
        const z = zones.find(z => z.id === heroZoneId) ?? zones[0];
        heroZoneId = z.id;
        const c = centroid(z.polygon);
        const dir = heroMode === 'approach' ? 1 : -1;
        const dx = c.x - k.x, dy = c.y - k.y, d = Math.hypot(dx, dy) || 1;
        k.vx = (dir * dx) / d * 0.45; k.vy = (dir * dy) / d * 0.45;
      } else if (Math.random() < 0.04) {
        k.vx = rand(-0.3, 0.3); k.vy = rand(-0.3, 0.3);
      }
      // everyone except the hero keeps out of danger zones, so only the scripted child triggers alerts:
      // if the current heading would lead into a zone within 4 s, pick another heading
      if (k !== hero) {
        const bad = (vx: number, vy: number) => zones.some(z => [1, 2, 3, 4].some(t => inside({ x: k.x + vx * t, y: k.y + vy * t }, z.polygon)));
        if (bad(k.vx, k.vy)) {
          for (let i = 0; i < 30 && bad(k.vx, k.vy); i++) { k.vx = rand(-0.3, 0.3); k.vy = rand(-0.3, 0.3); }
        }
      }
      k.x = clamp(k.x + k.vx * dt, 0.15, W - 0.15); k.y = clamp(k.y + k.vy * dt, 0.15, H - 0.15);
      if (k.x <= 0.15 || k.x >= W - 0.15) k.vx *= -1;
      if (k.y <= 0.15 || k.y >= H - 0.15) k.vy *= -1;

      // predicted entry: where will it be in 3 s?
      for (const z of zones) {
        const now = inside(k, z.polygon);
        const soon = !now && inside({ x: k.x + k.vx * 3, y: k.y + k.vy * 3 }, z.polygon);
        if (now) report(k.id, 'zone_entry', z.id, 'high', undefined);
        else if (soon) {
          const c = centroid(z.polygon);
          report(k.id, 'zone_entry_predicted', z.id, 'high', Math.max(0.5, Math.min(3, Math.hypot(c.x - k.x, c.y - k.y) / (Math.hypot(k.vx, k.vy) || 1))));
        }
      }
    }

    // once the hero's alert is owned, it retreats; ~5 s later the alert is closed as resolved
    const heroAlert = [...conn.db.alert.iter()].find(a => a.trackId === hero.id && a.status === 'owned');
    if (heroAlert && heroMode === 'approach') { heroMode = 'retreat'; safeSince = 0; }
    if (heroMode === 'retreat') {
      const z = zones.find(z => z.id === heroZoneId);
      const away = !z || !inside(hero, z.polygon);
      if (away && !safeSince) safeSince = Date.now();
      if (safeSince && Date.now() - safeSince > 5000) {
        if (heroAlert) conn.reducers.closeAlert({ alertId: heroAlert.id, reason: 'child moved back to the play area' }).catch(errHandler);
        heroMode = 'wander'; safeSince = 0;
        setTimeout(() => { heroMode = 'approach'; }, 25_000);
      }
    }

    const all = [...kids, adult];
    conn.reducers.updatePositions({
      roomId: ROOM,
      positions: all.map(k => ({ trackId: k.id, kind: k === adult ? 'adult' : 'child', label: k.label, x: +k.x.toFixed(3), y: +k.y.toFixed(3), vx: +k.vx.toFixed(3), vy: +k.vy.toFixed(3), visible: true })),
    }).catch(errHandler);
  }, 1000 / HZ);

  setInterval(() => conn.reducers.cameraHealth({ cameraId: 'cam1', status: 'online' }).catch(() => {}), 10_000);

  process.stdin.setEncoding('utf8');
  process.stdin.on('data', (s: string) => {
    const key = s.trim();
    const zones = dangerZones();
    if (key === 'e' && zones[0]) { reported.clear(); report(hero.id, 'zone_entry_predicted', zones[0].id, 'high', 2.8); }
    if (key === 'u') { const z = zones[0]?.id ?? ''; conn.reducers.reportEvent({ trackId: kids[1].id, eventType: 'unsupervised', zoneId: z, severity: 'medium', predictedEntryS: undefined, clipRef: `evt_${Date.now()}_u` }).catch(errHandler); }
    if (key === 'b') {
      const open = [...conn.db.alert.iter()].filter(a => !a.ownerId && ['notified', 'escalated', 'unanswered'].includes(a.status)).pop();
      if (open) conn.reducers.acknowledgeAlert({ alertId: open.id, caregiverId: BUZZER_CAREGIVER, via: 'buzzer' }).catch(errHandler);
      else console.log('no unhandled alert');
    }
  });
  console.log(`fake vision running at ${HZ} Hz in room "${ROOM}". Keys: e=event  u=unsupervised  b=buzzer tap`);
}
