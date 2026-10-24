import type { Incident } from "./types";

// Presentation fixtures only; never sent to the incident or calling APIs.
export function demoIncidents(room: number): Incident[] {
  if (room !== 0) return [];
  const opened = new Date();
  opened.setHours(9, 0, 0, 0);
  const times = [28, 83];
  return times.map((seconds, index) => ({
    id: `demo-camera-${room}-${index}`,
    kind: index ? "possible_fall" : "restricted_zone",
    title: index ? "Activity flagged for review" : "Motion near restricted area",
    room: room === 0 ? "Toddler room" : "Gas station",
    status: "resolved",
    opened_at: new Date(opened.getTime() + seconds * 1000).toISOString(),
    observations: [index
      ? room === 0 ? "A person lowered quickly near the play area and remained low. The event was flagged for a caregiver to check." : "A person crouched beside the aisle shelving. The change in posture was flagged for review."
      : room === 0 ? "A tracked person approached the restricted doorway boundary." : "A tracked person approached the restricted stockroom entrance."],
    origin: "fixture",
    priority: index ? "high" : "medium",
    media_time_ms: seconds * 1000,
    media_end_time_ms: (index ? 111 : 46) * 1000,
    resolved_at: new Date(opened.getTime() + (index ? 111 : 46) * 1000).toISOString(),
    source_key: "fixture",
    assigned_responder: "Maya Chen",
    acknowledged_via: index ? "voice" : "dashboard",
    demo_response: index ? [
      { time_ms: 83000, tool: "Notification", description: "Alert sent to Maya Chen." },
      { time_ms: 91000, tool: "Phone call", description: "The agent called Maya after the alert went unanswered (simulated), described the location and observed movement, and asked her to confirm she could respond." },
      { time_ms: 98000, tool: "Voice acknowledgment", description: "Maya confirmed she was responding. The agent recorded her acknowledgment and stopped further escalation." },
      { time_ms: 111000, description: "Maya checked the person and resolved the incident." },
    ] : [
      { time_ms: 28000, tool: "Notification", description: "Maya Chen was alerted to movement near the restricted doorway." },
      { time_ms: 31000, tool: "Call canceled", description: "Maya acknowledged in the dashboard. The agent canceled the pending call because she was responding." },
      { time_ms: 46000, description: "Maya checked the area and resolved the incident." },
    ],
  }));
}
