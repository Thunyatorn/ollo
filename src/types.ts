export interface Incident {
  id: string;
  kind: string;
  title: string;
  room: string;
  status: string;
  opened_at: string | number;
  acknowledged_at?: string;
  assigned_responder?: string | null;
  acknowledged_via?: "dashboard" | "app" | "keypad" | "voice";
  resolved_at?: string;
  observations: string[];
  origin: string;
  priority: string;
  media_time_ms?: number;
  media_end_time_ms?: number;
  source_key?: string;
  epoch?: number;
  primary_due_at?: number;
  backup_due_at?: number;
  limitations?: string[];
  clip_url?: string;
  evidence_url?: string;
  demo_response?: { time_ms: number; description: string; tool?: string }[];
  second_opinion?: {
    assessment:
      | "concern_visible"
      | "benign_explanation_likely"
      | "insufficient_view";
    visibility: string;
    observations: { frame_seq: number; description: string }[];
    alternative_explanations: string[];
    model: string;
    cost_usd: number | null;
  };
}
export interface LookoutState {
  session: {
    id: string;
    epoch: number;
    status: string;
    calls_armed: boolean;
    source_type: string;
    media_id?: string;
    recording_started_at?: string;
    kept_until?: string;
    audio_permitted?: boolean;
    camera_label?: string;
  };
  camera: {
    id: string;
    room_label: string;
    health: string;
    last_frame_at: string | null;
    detector?: string;
    analysis_fps?: number;
    predictive?: string;
    // SRC-4 server camera; null for browser and fixture sources.
    capture?: {
      source: string;
      status: "connecting" | "live" | "offline";
      camera_fps: number;
      error: string | null;
    } | null;
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
  analysis?: {
    cloud?: {
      requests: number;
      input_tokens: number;
      output_tokens: number;
      cost_usd: number;
      cost_known: boolean;
    };
  };
  floor_plan?: {
    points: number[][];
    zones: { id: string; name: string; polygon: number[][] }[];
    landmarks: { id: string; name: string; polygon: number[][] }[];
  } | null;
  overlays?: {
    id?: string;
    track_id?: number;
    keypoints?: number[][];
    floor?: number[] | null;
    x: number;
    y: number;
    width: number;
    height: number;
    label: string;
    foot?: number[] | null;
    approach?: {
      p: number;
      eta_s: number | null;
      warning: boolean;
      path: number[][] | null;
      floor_path?: number[][] | null;
    } | null;
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
