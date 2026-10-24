// NestWatch Spacetime module. Spec: CLUADE.md ("Spacetime backend").
// Rule 1: this module is the only place alert state changes.
import { schema, table, t, SenderError } from 'spacetimedb/server';
import type { InferSchema, ReducerCtx } from 'spacetimedb/server';
import { ScheduleAt, Timestamp } from 'spacetimedb';

// ---------- shared value types ----------

const Point = t.object('Point', { x: t.f64(), y: t.f64() });
const Polygon = t.object('Polygon', { points: t.array(Point) });
const Schedule = t.object('Schedule', {
  named: t.option(t.string()), // e.g. "nap_time"
  startMin: t.option(t.u16()), // minutes after midnight
  endMin: t.option(t.u16()),
});
const ReportLine = t.object('ReportLine', { eventId: t.string(), text: t.string() });
const PositionInput = t.object('PositionInput', {
  trackId: t.string(),
  kind: t.string(), // 'child' | 'adult'
  label: t.string(),
  x: t.f64(),
  y: t.f64(),
  vx: t.f64(),
  vy: t.f64(),
  visible: t.bool(),
});

// ---------- tables ----------

// Who may call what. Private: clients never read it.
const principal = table(
  { name: 'principal' },
  {
    identity: t.identity().primaryKey(),
    role: t.string(), // 'admin' | 'vision' | 'worker' | 'caregiver'
    caregiverId: t.option(t.string()), // set when role = 'caregiver'
  }
);

const idCounter = table(
  { name: 'id_counter' },
  { prefix: t.string().primaryKey(), next: t.u64() }
);

const room = table(
  { name: 'room', public: true },
  {
    id: t.string().primaryKey(),
    name: t.string(),
    widthM: t.f64(),
    heightM: t.f64(),
    floorPlan: t.string(),
  }
);

const camera = table(
  { name: 'camera', public: true },
  {
    id: t.string().primaryKey(),
    roomId: t.string(),
    name: t.string(),
    homography: t.array(t.f64()), // 9 numbers, row-major
    blindSpots: t.array(Polygon),
    status: t.string(), // 'online' | 'offline' | 'low_fps'
    lastSeen: t.timestamp(),
  }
);

// Phone number lives in caregiver_contact (private), exposed only to the worker via a view.
const caregiver = table(
  { name: 'caregiver', public: true },
  {
    id: t.string().primaryKey(),
    name: t.string(),
    role: t.string(), // 'primary' | 'backup' | 'staff'
    buzzerId: t.option(t.string()),
    onDuty: t.bool(),
  }
);

const caregiverContact = table(
  { name: 'caregiver_contact' },
  { caregiverId: t.string().primaryKey(), phone: t.string(), joinCode: t.string() }
);

// Named areas (e.g. "Kitchen gate") that a plain-language rule can refer to.
const namedArea = table(
  { name: 'named_area', public: true },
  {
    id: t.string().primaryKey(),
    roomId: t.string().index('btree'),
    name: t.string(),
    polygon: t.array(Point),
  }
);

const zone = table(
  { name: 'zone', public: true },
  {
    id: t.string().primaryKey(),
    roomId: t.string().index('btree'),
    name: t.string(),
    polygon: t.array(Point), // meters
    severity: t.string(),
    schedule: Schedule,
    escalation: t.string(),
    status: t.string(), // 'draft' | 'active' | 'off'
    confirmedBy: t.option(t.string()),
  }
);

// One row per track, updated in place.
const trackPosition = table(
  { name: 'track_position', public: true },
  {
    trackId: t.string().primaryKey(),
    roomId: t.string().index('btree'),
    kind: t.string(),
    label: t.string(),
    x: t.f64(),
    y: t.f64(),
    vx: t.f64(),
    vy: t.f64(),
    visible: t.bool(),
    updatedAt: t.timestamp(),
  }
);

const alert = table(
  { name: 'alert', public: true },
  {
    id: t.string().primaryKey(),
    trackId: t.string().index('btree'),
    eventType: t.string(),
    zoneId: t.string(),
    severity: t.string(),
    status: t.string().index('btree'),
    createdAt: t.timestamp(),
    predictedEntryS: t.option(t.f64()),
    clipRef: t.string(),
    ownerId: t.option(t.string()),
    ackedAt: t.option(t.timestamp()),
    ackedVia: t.option(t.string()),
    escalationLevel: t.u8(),
    nextEscalationAt: t.option(t.timestamp()),
    closedAt: t.option(t.timestamp()),
    urgencyNote: t.option(t.string()),
  }
);

