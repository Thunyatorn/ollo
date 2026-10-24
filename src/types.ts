export interface Incident {
  id: string;
  kind: string;
  title: string;
  room: string;
  status: string;
  opened_at: string | number;
  acknowledged_at?: string;
  resolved_at?: string;
  observations: string[];
  origin: string;
  priority: string;
  media_time_ms?: number;
  source_key?: string;
  epoch?: number;
  primary_due_at?: number;
  backup_due_at?: number;
}
export interface LookoutState {
  session: {
    id: string;
    epoch: number;
    status: string;
    calls_armed: boolean;
    source_type: string;
    media_id?: string;
  };
  camera: {
    id: string;
    room_label: string;
    health: string;
    last_frame_at: string | null;
  };
  incidents: Incident[];
  caregivers: {
    id: string;
    name: string;
    role: string;
    phone_last4?: string;
  }[];
  events: { id: string; type: string; message: string; at: string | number }[];
  settings: Record<string, unknown>;
  overlays?: {
    x: number;
    y: number;
    width: number;
    height: number;
    label: string;
    epoch: number;
    media_time_ms: number;
  }[];
  attempts?: {
    id: string;
    status: string;
    incident_id: string;
    step: number;
    due: number;
    payload?: { mode?: string; [key: string]: unknown };
  }[];
}
