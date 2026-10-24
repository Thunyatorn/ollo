import { useEffect, useRef, useState } from "react";
import { Check, ChevronDown, Video } from "lucide-react";

export default function CameraPicker({ rooms, selected, onSelect }: {
  rooms: { id: string; name: string }[]; selected: number; onSelect: (index: number) => void;
}) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null), trigger = useRef<HTMLButtonElement>(null);
  const options = useRef<(HTMLButtonElement | null)[]>([]);
  useEffect(() => {
    if (!open) return;
    options.current[selected]?.focus();
    const dismiss = (event: PointerEvent) => { if (!root.current?.contains(event.target as Node)) setOpen(false); };
    document.addEventListener("pointerdown", dismiss);
    return () => document.removeEventListener("pointerdown", dismiss);
  }, [open, selected]);
  const close = () => { setOpen(false); trigger.current?.focus(); };
  return <div ref={root} className="camera-picker" onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false); }} onKeyDown={event => { if (event.key === "Escape") { event.preventDefault(); close(); } }}>
    <button ref={trigger} className="camera-picker-trigger" aria-label={`Select camera: ${rooms[selected].name}`} aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(!open)} onKeyDown={event => { if (event.key === "ArrowDown" || event.key === "ArrowUp") { event.preventDefault(); setOpen(true); } }}>
      <span>{rooms[selected].name}</span><ChevronDown size={14} />
    </button>
    {open && <div className="camera-picker-menu" role="menu" aria-label="Cameras" onKeyDown={event => {
      const current = options.current.indexOf(document.activeElement as HTMLButtonElement);
      let next = current;
      if (event.key === "ArrowDown") next = (current + 1) % rooms.length;
      else if (event.key === "ArrowUp") next = (current - 1 + rooms.length) % rooms.length;
      else if (event.key === "Home") next = 0;
      else if (event.key === "End") next = rooms.length - 1;
      else return;
      event.preventDefault(); options.current[next]?.focus();
    }}><span className="camera-picker-label">CAMERAS</span>{rooms.map((room, index) => <button key={room.id} ref={element => { options.current[index] = element; }} role="menuitemradio" aria-checked={selected === index} onClick={() => { onSelect(index); close(); }}><Video size={14} /><span>{room.name}</span>{selected === index && <Check size={14} />}</button>)}</div>}
  </div>;
}