const incidentEvent = table(
  { name: 'incident_event', public: true },
  {
    id: t.string().primaryKey(),
    alertId: t.string().index('btree'),
    at: t.timestamp(),
    kind: t.string(),
    text: t.string(),
    clipRef: t.option(t.string()),
  }
);

const callJob = table(
  { name: 'call_job', public: true },
  {
    id: t.string().primaryKey(),
    alertId: t.string().index('btree'),
    caregiverId: t.string(),
    attempt: t.u8(),
    status: t.string(), // 'queued' | 'ringing' | 'answered' | 'failed' | 'cancelled'
  }
);

const report = table(
  { name: 'report', public: true },
  {
    id: t.string().primaryKey(),
    kind: t.string(), // 'incident' | 'daily'
    alertId: t.option(t.string()),
    summary: t.string(),
    lines: t.array(ReportLine),
    caregiverNote: t.option(t.string()),
    status: t.string(), // 'draft' | 'final'
  }
);

const recallMatch = table(
  { name: 'recall_match', public: true },
  {
    id: t.string().primaryKey(),
    product: t.string(),
    recallTitle: t.string(),
    recallUrl: t.string(),
    confidence: t.f64(),
    status: t.string(),
  }
);

const escalationTimer = table(
  { name: 'escalation_timer' },
  {
    scheduledId: t.u64().primaryKey().autoInc(),
    scheduledAt: t.scheduleAt(),
    alertId: t.string().index('btree'),
    level: t.u8(), // the escalation level this timer moves the alert FROM
  }
);

const spacetimedb = schema({
  principal,
  idCounter,
  room,
  camera,
  caregiver,
  caregiverContact,
  namedArea,
  zone,
  trackPosition,
  alert,
  incidentEvent,
  callJob,
  report,
  recallMatch,
  escalationTimer,
});
export default spacetimedb;

// ---------- helpers ----------

type Ctx = ReducerCtx<InferSchema<typeof spacetimedb>>;

const SEVERITY_RANK: Record<string, number> = { low: 0, medium: 1, high: 2 };
const TIMEOUTS_S: Record<string, [number, number] | null> = {
  high: [20, 30],
  medium: [45, 60],
  low: null,
};
const CLOSED_STATES = new Set(['closed', 'reported']);
const ACKABLE_STATES = new Set(['open', 'notified', 'escalated', 'unanswered']);

function roleOf(ctx: Ctx): { role: string; caregiverId: string | undefined } | null {
  const p = ctx.db.principal.identity.find(ctx.sender);
  return p ? { role: p.role, caregiverId: p.caregiverId ?? undefined } : null;
}

function requireRole(ctx: Ctx, ...roles: string[]) {
  const who = roleOf(ctx);
  if (!who || !roles.includes(who.role)) {
    throw new SenderError(`requires role: ${roles.join(' or ')}`);
  }
  return who;
}

function nextId(ctx: Ctx, prefix: string): string {
  const row = ctx.db.idCounter.prefix.find(prefix);
  const n = row ? row.next : 1n;
  if (row) ctx.db.idCounter.prefix.update({ prefix, next: n + 1n });
  else ctx.db.idCounter.insert({ prefix, next: n + 1n });
  return `${prefix}_${n}`;
}

function afterSeconds(ctx: Ctx, seconds: number): Timestamp {
  return new Timestamp(ctx.timestamp.microsSinceUnixEpoch + BigInt(seconds) * 1_000_000n);
}

function logEvent(ctx: Ctx, alertId: string, kind: string, text: string, clipRef?: string) {
  const id = nextId(ctx, 'e');
  ctx.db.incidentEvent.insert({ id, alertId, at: ctx.timestamp, kind, text, clipRef });
  return id;
}

function scheduleEscalation(ctx: Ctx, alertId: string, fromLevel: number, seconds: number) {
  const at = afterSeconds(ctx, seconds);
  ctx.db.escalationTimer.insert({
    scheduledId: 0n,
    scheduledAt: ScheduleAt.time(at.microsSinceUnixEpoch),
    alertId,
    level: fromLevel,
  });
  return at;
}

