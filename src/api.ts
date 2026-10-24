import type { LookoutState } from "./types";
export async function request<T = LookoutState>(
  path: string,
  body?: unknown,
  method = "POST",
): Promise<T> {
  const response = await fetch(`/api${path}`, {
    method,
    headers:
      body instanceof FormData
        ? undefined
        : { "Content-Type": "application/json" },
    body:
      body instanceof FormData
        ? body
        : body === undefined
          ? undefined
          : JSON.stringify(body),
  });
  if (!response.ok) {
    // Surface the server's reason (FastAPI `detail`) so the UI can say what to fix.
    let detail: unknown;
    try {
      detail = (await response.json()).detail;
    } catch {
      detail = undefined;
    }
    throw new Error(
      typeof detail === "string" ? detail : `Request failed (${response.status})`,
    );
  }
  return response.json();
}
export const initialState: LookoutState = {
  session: {
    id: "demo",
    epoch: 1,
    status: "active",
    calls_armed: false,
    source_type: "fixture",
  },
  camera: {
    id: "cam-01",
    room_label: "Toddler room",
    health: "active",
    last_frame_at: null,
  },
  incidents: [],
  caregivers: [
    {
      id: "maya",
      name: "Maya Chen",
      role: "Primary caregiver",
      phone_last4: "0184",
    },
    {
      id: "james",
      name: "James Wilson",
      role: "Backup caregiver",
      phone_last4: "0296",
    },
  ],
  events: [],
  settings: {},
};
