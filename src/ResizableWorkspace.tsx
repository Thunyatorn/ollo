import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";

const preference = "nestwatch-panel-width";
export default function ResizableWorkspace({ children }: { children: ReactNode }) {
  const root = useRef<HTMLElement>(null);
  const [width, setWidth] = useState(() => {
    try { const saved = Number(localStorage.getItem(preference)); return saved >= 240 && saved <= 560 ? saved : 320; } catch { return 320; }
  });
  const [dragging, setDragging] = useState(false);
  const limit = () => Math.max(240, Math.min(560, (root.current?.clientWidth || 1200) * .5, (root.current?.clientWidth || 1200) - 360));
  const resize = (next: number) => setWidth(Math.round(Math.max(240, Math.min(limit(), next))));
  const save = (value: number) => { try { localStorage.setItem(preference, String(value)); } catch { /* The divider still works without browser storage. */ } };
  useEffect(() => {
    if (!root.current) return;
    const observer = new ResizeObserver(() => {
      if ((root.current?.clientWidth || 0) > 760) setWidth(previous => Math.max(240, Math.min(limit(), previous)));
    });
    observer.observe(root.current);
    return () => observer.disconnect();
  }, []);
  return <section className="monitor-grid resizable-workspace" ref={root} style={{ "--monitor-panel-width": `${width}px` } as CSSProperties}>
    {children}
    <div className="workspace-divider" role="separator" aria-label="Resize camera and event panels" aria-orientation="vertical" aria-valuemin={240} aria-valuemax={Math.round(limit())} aria-valuenow={width} tabIndex={0} data-dragging={dragging} title="Drag to resize · double-click to reset"
      onPointerDown={event => { if (event.button !== 0) return; event.preventDefault(); event.currentTarget.setPointerCapture(event.pointerId); setDragging(true); }}
      onPointerMove={event => { if (!event.currentTarget.hasPointerCapture(event.pointerId) || !root.current) return; const bounds = root.current.getBoundingClientRect(); resize(bounds.right - event.clientX - 10); }}
      onPointerUp={event => { if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId); setDragging(false); save(width); }}
      onLostPointerCapture={() => setDragging(false)}
      onDoubleClick={() => { resize(320); save(320); }}
      onKeyDown={event => {
        if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
        event.preventDefault();
        const next = event.key === "Home" ? 240 : event.key === "End" ? limit() : width + (event.key === "ArrowLeft" ? 1 : -1) * (event.shiftKey ? 48 : 16);
        resize(next); save(Math.max(240, Math.min(limit(), next)));
      }}
    />
  </section>;
}