function cancelTimers(ctx: Ctx, alertId: string) {
  for (const timer of [...ctx.db.escalationTimer.alertId.filter(alertId)]) {
    ctx.db.escalationTimer.scheduledId.delete(timer.scheduledId);
  }
}

function cancelCalls(ctx: Ctx, alertId: string) {
  for (const job of [...ctx.db.callJob.alertId.filter(alertId)]) {
    if (job.status === 'queued' || job.status === 'ringing') {
      ctx.db.callJob.id.update({ ...job, status: 'cancelled' });
    }
  }
}

function queueBackupCall(ctx: Ctx, alertId: string, attempt: number) {
  const backup = [...ctx.db.caregiver.iter()].find(c => c.role === 'backup' && c.onDuty);
  if (!backup) {
    logEvent(ctx, alertId, 'call_skipped', 'No backup caregiver on duty to call');
    return;
  }
  const id = nextId(ctx, 'call');
  ctx.db.callJob.insert({ id, alertId, caregiverId: backup.id, attempt, status: 'queued' });
  logEvent(ctx, alertId, 'call_queued', `Call attempt ${attempt} queued for the backup caregiver`);
}

// Moves an alert up one escalation level. `fromLevel` guards against stale timers.
function runEscalation(ctx: Ctx, alertId: string, fromLevel: number) {
  const a = ctx.db.alert.id.find(alertId);
  if (!a) return;
  if (a.escalationLevel !== fromLevel) return;
  if (a.status !== 'notified' && a.status !== 'escalated') return;
  const timeouts = TIMEOUTS_S[a.severity];

  if (fromLevel === 0) {
    const nextAt = timeouts ? scheduleEscalation(ctx, alertId, 1, timeouts[1]) : undefined;
    ctx.db.alert.id.update({ ...a, status: 'escalated', escalationLevel: 1, nextEscalationAt: nextAt });
    logEvent(ctx, alertId, 'escalated', 'Nobody acknowledged in time; escalating to the backup caregiver');
    queueBackupCall(ctx, alertId, 1);
  } else if (fromLevel === 1) {
    ctx.db.alert.id.update({ ...a, status: 'unanswered', escalationLevel: 2, nextEscalationAt: undefined });
    logEvent(ctx, alertId, 'unanswered', 'Backup did not answer; local alarm and all-staff notification');
    queueBackupCall(ctx, alertId, 2);
  }
}

// ---------- lifecycle ----------

export const init = spacetimedb.init(ctx => {
  // The identity that publishes the module becomes the admin.
  ctx.db.principal.insert({ identity: ctx.sender, role: 'admin', caregiverId: undefined });
});

// ---------- views ----------

// Phone numbers are readable only by the worker.
export const workerContacts = spacetimedb.view(
  { name: 'worker_contacts', public: true },
  t.array(caregiverContact.rowType),
  ctx => {
    const p = ctx.db.principal.identity.find(ctx.sender);
    if (!p || p.role !== 'worker') return [];
    return [...ctx.db.caregiverContact.iter()];
  }
);

// The caregiver this connection is signed in as (zero or one row).
export const myCaregiver = spacetimedb.view(
  { name: 'my_caregiver', public: true },
  t.array(caregiver.rowType),
  ctx => {
    const p = ctx.db.principal.identity.find(ctx.sender);
    if (!p || !p.caregiverId) return [];
    const c = ctx.db.caregiver.id.find(p.caregiverId);
    return c ? [c] : [];
  }
);

// This connection's role (zero or one row). The worker reads it with a caller's token to check who is calling it.
export const myRole = spacetimedb.view(
  { name: 'my_role', public: true },
  t.array(principal.rowType),
  ctx => {
    const p = ctx.db.principal.identity.find(ctx.sender);
    return p ? [p] : [];
  }
);

// ---------- identity management ----------

