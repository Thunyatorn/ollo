import { useRef } from "react";
import { Minus, Plus } from "lucide-react";

export default function TimelineOverview({ start, span, onChange }: {
  start: number; span: number; onChange: (start: number, span: number) => void;
}) {
  const drag = useRef<{ x: number; start: number; span: number; mode: string } | null>(null);
  const clamp = (value: number, min: number, max: number) => Math.max(min, Math.min(max, value));
  const zoom = (factor: number) => { const next = clamp(span * factor, .05, 1); onChange(clamp(start + (span - next) / 2, 0, 1 - next), next); };
  return <div className="timeline-overview-row">
    <div className="timeline-overview" aria-label="Timeline overview" onPointerDown={event => {
      if (event.button !== 0) return;
      event.preventDefault(); event.currentTarget.setPointerCapture(event.pointerId);
      const target = event.target as HTMLElement;
      const mode = target.dataset.handle || "pan";
      const bounds = event.currentTarget.getBoundingClientRect();
      const next = target.closest(".timeline-overview-window") ? start : clamp((event.clientX - bounds.left) / bounds.width - span / 2, 0, 1 - span);
      onChange(next, span); drag.current = { x: event.clientX, start: next, span, mode };
    }} onPointerMove={event => {
      const current = drag.current;
      if (!current || !event.currentTarget.hasPointerCapture(event.pointerId)) return;
      const delta = (event.clientX - current.x) / event.currentTarget.clientWidth;
      if (current.mode === "start") { const next = clamp(current.start + delta, 0, current.start + current.span - .05); onChange(next, current.start + current.span - next); }
      else if (current.mode === "end") onChange(current.start, clamp(current.span + delta, .05, 1 - current.start));
      else onChange(clamp(current.start + delta, 0, 1 - current.span), current.span);
    }} onPointerUp={event => { drag.current = null; if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId); }} onLostPointerCapture={() => { drag.current = null; }}>
      <div className="timeline-overview-window" style={{ left: `${start * 100}%`, width: `${span * 100}%` }}>
        <button data-handle="start" className="overview-handle" aria-label="Visible timeline start" onKeyDown={event => {
          if (!["ArrowLeft", "ArrowRight", "Home"].includes(event.key)) return;
          event.preventDefault(); const next = event.key === "Home" ? 0 : clamp(start + (event.key === "ArrowLeft" ? -.01 : .01), 0, start + span - .05); onChange(next, start + span - next);
        }} />
        <button className="overview-pan" aria-label="Pan timeline" onKeyDown={event => {
          if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
          event.preventDefault(); onChange(event.key === "Home" ? 0 : event.key === "End" ? 1 - span : clamp(start + (event.key === "ArrowLeft" ? -span / 10 : span / 10), 0, 1 - span), span);
        }} />
        <button data-handle="end" className="overview-handle" aria-label="Visible timeline end" onKeyDown={event => {
          if (!["ArrowLeft", "ArrowRight", "End"].includes(event.key)) return;
          event.preventDefault(); onChange(start, event.key === "End" ? 1 - start : clamp(span + (event.key === "ArrowLeft" ? -.01 : .01), .05, 1 - start));
        }} />
      </div>
    </div>
    <button className="timeline-zoom" aria-label="Zoom out timeline" disabled={span >= 1} onClick={() => zoom(2)}><Minus size={12} /></button>
    <button className="timeline-zoom" aria-label="Zoom in timeline" disabled={span <= .05} onClick={() => zoom(.5)}><Plus size={12} /></button>
  </div>;
}
