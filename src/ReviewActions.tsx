import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { Info } from "lucide-react";
import { recordAudit, reviewActivity } from "./reviewAudit";

export default function ReviewActions({ cameraId, userId, duration, keptUntil, audioPresent, audioPermitted }: {
  cameraId: string; userId: string; duration: number; keptUntil?: string; audioPresent: boolean; audioPermitted: boolean;
}) {
  const id = useId();
  const trigger = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState({ top: 0, left: 0 });
  const [activityOpen, setActivityOpen] = useState(false);
  const [blurRequested, setBlurRequested] = useState(false);
  useEffect(() => { panel.current?.hidePopover(); setActivityOpen(false); setBlurRequested(false); }, [cameraId]);
  useLayoutEffect(() => {
    if (!open) return;
    const place = () => {
      const anchor = trigger.current?.getBoundingClientRect(); const box = panel.current?.getBoundingClientRect();
      if (!anchor || !box) return;
      setPosition({ left: Math.max(12, Math.min(innerWidth - box.width - 12, anchor.right - box.width)), top: Math.max(12, Math.min(innerHeight - box.height - 12, anchor.top - box.height - 8)) });
    };
    place(); window.addEventListener("resize", place); window.addEventListener("scroll", place, true);
    const resize = new ResizeObserver(place); if (panel.current) resize.observe(panel.current);
    return () => { resize.disconnect(); window.removeEventListener("resize", place); window.removeEventListener("scroll", place, true); };
  }, [open, activityOpen]);
  return <div className="review-actions">
    <button ref={trigger} className="clip-info-trigger" popoverTarget={id} aria-label="Clip information" title="Clip information" aria-expanded={open}><Info size={16} /></button>
    <div ref={panel} id={id} popover="auto" className="clip-details" aria-label="Clip information" style={{ top: position.top, left: position.left }} onToggle={event => setOpen(event.currentTarget.matches(":popover-open"))}>
      <dl className="clip-metadata">
        <div><dt>Camera</dt><dd>{cameraId}</dd></div>
        <div><dt>Audio</dt><dd>{audioPresent ? audioPermitted ? "Muted" : "Permission needed" : "None"}</dd></div>
        <div><dt>Kept until</dt><dd>{keptUntil ? new Date(keptUntil).toLocaleDateString() : "Not supplied"}</dd></div>
        <div><dt>Redaction</dt><dd><label className="clip-redaction"><input type="checkbox" checked={blurRequested} onChange={event => setBlurRequested(event.target.checked)} />Blur others</label></dd></div>
        <div><dt></dt><dd>Preview only · not applied</dd></div>
        <div><dt>Activity</dt><dd><button className="clip-activity-toggle" aria-expanded={activityOpen} onClick={() => { recordAudit({ action: "view_activity", userId, cameraId, range: { start: 0, end: duration } }); setActivityOpen(!activityOpen); }}>{activityOpen ? "Hide session" : "View session"}</button></dd></div>
      </dl>
      {activityOpen && <div className="clip-activity"><p>This session only</p>{reviewActivity(cameraId).map((entry, i) => <div key={i}><span>{entry.userId}</span><span>{entry.action.replaceAll("_", " ")} · {new Date(entry.at).toLocaleTimeString()}</span></div>)}</div>}

    </div>
  </div>;
}
