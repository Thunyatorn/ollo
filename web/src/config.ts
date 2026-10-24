// The browser connects to Spacetime directly. On a phone, "localhost" would be the phone itself,
// so the default host is whatever host served this page.
const host = window.location.hostname;

export const STDB_URI = import.meta.env.VITE_STDB_URI ?? `ws://${host}:3000`;
export const STDB_DB = import.meta.env.VITE_STDB_DB ?? 'nestwatch-test';
// Worker service (rule interpretation). Not built yet; screens handle it being offline.
export const WORKER_URL = import.meta.env.VITE_WORKER_URL ?? `http://${host}:8787`;
// Vision service local HTTP (snapshots, clips). Only reachable on the daycare network.
export const VISION_URL = import.meta.env.VITE_VISION_URL ?? `http://${host}:8000`;
