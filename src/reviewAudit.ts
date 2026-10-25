export type ReviewAction = "open_thread" | "add_note" | "resolve_incident" | "export" | "view_activity";
export type AuditRecord = {
  action: ReviewAction; userId: string; incidentId?: string; cameraId?: string;
  at: string; range?: { start: number; end: number }; reason?: string;
};
// Integration stub: session memory only, without authentication or durable storage.
const entries: (AuditRecord & { at: string })[] = [];
export function recordAudit(record: AuditRecord) {
  const entry = { ...record, ...(record.range ? { range: { ...record.range } } : {}), at: record.at ?? new Date().toISOString() };
  entries.push(entry); return entry;
}
export function reviewActivity(cameraId: string) { return entries.filter(entry => entry.cameraId === cameraId); }
