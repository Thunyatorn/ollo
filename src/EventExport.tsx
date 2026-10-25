import { useRef, useState } from "react";
import { Download } from "lucide-react";
import type { Incident } from "./types";
import { recordAudit } from "./reviewAudit";

export default function EventExport({ incident, cameraId, userId }: { incident: Incident; cameraId: string; userId: string }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [kind, setKind] = useState<"details" | "clip">("details");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const open = (next: "details" | "clip") => { setKind(next); setReason(""); setError(""); dialog.current?.showModal(); };
  const download = async () => {
    if (!reason.trim() || busy) return;
    setBusy(true); setError("");
    try {
      let blob: Blob;
      let extension = "json";
      if (kind === "clip") {
        if (!incident.clip_url) throw new Error("Footage is not available for this event yet.");
        const response = await fetch(incident.clip_url);
        if (!response.ok) throw new Error("The footage could not be downloaded. Try again.");
        blob = await response.blob();
        if (!blob.type.startsWith("video/")) throw new Error("The server did not return a video clip.");
        extension = blob.type.includes("mp4") ? "mp4" : "webm";
      } else {
        blob = new Blob([JSON.stringify({ incident, cameraId, exportedBy: userId, exportedAt: new Date().toISOString(), reason: reason.trim() }, null, 2)], { type: "application/json" });
      }
      recordAudit({ action: "export", userId, cameraId, range: { start: (incident.media_time_ms ?? 0) / 1000, end: (incident.media_end_time_ms ?? incident.media_time_ms ?? 0) / 1000 }, reason: `${kind}: ${reason.trim()}` });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a"); link.href = url; link.download = `event-${incident.id.replace(/[^a-zA-Z0-9_-]/g, "_")}-${kind}.${extension}`;
      document.body.append(link); link.click(); link.remove(); window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      dialog.current?.close();
    } catch (e) { setError(e instanceof Error ? e.message : "Export unavailable. Try again."); }
    finally { setBusy(false); }
  };
  return <div className="event-export">
    <button className="text-button" onClick={() => open("details")}><Download size={13} />Export details</button>
    <button className="text-button" disabled={!incident.clip_url} title={incident.clip_url ? "Download the saved evidence clip" : "No saved footage clip is available for this event"} onClick={() => open("clip")}><Download size={13} />Export clip</button>
    <dialog ref={dialog} className="event-export-dialog" aria-labelledby={`export-title-${incident.id}`} onCancel={event => { if (busy) event.preventDefault(); }}>
      <form onSubmit={event => { event.preventDefault(); void download(); }}>
        <h2 id={`export-title-${incident.id}`}>Export {kind === "details" ? "event details" : "footage clip"}</h2>
        <p>{incident.title}</p>
        <label>Reason for export<input autoFocus required maxLength={240} value={reason} disabled={busy} onChange={event => setReason(event.target.value)} /></label>
        <p>{kind === "details" ? "Downloads the event details as JSON, including your name, export time and reason." : "Downloads the saved evidence clip. An export watermark has not been applied."}</p>
        {error && <p role="alert">{error}</p>}
        <div className="export-dialog-actions"><button type="button" className="button" disabled={busy} onClick={() => dialog.current?.close()}>Cancel</button><button type="submit" className="button" disabled={busy || !reason.trim()}>{busy ? "Preparing…" : "Download"}</button></div>
      </form>
    </dialog>
  </div>;
}
