export type ReviewAction = "mark_incident" | "set_in" | "set_out" | "save_clip" | "snapshot" | "export" | "view_activity";
export type AuditRecord = { action: ReviewAction; userId: string; cameraId: string; range: { start: number; end: number }; reason?: string };
// Integration boundary only. Session memory is not a durable or authenticated audit log.
const entries: (AuditRecord & { at: string })[] = [];
export function recordAudit(record: AuditRecord) {
  const entry = { ...record, range: { ...record.range }, at: new Date().toISOString() };
  entries.push(entry);
  return entry;
}
export function reviewActivity(cameraId: string) { return entries.filter(entry => entry.cameraId === cameraId); }
