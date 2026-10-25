import type { Incident, IncidentMessage, IncidentThread, IncidentThreadChanges, IncidentResolution, LookoutState, ResolutionOutcome } from "./types";
import { recordAudit } from "./reviewAudit";
const iso = (value: string | number) => new Date(typeof value === "number" ? value * 1000 : value).toISOString();
export function displayIncidentTitle(title: string) {
  return title === "Motion near restricted area" ? "Someone near the doorway" : title === "Activity flagged for review" ? "Someone lowered quickly near the play area" : title;
}
export function adaptIncidentThread(incident: Incident, context: {
  cameraId: string; cameraName: string; recordingStartedAt?: string; thumbnailUrl?: string;
  attempts?: LookoutState["attempts"]; changes?: IncidentThreadChanges;
}): IncidentThread {
  const opened = iso(incident.opened_at);
  const base = context.recordingStartedAt && Number.isFinite(Date.parse(context.recordingStartedAt))
    ? Date.parse(context.recordingStartedAt) : Date.parse(opened) - (incident.media_time_ms ?? 0);
  const atSeconds = (seconds: number) => new Date(base + seconds * 1000).toISOString();
  const startSeconds = incident.media_time_ms === undefined ? undefined : incident.media_time_ms / 1000;
  const endSeconds = incident.media_end_time_ms === undefined ? undefined : incident.media_end_time_ms / 1000;
  const startedAt = startSeconds === undefined ? opened : atSeconds(startSeconds);
  const endedAt = incident.resolved_at ? iso(incident.resolved_at) : endSeconds === undefined ? undefined : atSeconds(endSeconds);
  const resolution = context.changes?.resolution ?? incident.resolution;
  const status = resolution || ["resolved", "dismissed", "closed"].includes(incident.status) ? "resolved" : ["acknowledged", "owned", "in_review"].includes(incident.status) ? "in_review" : "open";
  const derived: IncidentMessage[] = [{ kind: "detection", id: `${incident.id}:detection`, at: startedAt, text: incident.observations[0] || displayIncidentTitle(incident.title), anchorSeconds: startSeconds, ...(incident.confidence === undefined ? {} : { confidence: incident.confidence }) }];
  if (incident.demo_response) {
    for (const [index, step] of incident.demo_response.entries()) {
      if (!step.tool && status === "resolved") continue; // Resolution has its own message below.
      derived.push({ kind: "system", id: `${incident.id}:system:${index}`, at: atSeconds(step.time_ms / 1000), text: step.description, anchorSeconds: step.time_ms / 1000 });
    }
  } else {
    for (const attempt of (context.attempts ?? []).filter(a => a.incident_id === incident.id)) derived.push({ kind: "system", id: `${incident.id}:attempt:${attempt.id}`, at: iso(attempt.due), text: `Caregiver call ${attempt.status.replaceAll("_", " ")}${attempt.payload?.mode === "simulation" ? " (simulated)" : ""}.` });
    if (incident.acknowledged_at) derived.push({ kind: "status", id: `${incident.id}:ack`, at: iso(incident.acknowledged_at), authorId: incident.assigned_responder || "staff", text: `${incident.assigned_responder || "A caregiver"} is responding`, anchorSeconds: (Date.parse(incident.acknowledged_at) - base) / 1000 });
  }
  if (endedAt && ["resolved", "dismissed", "closed"].includes(incident.status)) derived.push({ kind: "status", id: `${incident.id}:resolved`, at: endedAt, authorId: incident.assigned_responder || "staff", text: `${incident.assigned_responder || "A caregiver"} ${incident.status === "dismissed" ? "dismissed" : "resolved"} this`, anchorSeconds: endSeconds });
  const messages = [...(incident.messages?.length ? incident.messages : derived), ...(context.changes?.messages ?? [])].sort((a, b) => Date.parse(a.at) - Date.parse(b.at));
  return { id: incident.id, title: displayIncidentTitle(incident.title), cameraId: context.cameraId, cameraName: context.cameraName, startedAt, endedAt: resolution?.at ?? endedAt, startSeconds, endSeconds, status, resolution, thumbnailUrl: incident.evidence_url || context.thumbnailUrl, messages, lastReadAt: context.changes?.lastReadAt ?? incident.lastReadAt, source: incident };
}
export function addIncidentNote(input: { incidentId: string; cameraId: string; userId: string; authorName: string; text: string; at?: string; anchorAt?: string; anchorSeconds?: number }): IncidentMessage {
  const text = input.text.trim();
  if (!text) throw new Error("Write a note first.");
  if (text.length > 2000) throw new Error("Keep notes under 2,000 characters.");
  const at = input.at ?? new Date().toISOString();
  recordAudit({ action: "add_note", userId: input.userId, incidentId: input.incidentId, cameraId: input.cameraId, at, reason: input.anchorAt ? `Anchored at ${input.anchorAt}` : undefined });
  return { kind: "note", id: crypto.randomUUID(), at, authorId: input.userId, authorName: input.authorName, text, anchorAt: input.anchorAt, anchorSeconds: input.anchorSeconds };
}
export function resolveIncidentThread(input: { incidentId: string; cameraId: string; userId: string; outcome: ResolutionOutcome; at?: string }): { resolution: IncidentResolution; message: IncidentMessage } {
  const at = input.at ?? new Date().toISOString();
  recordAudit({ action: "resolve_incident", userId: input.userId, incidentId: input.incidentId, cameraId: input.cameraId, at, reason: input.outcome });
  const labels = { false_alarm: "False alarm", handled: "Handled", escalated: "Escalated" };
  return { resolution: { outcome: input.outcome, by: input.userId, at }, message: { kind: "status", id: crypto.randomUUID(), at, authorId: input.userId, text: `${input.userId} resolved this · ${labels[input.outcome]}` } };
}
export const threadClock = (at: string) => new Date(at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit", second: "2-digit" });