export const grantRole = spacetimedb.reducer(
  { identity: t.identity(), role: t.string(), caregiverId: t.option(t.string()) },
  (ctx, { identity, role, caregiverId }) => {
    requireRole(ctx, 'admin');
    if (!['admin', 'vision', 'worker', 'caregiver'].includes(role)) {
      throw new SenderError('role must be admin, vision, worker or caregiver');
    }
    if (role === 'caregiver') {
      if (!caregiverId || !ctx.db.caregiver.id.find(caregiverId)) {
        throw new SenderError('caregiver role needs an existing caregiverId');
      }
    }
    const row = { identity, role, caregiverId };
    if (ctx.db.principal.identity.find(identity)) ctx.db.principal.identity.update(row);
    else ctx.db.principal.insert(row);
  }
);

// A caregiver signs in on a new browser or phone with the code the admin gave them.
// Any number of devices (identities) can claim the same caregiver.
export const claimCaregiver = spacetimedb.reducer(
  { caregiverId: t.string(), joinCode: t.string() },
  (ctx, { caregiverId, joinCode }) => {
    const contact = ctx.db.caregiverContact.caregiverId.find(caregiverId);
    if (!contact || !contact.joinCode || contact.joinCode !== joinCode) {
      throw new SenderError('wrong caregiver or join code');
    }
    const existing = ctx.db.principal.identity.find(ctx.sender);
    if (existing && existing.role !== 'caregiver') {
      throw new SenderError('this identity already has another role');
    }
    const row = { identity: ctx.sender, role: 'caregiver', caregiverId };
    if (existing) ctx.db.principal.identity.update(row);
    else ctx.db.principal.insert(row);
  }
);

// ---------- setup (dashboard / admin) ----------

export const upsertRoom = spacetimedb.reducer(
  { id: t.string(), name: t.string(), widthM: t.f64(), heightM: t.f64(), floorPlan: t.string() },
  (ctx, args) => {
    requireRole(ctx, 'admin', 'caregiver');
    if (args.widthM <= 0 || args.heightM <= 0) throw new SenderError('room size must be positive');
    if (ctx.db.room.id.find(args.id)) ctx.db.room.id.update(args);
    else ctx.db.room.insert(args);
  }
);

export const upsertCamera = spacetimedb.reducer(
  { id: t.string(), roomId: t.string(), name: t.string(), homography: t.array(t.f64()), blindSpots: t.array(Polygon) },
  (ctx, args) => {
    requireRole(ctx, 'admin', 'caregiver', 'vision');
    if (args.homography.length !== 9 && args.homography.length !== 0) {
      throw new SenderError('homography must have 9 numbers (or none before calibration)');
    }
    const existing = ctx.db.camera.id.find(args.id);
    if (existing) ctx.db.camera.id.update({ ...existing, ...args });
    else ctx.db.camera.insert({ ...args, status: 'offline', lastSeen: ctx.timestamp });
  }
);

export const upsertCaregiver = spacetimedb.reducer(
  {
    id: t.string(),
    name: t.string(),
    role: t.string(),
    phone: t.string(),
    joinCode: t.string(), // lets the caregiver's phone or laptop sign in as them (see claimCaregiver)
    buzzerId: t.option(t.string()),
    onDuty: t.bool(),
  },
  (ctx, args) => {
    requireRole(ctx, 'admin', 'caregiver');
    const { phone, joinCode } = args;
    const c = { id: args.id, name: args.name, role: args.role, buzzerId: args.buzzerId, onDuty: args.onDuty };
    if (!['primary', 'backup', 'staff'].includes(c.role)) {
      throw new SenderError('role must be primary, backup or staff');
    }
    if (ctx.db.caregiver.id.find(c.id)) ctx.db.caregiver.id.update(c);
    else ctx.db.caregiver.insert(c);
    // Blank phone or join code on an existing caregiver means "keep what is stored".
    const prev = ctx.db.caregiverContact.caregiverId.find(c.id);
    if (!prev && (!phone || !joinCode)) throw new SenderError('a new caregiver needs a phone number and a join code');
    const contact = { caregiverId: c.id, phone: phone || prev!.phone, joinCode: joinCode || prev!.joinCode };
    if (prev) ctx.db.caregiverContact.caregiverId.update(contact);
    else ctx.db.caregiverContact.insert(contact);
  }
);

export const upsertNamedArea = spacetimedb.reducer(
  { id: t.string(), roomId: t.string(), name: t.string(), polygon: t.array(Point) },
  (ctx, args) => {
    requireRole(ctx, 'admin', 'caregiver');
    if (args.polygon.length < 3) throw new SenderError('a polygon needs at least 3 points');
    if (ctx.db.namedArea.id.find(args.id)) ctx.db.namedArea.id.update(args);
    else ctx.db.namedArea.insert(args);
  }
);

