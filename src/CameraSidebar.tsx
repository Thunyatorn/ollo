import { MoreHorizontal, Star, Video } from "lucide-react";

export default function CameraSidebar({ rooms, selected, main, onSelect, onMain }: {
  rooms: { id: string; name: string }[]; selected: number; main: number;
  onSelect: (index: number) => void; onMain: (index: number) => void;
}) {
  return <div className="sidebar-cameras" aria-label="Available cameras">{rooms.map((camera, index) => <div className={`sidebar-camera ${selected === index ? "selected" : ""}`} key={camera.id}>
    <button className="sidebar-camera-select" onClick={() => onSelect(index)} aria-pressed={selected === index}><Video size={14} /><span>{camera.name}<small>{camera.id}</small></span>{main === index && <Star size={12} fill="currentColor" aria-label="Main camera" />}</button>
    <details className="camera-actions" name="camera-actions" onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget)) event.currentTarget.removeAttribute("open"); }} onKeyDown={event => { if (event.key === "Escape") { event.currentTarget.removeAttribute("open"); event.currentTarget.querySelector("summary")?.focus(); } }}>
      <summary aria-label={`Options for ${camera.name}`}><MoreHorizontal size={15} /></summary>
      <div><button onClick={event => { onMain(index); event.currentTarget.closest("details")?.removeAttribute("open"); }}><Star size={12} />{main === index ? "Main camera" : "Set as main camera"}</button></div>
    </details>
  </div>)}</div>;
}
