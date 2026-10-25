import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { CalendarDays, ChevronLeft, ChevronRight, Grid2X2, PanelLeft, Square } from "lucide-react";

export type CameraLayout = "single" | "grid" | "focus";
export const dateKey = (date: Date) => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;

export default function MonitoringControls({ date, onDate, eventDates, footageDates = new Set(), openIncidentDates = new Set(), compact = false }: {
  compact?: boolean;
  date: string | null; onDate: (date: string | null) => void;
  layout?: CameraLayout; onLayout?: (layout: CameraLayout) => void; eventDates: Set<string>; footageDates?: Set<string>; openIncidentDates?: Set<string>;
}) {
  const [month, setMonth] = useState(() => new Date(new Date().getFullYear(), new Date().getMonth(), 1));
  const datePicker = useRef<HTMLDetailsElement>(null);
  const calendar = useRef<HTMLDivElement>(null);
  const [calendarOpen, setCalendarOpen] = useState(false);
  const [calendarPosition, setCalendarPosition] = useState({ top: 0, left: 0 });
  const closeCalendar = () => { datePicker.current?.removeAttribute("open"); setCalendarOpen(false); };
  useLayoutEffect(() => {
    if (!calendarOpen) return;
    const place = () => {
      const trigger = datePicker.current?.getBoundingClientRect();
      const panel = calendar.current?.getBoundingClientRect();
      if (!trigger || !panel) return;
      const below = window.innerHeight - trigger.bottom - 8;
      const top = below >= panel.height ? trigger.bottom + 8 : Math.max(8, trigger.top - panel.height - 8);
      setCalendarPosition({ top: Math.min(top, Math.max(8, window.innerHeight - panel.height - 8)), left: Math.max(8, Math.min(trigger.right - panel.width, window.innerWidth - panel.width - 8)) });
    };
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => { window.removeEventListener("resize", place); window.removeEventListener("scroll", place, true); };
  }, [calendarOpen, month]);
  useEffect(() => {
    if (!calendarOpen) return;
    const dismiss = (event: PointerEvent) => { if (!datePicker.current?.contains(event.target as Node) && !calendar.current?.contains(event.target as Node)) closeCalendar(); };
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") { closeCalendar(); datePicker.current?.querySelector("summary")?.focus(); } };
    document.addEventListener("pointerdown", dismiss); document.addEventListener("keydown", escape);
    return () => { document.removeEventListener("pointerdown", dismiss); document.removeEventListener("keydown", escape); };
  }, [calendarOpen]);
  const today = dateKey(new Date());
  const count = new Date(month.getFullYear(), month.getMonth() + 1, 0).getDate();
  return <div className="monitor-controls">
    <div className="monitor-control-actions">
      <details ref={datePicker} onToggle={event => setCalendarOpen(event.currentTarget.open)} className="date-picker" onKeyDown={e => { if (e.key === "Escape") { e.currentTarget.removeAttribute("open"); e.currentTarget.querySelector("summary")?.focus(); } }}>
        <summary aria-label="Choose date"><span>{new Date(`${date || today}T12:00:00`).toLocaleDateString("en-US", { month: compact ? "short" : "long", day: "numeric", ...(compact ? {} : { year: "numeric" as const }) })}</span><CalendarDays size={15} /></summary>
        {calendarOpen && createPortal(<div ref={calendar} className="calendar-popover calendar-portal" role="dialog" aria-label="Choose date" style={{ top: calendarPosition.top, left: calendarPosition.left }}>
          <div className="calendar-heading"><button aria-label="Previous month" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() - 1, 1))}><ChevronLeft size={16} /></button><strong aria-live="polite">{month.toLocaleDateString("en-US", { month: "long", year: "numeric" })}</strong><button aria-label="Next month" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() + 1, 1))}><ChevronRight size={16} /></button></div>
          <div className="calendar-days">
            {["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"].map(day => <span key={day}>{day}</span>)}
            {Array.from({ length: month.getDay() }, (_, i) => <span key={`blank-${i}`} />)}
            {Array.from({ length: count }, (_, i) => {
              const key = dateKey(new Date(month.getFullYear(), month.getMonth(), i + 1));
              return <button key={key} disabled={key > today} className={`${openIncidentDates.has(key) ? "has-open-incidents" : ""} ${footageDates.has(key) ? "has-footage" : ""} ${date === key ? "selected" : ""} ${today === key ? "today" : ""}`} aria-label={`${key}${footageDates.has(key) ? ", footage available" : ""}${openIncidentDates.has(key) ? ", open incidents" : eventDates.has(key) ? ", has incidents" : ""}`} aria-pressed={date === key} onClick={() => { onDate(key); closeCalendar(); }}>{i + 1}</button>;
            })}
          </div>
          <div className="calendar-footer"><button onClick={() => { setMonth(new Date(new Date().getFullYear(), new Date().getMonth(), 1)); onDate(today); closeCalendar(); }}>Today</button></div>
        </div>, document.body)}
      </details>

    </div>
  </div>;
}

export function CameraViewControls({ layout, onLayout }: { layout: CameraLayout; onLayout: (layout: CameraLayout) => void }) {
  const layouts = [{ id: "single", label: "Single", Icon: Square }, { id: "grid", label: "Grid", Icon: Grid2X2 }, { id: "focus", label: "Focus", Icon: PanelLeft }] as const;
  return (<div className="view-settings"><span className="view-settings-label">View</span><div className="layout-switch" role="group" aria-label="Camera layout">{layouts.map(({ id, label, Icon }) => <button key={id} aria-label={`${label} view`} aria-pressed={layout === id} className={layout === id ? "active" : ""} onClick={() => onLayout(id)}><Icon size={14} /><span>{label}</span></button>)}</div></div>);
}