// ---------- zones ----------

function checkSeverity(severity: string) {
  if (!(severity in SEVERITY_RANK)) throw new SenderError('severity must be high, medium or low');
}

// Dashboard/phone: a person draws or edits a zone, so it is active immediately.
export const createZone = spacetimedb.reducer(
  {
    roomId: t.string(),
    name: t.string(),
    polygon: t.array(Point),
    severity: t.string(),
    schedule: Schedule,
    escalation: t.string(),
  },
  (ctx, args) => {
    const who = requireRole(ctx, 'admin', 'caregiver');
    checkSeverity(args.severity);
    if (args.polygon.length < 3) throw new SenderError('a polygon needs at least 3 points');
    ctx.db.zone.insert({
      id: nextId(ctx, 'z'),
      ...args,
      status: 'active',
      confirmedBy: who.caregiverId ?? 'admin',
    });
  }
);

// Worker: a draft from a plain-language rule. Always inactive; polygon comes from the named area.
export const saveZoneDraft = spacetimedb.reducer(
  {
    roomId: t.string(),
    areaName: t.string(),
    schedule: Schedule,
    severity: t.string(),
    escalation: t.string(),
  },
  (ctx, args) => {
    requireRole(ctx, 'worker');
    checkSeverity(args.severity);
    const area = [...ctx.db.namedArea.roomId.filter(args.roomId)].find(
      a => a.name.toLowerCase() === args.areaName.toLowerCase()
    );
    if (!area) throw new SenderError(`no named area "${args.areaName}" in room ${args.roomId}`);
    ctx.db.zone.insert({
      id: nextId(ctx, 'zd'),
      roomId: args.roomId,
      name: area.name,
      polygon: area.polygon,
      severity: args.severity,
      schedule: args.schedule,
      escalation: args.escalation,
      status: 'draft',
      confirmedBy: undefined,
    });
  }
);

export const confirmZone = spacetimedb.reducer({ zoneId: t.string() }, (ctx, { zoneId }) => {
  const who = requireRole(ctx, 'admin', 'caregiver');
  const z = ctx.db.zone.id.find(zoneId);
  if (!z) throw new SenderError('zone not found');
  if (z.status !== 'draft') throw new SenderError('only a draft can be confirmed');
  ctx.db.zone.id.update({ ...z, status: 'active', confirmedBy: who.caregiverId ?? 'admin' });
});

export const updateZone = spacetimedb.reducer(
  {
    zoneId: t.string(),
    name: t.string(),
    severity: t.string(),
    schedule: Schedule,
    escalation: t.string(),
    status: t.string(),
  },
  (ctx, { zoneId, ...changes }) => {
    requireRole(ctx, 'admin', 'caregiver');
    checkSeverity(changes.severity);
    if (!['active', 'off'].includes(changes.status)) {
      throw new SenderError('status must be active or off (use confirmZone for drafts)');
    }
    const z = ctx.db.zone.id.find(zoneId);
    if (!z) throw new SenderError('zone not found');
    if (z.status === 'draft') throw new SenderError('confirm the draft before editing its status');
    ctx.db.zone.id.update({ ...z, ...changes });
  }
);

// ---------- vision service ----------

export const updatePositions = spacetimedb.reducer(
  { roomId: t.string(), positions: t.array(PositionInput) },
  (ctx, { roomId, positions }) => {
    requireRole(ctx, 'vision');
    const seen = new Set<string>();
    for (const p of positions) {
      if (p.kind !== 'child' && p.kind !== 'adult') throw new SenderError('kind must be child or adult');
      seen.add(p.trackId);
      const row = { ...p, roomId, updatedAt: ctx.timestamp };
      if (ctx.db.trackPosition.trackId.find(p.trackId)) ctx.db.trackPosition.trackId.update(row);
      else ctx.db.trackPosition.insert(row);
    }
    // Tracks in this room that were not reported are no longer visible.
    for (const row of [...ctx.db.trackPosition.roomId.filter(roomId)]) {
      if (!seen.has(row.trackId) && row.visible) {
        ctx.db.trackPosition.trackId.update({ ...row, visible: false });
      }
    }
  }
);

