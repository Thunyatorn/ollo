import { useEffect, useRef, useState } from "react";
import { ChevronDown, Video } from "lucide-react";

export default function CameraPicker({ rooms, selected, onSelect }: {
  rooms: { id: string; name: string }[]; selected: number; onSelect: (index: number) => void;
}) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null), trigger = useRef<HTMLButtonElement>(null);
  const alternatives = rooms.map((room, index) => ({ room, index })).filter(item => item.index !== selected);
  const openFromEnd = useRef(false);
  const options = useRef<(HTMLButtonElement | null)[]>([]);
  useEffect(() => {
    if (!open) return;
    options.current[openFromEnd.current ? alternatives.length - 1 : 0]?.focus();
    const dismiss = (event: PointerEvent) => { if (!root.current?.contains(event.target as Node)) setOpen(false); };
    document.addEventListener("pointerdown", dismiss);
    return () => document.removeEventListener("pointerdown", dismiss);
  }, [open, selected, alternatives.length]);
  const close = () => { setOpen(false); trigger.current?.focus(); };
  return <div ref={root} className={`camera-picker${open ? " is-open" : ""}`} onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false); }} onKeyDown={event => { if (event.key === "Escape") { event.preventDefault(); close(); } }}>
    <button ref={trigger} className="camera-picker-trigger" aria-label={`Select camera: ${rooms[selected].name}`} aria-haspopup="menu" aria-expanded={open} onClick={() => { openFromEnd.current = false; setOpen(!open); }} onKeyDown={event => { if (event.key === "ArrowDown" || event.key === "ArrowUp") { event.preventDefault(); openFromEnd.current = event.key === "ArrowUp"; setOpen(true); } }}>
      <Video size={14} /><span>{rooms[selected].name}</span><small>{rooms[selected].id}</small><ChevronDown className="camera-picker-chevron" size={14} />
    </button>
    {open && <div className="camera-picker-menu" role="menu" aria-label="Cameras" onKeyDown={event => {
      const current = options.current.indexOf(document.activeElement as HTMLButtonElement);
      let next = current;
      if (event.key === "ArrowDown") next = (current + 1) % alternatives.length;
      else if (event.key === "ArrowUp") next = (current - 1 + alternatives.length) % alternatives.length;
      else if (event.key === "Home") next = 0;
      else if (event.key === "End") next = alternatives.length - 1;
      else return;
      event.preventDefault(); options.current[next]?.focus();
    }}>{alternatives.map(({room, index}, optionIndex) => <button key={room.id} ref={element => { options.current[optionIndex] = element; }} role="menuitem" onClick={() => { onSelect(index); close(); }}><Video size={14} /><span>{room.name}</span><small>{room.id}</small></button>)}</div>}
  </div>;
}
