import { MoreHorizontal, Pin, Trash2, Video } from "lucide-react";

export default function CameraSidebar({ rooms, selected, main, removed, onSelect, onMain, onRemove }: {
  rooms: { id: string; name: string }[]; selected: number; main: number; removed: number[];
  onSelect: (index: number) => void; onMain: (index: number) => void; onRemove: (index: number) => void;
}) {
  const available = rooms.map((camera, index) => ({ camera, index })).filter(({ index }) => !removed.includes(index)).sort((a, b) => Number(b.index === main) - Number(a.index === main));
  return <div className="sidebar-cameras" aria-label="Available cameras">{available.map(({ camera, index }) => <div className={`sidebar-camera ${selected === index ? "selected" : ""}`} key={camera.id}>
    <button className="sidebar-camera-select" onClick={() => onSelect(index)} aria-pressed={selected === index} title={`${camera.name} · ${camera.id}`}><Video size={14} /><span className="camera-row-label"><span>{camera.name}</span><small>{camera.id}</small></span></button>
    <button className={`camera-pin ${main === index ? "is-pinned" : ""}`} aria-label={`Pin ${camera.name} as main camera`} aria-pressed={main === index} title={main === index ? "Main camera" : "Pin as main camera"} onClick={() => onMain(index)}><Pin size={12} fill={main === index ? "currentColor" : "none"} /></button>
    <details className="camera-actions" name="camera-actions" onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget)) event.currentTarget.removeAttribute("open"); }} onKeyDown={event => { if (event.key === "Escape") { event.currentTarget.removeAttribute("open"); event.currentTarget.querySelector("summary")?.focus(); } }}>
      <summary aria-label={`Options for ${camera.name}`}><MoreHorizontal size={15} /></summary>
      <div className="camera-details-popover"><strong>{camera.name}</strong><dl><div><dt>Camera</dt><dd>{camera.id}</dd></div><div><dt>Source</dt><dd>{index === 2 ? "Live camera" : "Demo / local source"}</dd></div><div><dt>Role</dt><dd>{main === index ? "Main camera" : "Camera"}</dd></div></dl><button disabled={available.length === 1} title={available.length === 1 ? "Keep at least one camera in the workspace" : "Remove from workspace"} onClick={() => onRemove(index)}><Trash2 size={12} />Remove camera</button></div>
    </details>
  </div>)}</div>;
}