export const tagAdult = spacetimedb.reducer(
  { trackId: t.string(), caregiverId: t.string() },
  (ctx, { trackId, caregiverId }) => {
    requireRole(ctx, 'vision');
    const track = ctx.db.trackPosition.trackId.find(trackId);
    const cg = ctx.db.caregiver.id.find(caregiverId);
    if (!track) throw new SenderError('track not found');
    if (!cg) throw new SenderError('caregiver not found');
    ctx.db.trackPosition.trackId.update({ ...track, kind: 'adult', label: cg.name.charAt(0).toUpperCase() });
  }
);

export const cameraHealth = spacetimedb.reducer(
  { cameraId: t.string(), status: t.string() },
  (ctx, { cameraId, status }) => {
    requireRole(ctx, 'vision');
    if (!['online', 'offline', 'low_fps'].includes(status)) throw new SenderError('bad camera status');
    const cam = ctx.db.camera.id.find(cameraId);
    if (!cam) throw new SenderError('camera not found');
    ctx.db.camera.id.update({ ...cam, status, lastSeen: ctx.timestamp });
  }
);

export const reportEvent = spacetimedb.reducer(
  {
    trackId: t.string(),
    eventType: t.string(),
    zoneId: t.string(),
    severity: t.string(),
    predictedEntryS: t.option(t.f64()),
    clipRef: t.string(),
  },
  (ctx, args) => {
    requireRole(ctx, 'vision');
    checkSeverity(args.severity);

    // Reuse an open alert for the same child and zone.
    const existing = [...ctx.db.alert.trackId.filter(args.trackId)].find(
      a => a.zoneId === args.zoneId && !CLOSED_STATES.has(a.status)
    );
    if (existing) {
      logEvent(ctx, existing.id, 'repeat', `${args.eventType} seen again`, args.clipRef);
      return;
    }

    const timeouts = TIMEOUTS_S[args.severity];
    const id = nextId(ctx, 'a');
    const nextEscalationAt = timeouts ? scheduleEscalation(ctx, id, 0, timeouts[0]) : undefined;
    ctx.db.alert.insert({
      id,
      trackId: args.trackId,
      eventType: args.eventType,
      zoneId: args.zoneId,
      severity: args.severity,
      status: 'notified',
      createdAt: ctx.timestamp,
      predictedEntryS: args.predictedEntryS,
      clipRef: args.clipRef,
      ownerId: undefined,
      ackedAt: undefined,
      ackedVia: undefined,
      escalationLevel: 0,
      nextEscalationAt,
      closedAt: undefined,
      urgencyNote: undefined,
    });
    logEvent(ctx, id, 'detected', `${args.eventType} (${args.severity}) in zone ${args.zoneId || 'n/a'}`, args.clipRef);
  }
);

// ---------- alert lifecycle ----------

// A reducer cannot return data, so "already owned" is not an error: the call is a no-op
// and callers see the owner by reading the alert row.
export const acknowledgeAlert = spacetimedb.reducer(
  { alertId: t.string(), caregiverId: t.string(), via: t.string() },
  (ctx, { alertId, caregiverId, via }) => {
    const who = requireRole(ctx, 'vision', 'worker', 'caregiver');
    if (!['buzzer', 'dashboard', 'phone_app', 'phone_call', 'voice'].includes(via)) {
      throw new SenderError('bad via');
    }
    // Each caller may only claim the channels it really owns.
    if (who.role === 'vision' && via !== 'buzzer') throw new SenderError('vision can only ack via buzzer');
    if (who.role === 'worker' && via !== 'phone_call' && via !== 'voice') {
      throw new SenderError('worker can only ack via phone_call or voice');
    }
    if (who.role === 'caregiver') {
      if (via !== 'dashboard' && via !== 'phone_app') throw new SenderError('caregivers ack via dashboard or phone_app');
      if (who.caregiverId !== caregiverId) throw new SenderError('you can only acknowledge as yourself');
    }

    const a = ctx.db.alert.id.find(alertId);
    if (!a) throw new SenderError('alert not found');
    const cg = ctx.db.caregiver.id.find(caregiverId);
    if (!cg) throw new SenderError('caregiver not found');
    if (a.ownerId) return; // already owned
    if (!ACKABLE_STATES.has(a.status)) throw new SenderError(`alert is ${a.status}`);

    cancelTimers(ctx, alertId);
    cancelCalls(ctx, alertId);
    ctx.db.alert.id.update({
      ...a,
      status: 'owned',
      ownerId: caregiverId,
      ackedAt: ctx.timestamp,
      ackedVia: via,
      nextEscalationAt: undefined,
    });
    logEvent(ctx, alertId, 'acknowledged', `${cg.name} is handling it (via ${via})`);
  }
);

