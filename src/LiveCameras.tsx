import { useEffect, useState } from "react";
import { Maximize2, Plus, Video, X } from "lucide-react";
import { request } from "./api";
import type { CameraSummary, LookoutState } from "./types";

type Overlay = NonNullable<LookoutState["overlays"]>[number];

/** SRC-5: one camera's live analyzed picture, long-polled like the main view (no tab throttling of analysis). */
function LivePicture({ camera }: { camera: string }) {
  const [frame, setFrame] = useState<{ image: string; overlays: Overlay[] } | null>(null);
  useEffect(() => {
    const abort = new AbortController();
    (async () => {
      let after = -1;
      while (!abort.signal.aborted) {
        try {
          const r = await fetch(`/api/camera/frame?camera=${encodeURIComponent(camera)}&after=${after}`, { signal: abort.signal });
          if (r.status === 204) continue;
          if (r.ok) {
            const f = await r.json();
            after = f.frame_seq;
            setFrame({ image: `data:image/jpeg;base64,${f.image}`, overlays: f.overlays || [] });
            continue;
          }
        } catch {
          if (abort.signal.aborted) return;
        }
        await new Promise(resolve => setTimeout(resolve, 1000));
      }
    })();
    return () => abort.abort();
  }, [camera]);
  if (!frame) return <div className="preview-source-placeholder"><Video size={24} /><span>Connecting…</span></div>;
  return <div className="live-picture">
    <img src={frame.image} alt={`Live picture from ${camera}`} />
    {frame.overlays.map((o, i) => <span key={o.id ?? i} className="live-box" style={{ left: `${o.x * 100}%`, top: `${o.y * 100}%`, width: `${o.width * 100}%`, height: `${o.height * 100}%` }}>{o.track_id != null && <small>{o.track_id}</small>}</span>)}
  </div>;
}

function rate(c: CameraSummary) {
  if (c.health === "offline") return c.capture?.error || "offline · reconnecting";
  return `${(c.capture?.camera_fps ?? 0).toFixed(0)} fps in · ${(c.analysis_fps ?? 0).toFixed(1)} analyzed · ${c.people ?? 0} ${c.people === 1 ? "person" : "people"}`;
}

/** SRC-5: every server camera other than the focused one, plus a tile to add or remove cameras. */
export default function LiveCameras({ cameras, focus, onFocus, onState }: {
  cameras: CameraSummary[]; focus: string; onFocus: (id: string) => void; onState: (s: LookoutState) => void;
}) {
  const [adding, setAdding] = useState(false);
  const [url, setUrl] = useState(""), [room, setRoom] = useState("");
  const [message, setMessage] = useState(""), [busy, setBusy] = useState(false);
  async function add() {
    setBusy(true); setMessage("");
    try {
      onState(await request("/cameras", { camera: url.trim(), room_label: room.trim() || undefined }));
      setUrl(""); setRoom(""); setAdding(false);
    } catch (e) { setMessage(e instanceof Error ? e.message : "Could not add the camera"); }
    setBusy(false);
  }
  async function remove(id: string) {
    try { onState(await request(`/cameras/${id}`, undefined, "DELETE")); if (id === focus) onFocus("cam-01"); }
    catch (e) { setMessage(e instanceof Error ? e.message : "Could not remove the camera"); }
  }
  return <>
    {cameras.filter(c => c.id !== focus).map(c => <div className="camera-preview-card live-camera-card" key={c.id}>
      <div className="preview-card-header">
        <button className="live-camera-focus" onClick={() => onFocus(c.id)} aria-label={`Focus ${c.room_label}`}><Video size={14} />{c.room_label}</button>
        <span className="live-camera-meta"><small>{c.id.toUpperCase().replace("-", " ")}</small>{!c.primary && <button className="live-camera-remove" title={`Remove ${c.room_label}`} aria-label={`Remove ${c.room_label}`} onClick={() => remove(c.id)}><X size={12} /></button>}</span>
      </div>
      <button className="preview-card-scene live-camera-scene" onClick={() => onFocus(c.id)} aria-label={`Focus ${c.room_label}`}><LivePicture camera={c.id} /></button>
      <div className="preview-card-footer"><span className={c.health === "offline" ? "live-camera-offline" : ""}>{rate(c)}</span><Maximize2 size={12} /></div>
    </div>)}
    {cameras.length < 4 && (adding ? <form className="add-camera-tile live-camera-form" onSubmit={e => { e.preventDefault(); if (url.trim()) void add(); }}>
      <strong>Add a server camera</strong>
      <input aria-label="Stream URL" placeholder="rtsp://192.168.1.20:8554/daycare" value={url} onChange={e => setUrl(e.target.value)} autoFocus />
      <input aria-label="Room name" placeholder="Room name, e.g. Front door" value={room} maxLength={80} onChange={e => setRoom(e.target.value)} />
      {message && <small className="live-camera-offline" role="alert">{message}</small>}
      <span className="live-camera-actions"><button type="button" onClick={() => { setAdding(false); setMessage(""); }}>Cancel</button><button type="submit" disabled={busy || !url.trim()}>{busy ? "Connecting…" : "Add camera"}</button></span>
    </form> : <button className="add-camera-tile" onClick={() => setAdding(true)}><Plus size={20} /><strong>Add a camera</strong><span>RTSP, HLS or MJPEG stream</span><small>{cameras.length} of 4 analyzed on this server</small></button>)}
    {!adding && message && <small className="live-camera-offline" role="alert">{message}</small>}
  </>;
}
