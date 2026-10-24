import { useEffect, useState } from 'react';
import { VISION_URL, WORKER_URL } from './config';

export interface VisionHealth { camera_online?: boolean; fps?: number; calibrated?: boolean; spacetime_online?: boolean | null;
  buzzers?: Record<string, unknown>; alarm?: { active: boolean; reasons: string[] }; detector?: string }
export interface WorkerHealth { claude?: string; calls?: string; claude_cost_usd?: number; claude_calls?: number; public_url?: string | null }
/** undefined: not checked yet; null: not reachable */
export interface Services { vision: VisionHealth | null | undefined; worker: WorkerHealth | null | undefined }

async function probe<T>(url: string): Promise<T | null> {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), 2500);
  try {
    const r = await fetch(url, { signal: ctl.signal, cache: 'no-store' });
    return r.ok ? await r.json() as T : null;
  } catch { return null; } finally { clearTimeout(timer); }
}

// One poll every 5 s, shared by every component that asks (the System card, the monitor footer, the event trace).
let current: Services = { vision: undefined, worker: undefined };
const listeners = new Set<(s: Services) => void>();
let timer: ReturnType<typeof setInterval> | null = null;

async function tick() {
  const [vision, worker] = await Promise.all([probe<VisionHealth>(`${VISION_URL}/health`), probe<WorkerHealth>(`${WORKER_URL}/health`)]);
  current = { vision, worker };
  listeners.forEach(l => l(current));
}

export function useServices(): Services {
  const [s, setS] = useState(current);
  useEffect(() => {
    listeners.add(setS);
    if (!timer) { void tick(); timer = setInterval(tick, 5000); }
    return () => {
      listeners.delete(setS);
      if (listeners.size === 0 && timer) { clearInterval(timer); timer = null; }
    };
  }, []);
  return s;
}