// A caregiver says they cannot respond. They do not take the alert; escalation moves on at once instead of waiting out its
// timer (the primary declines: the backup is called now; the backup declines: all staff and the alarm now).
// The worker may record a decline spoken to the voice agent (via phone_call or voice).
export const declineAlert = spacetimedb.reducer(
  { alertId: t.string(), caregiverId: t.string(), via: t.string() },
  (ctx, { alertId, caregiverId, via }) => {
    const who = requireRole(ctx, 'worker', 'caregiver');
    if (!['dashboard', 'phone_app', 'phone_call', 'voice'].includes(via)) throw new SenderError('bad via');
    if (who.role === 'worker' && via !== 'phone_call' && via !== 'voice') {
      throw new SenderError('worker can only decline via phone_call or voice');
    }
    if (who.role === 'caregiver') {
      if (via !== 'dashboard' && via !== 'phone_app') throw new SenderError('caregivers decline via dashboard or phone_app');
      if (who.caregiverId !== caregiverId) throw new SenderError('you can only decline as yourself');
    }
    const a = ctx.db.alert.id.find(alertId);
    if (!a) throw new SenderError('alert not found');
    const cg = ctx.db.caregiver.id.find(caregiverId);
    if (!cg) throw new SenderError('caregiver not found');
    if (a.ownerId) return;                                            // someone already has it
    if (a.status !== 'notified' && a.status !== 'escalated') return;  // nothing left to skip
    logEvent(ctx, alertId, 'declined', `${cg.name} cannot respond (via ${via}); escalating now`);
    cancelTimers(ctx, alertId);
    runEscalation(ctx, alertId, a.escalationLevel);
  }
);

export const closeAlert = spacetimedb.reducer(
  { alertId: t.string(), reason: t.string() },
  (ctx, { alertId, reason }) => {
    requireRole(ctx, 'vision', 'caregiver');
    const a = ctx.db.alert.id.find(alertId);
    if (!a) throw new SenderError('alert not found');
    if (a.status !== 'owned') throw new SenderError('only an owned alert can be closed');
    ctx.db.alert.id.update({ ...a, status: 'closed', closedAt: ctx.timestamp });
    logEvent(ctx, alertId, 'closed', reason);
  }
);

// Worker fallback when scheduled reducers are not usable: escalate every alert past its due time.
export const escalateDue = spacetimedb.reducer(ctx => {
  requireRole(ctx, 'worker');
  const now = ctx.timestamp.microsSinceUnixEpoch;
  for (const status of ['notified', 'escalated']) {
    for (const a of [...ctx.db.alert.status.filter(status)]) {
      if (a.nextEscalationAt && a.nextEscalationAt.microsSinceUnixEpoch <= now) {
        cancelTimers(ctx, a.id);
        runEscalation(ctx, a.id, a.escalationLevel);
      }
    }
  }
});

// Admin only: escalate one alert right now instead of waiting for its timer (drills and test calls).
export const escalateNow = spacetimedb.reducer({ alertId: t.string() }, (ctx, { alertId }) => {
  requireRole(ctx, 'admin');
  const a = ctx.db.alert.id.find(alertId);
  if (!a) throw new SenderError('alert not found');
  cancelTimers(ctx, alertId);
  runEscalation(ctx, alertId, a.escalationLevel);
});

// Scheduled by Spacetime itself. Clients cannot call it.
export const escalationTick = spacetimedb.reducer(
  { onSchedule: escalationTimer },
  { timer: escalationTimer.rowType },
  (ctx, { timer }) => {
    if (!ctx.sender.equals(ctx.identity)) throw new SenderError('scheduler only');
    runEscalation(ctx, timer.alertId, timer.level);
  }
);

