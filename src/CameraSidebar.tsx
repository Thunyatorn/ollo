import { MoreHorizontal, Trash2, Video } from "lucide-react";

export default function CameraSidebar({ rooms, selected, removed, onSelect, onRemove, modes = ["Demo", "Demo", "Offline"], thumbnails = [] }: {
  modes?: string[]; thumbnails?: string[];
  rooms: { id: string; name: string }[]; selected: number; removed: number[];
  onSelect: (index: number) => void; onRemove: (index: number) => void;
}) {
  const available = rooms.map((camera, index) => ({ camera, index })).filter(({ index }) => !removed.includes(index));
  return <div className="sidebar-cameras" aria-label="Available cameras">{available.map(({ camera, index }) => <div className={`sidebar-camera ${selected === index ? "selected" : ""}`} key={camera.id}>
    <button className="sidebar-camera-select" onClick={() => onSelect(index)} aria-pressed={selected === index} title={`${camera.name} · ${camera.id}`}><span className="camera-thumb">{thumbnails[index] ? <img src={thumbnails[index]} alt="Camera preview" /> : <Video size={14} />}</span><span className={`camera-state-dot ${modes[index] === "Offline" ? "offline" : "recorded"}`} title={modes[index]} /><span className="camera-row-label"><span>{camera.name}</span><small>{camera.id}{modes[index] !== "Offline" && ` · ${modes[index]}`}</small></span></button>
    <details className="camera-actions" name="camera-actions" onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget)) event.currentTarget.removeAttribute("open"); }} onKeyDown={event => { if (event.key === "Escape") { event.currentTarget.removeAttribute("open"); event.currentTarget.querySelector("summary")?.focus(); } }}>
      <summary aria-label={`Options for ${camera.name}`} title={`Options for ${camera.name}`}><MoreHorizontal size={15} /></summary>
      <div className="camera-details-popover"><strong>{camera.name}</strong><dl><div><dt>Camera</dt><dd>{camera.id}</dd></div><div><dt>Source</dt><dd>{modes[index]}</dd></div></dl><button disabled={available.length === 1} title={available.length === 1 ? "Keep at least one camera in the workspace" : "Remove from workspace"} onClick={() => onRemove(index)}><Trash2 size={12} />Remove camera</button></div>
    </details>
  </div>)}</div>;
}
