// Shared contracts for NestWatch. Source of truth: CLUADE.md ("Connections" > "Message formats").

export type Severity = 'high' | 'medium' | 'low';

export type EventType =
  | 'zone_entry_predicted'
  | 'zone_entry'
  | 'fall'
  | 'climbing'
  | 'stillness'
  | 'unsupervised'
  | 'possible_distress'
  | 'child_not_visible'
  | 'head_count_mismatch';

export type AlertStatus =
  | 'open'
  | 'notified'
  | 'escalated'
  | 'unanswered'
  | 'owned'
  | 'closed'
  | 'reported';

export type AckVia = 'buzzer' | 'dashboard' | 'phone_app' | 'phone_call' | 'voice';
export type CallStatus = 'queued' | 'ringing' | 'answered' | 'failed' | 'cancelled';
export type ZoneStatus = 'draft' | 'active' | 'off';
export type CaregiverRole = 'primary' | 'backup' | 'staff';

/** Escalation timeouts in seconds: [first, second]. null = app only. */
export const ESCALATION_TIMEOUTS_S: Record<Severity, [number, number] | null> = {
  high: [20, 30],
  medium: [45, 60],
  low: null,
};

// Link 2: vision -> Spacetime
export interface PositionUpdate {
  track_id: string;
  kind: 'child' | 'adult';
  label: string;
  x: number;
  y: number;
  vx: number;
  vy: number;
  visible: boolean;
}
export interface PositionsMessage {
  room_id: string;
  at: string;
  positions: PositionUpdate[];
}

// Link 3: vision -> Spacetime
export interface EventMessage {
  track_id: string;
  event_type: EventType;
  zone_id: string;
  severity: Severity;
  predicted_entry_s: number | null;
  camera_id: string;
  clip_ref: string;
  at: string;
}

// Links 6, 9, 13
export interface AcknowledgeRequest {
  alert_id: string;
  caregiver_id: string;
  via: AckVia;
}
export type AcknowledgeReply =
  | { result: 'owned_by_you' }
  | { result: 'already_owned'; owner: string };

// Link 12
export interface CallJob {
  job_id: string;
  alert_id: string;
  caregiver_id: string;
  attempt: number;
  status: CallStatus;
}

// Link 11
export interface RuleInterpretRequest {
  room_id: string;
  text: string;
}
export interface ZoneDraftReply {
  zone_draft_id: string;
  area_name: string;
  schedule: { named: string } | Record<string, unknown>;
  severity: Severity;
  escalation: string;
  needs_drawing: boolean;
  question: string | null;
}

// Link 5: vision <-> wrist buzzer (WebSocket)
export type BuzzerMessage =
  | { type: 'hello'; buzzer_id: string; battery: number }
  | { type: 'buzz'; alert_id: string; severity: Severity }
  | { type: 'ack'; buzzer_id: string; alert_id: string }
  | { type: 'stop'; alert_id: string; owner: string }
  | { type: 'ping' };