// Only downward, and only for medium and low alerts. High alerts are never touched.
export const setUrgency = spacetimedb.reducer(
  { alertId: t.string(), note: t.string(), lowerTo: t.string() },
  (ctx, { alertId, note, lowerTo }) => {
    requireRole(ctx, 'worker');
    checkSeverity(lowerTo);
    const a = ctx.db.alert.id.find(alertId);
    if (!a) throw new SenderError('alert not found');
    if (a.severity === 'high') throw new SenderError('high alerts cannot be changed');
    if (CLOSED_STATES.has(a.status)) throw new SenderError('alert is already closed');
    if (SEVERITY_RANK[lowerTo] >= SEVERITY_RANK[a.severity]) {
      throw new SenderError('urgency can only be lowered');
    }
    // Lowering to a level with no escalation (low) also stops the pending timer.
    if (!TIMEOUTS_S[lowerTo]) {
      cancelTimers(ctx, alertId);
      ctx.db.alert.id.update({ ...a, severity: lowerTo, urgencyNote: note, nextEscalationAt: undefined });
    } else {
      ctx.db.alert.id.update({ ...a, severity: lowerTo, urgencyNote: note });
    }
    logEvent(ctx, alertId, 'urgency_lowered', `Lowered from ${a.severity} to ${lowerTo}: ${note}`);
  }
);

// ---------- worker: calls, reports ----------

export const updateCallJob = spacetimedb.reducer(
  { jobId: t.string(), status: t.string() },
  (ctx, { jobId, status }) => {
    requireRole(ctx, 'worker');
    if (!['ringing', 'answered', 'failed'].includes(status)) throw new SenderError('bad call status');
    const job = ctx.db.callJob.id.find(jobId);
    if (!job) throw new SenderError('call job not found');
    if (job.status === 'cancelled') return; // the alert was already acknowledged
    ctx.db.callJob.id.update({ ...job, status });
    logEvent(ctx, job.alertId, 'call_result', `Call attempt ${job.attempt}: ${status}`);
    // The backup call failed (the worker already retried once): do not wait out the timer. Go to unanswered now,
    // which sounds the local alarm and buzzes all staff (CLUADE.md "Twilio or Cartesia fails").
    if (status === 'failed' && job.attempt === 1) {
      const a = ctx.db.alert.id.find(job.alertId);
      if (a && a.status === 'escalated' && !a.ownerId) {
        cancelTimers(ctx, a.id);
        runEscalation(ctx, a.id, 1);
      }
    }
  }
);

export const saveReport = spacetimedb.reducer(
  { alertId: t.option(t.string()), summary: t.string(), lines: t.array(ReportLine) },
  (ctx, { alertId, summary, lines }) => {
    requireRole(ctx, 'worker');
    if (alertId) {
      const a = ctx.db.alert.id.find(alertId);
      if (!a) throw new SenderError('alert not found');
      if (a.status !== 'closed') throw new SenderError('reports are written for closed alerts');
      // Defense in depth: every line must cite a real event of this alert.
      const valid = new Set([...ctx.db.incidentEvent.alertId.filter(alertId)].map(e => e.id));
      for (const line of lines) {
        if (!valid.has(line.eventId)) throw new SenderError(`unknown event ${line.eventId}`);
      }
      ctx.db.alert.id.update({ ...a, status: 'reported' });
    }
    ctx.db.report.insert({
      id: nextId(ctx, 'r'),
      kind: alertId ? 'incident' : 'daily',
      alertId,
      summary,
      lines,
      caregiverNote: undefined,
      status: 'draft',
    });
  }
);

export const addCaregiverNote = spacetimedb.reducer(
  { reportId: t.string(), text: t.string() },
  (ctx, { reportId, text }) => {
    requireRole(ctx, 'caregiver', 'admin');
    const r = ctx.db.report.id.find(reportId);
    if (!r) throw new SenderError('report not found');
    ctx.db.report.id.update({ ...r, caregiverNote: text });
  }
);

export const saveRecallMatch = spacetimedb.reducer(
  { product: t.string(), recallTitle: t.string(), recallUrl: t.string(), confidence: t.f64() },
  (ctx, args) => {
    requireRole(ctx, 'worker');
    ctx.db.recallMatch.insert({ id: nextId(ctx, 'rc'), ...args, status: 'new' });
  }
);
