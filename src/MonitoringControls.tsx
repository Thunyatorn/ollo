import { useState } from "react";
import { CalendarDays, ChevronLeft, ChevronRight, Grid2X2, PanelLeft, Square, Radio } from "lucide-react";

export type CameraLayout = "single" | "grid" | "focus";
export const dateKey = (date: Date) => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;

export default function MonitoringControls({ date, onDate, layout, onLayout, eventDates }: {
  date: string | null; onDate: (date: string | null) => void;
  layout: CameraLayout; onLayout: (layout: CameraLayout) => void; eventDates: Set<string>;
}) {
  const [month, setMonth] = useState(() => new Date(new Date().getFullYear(), new Date().getMonth(), 1));
  const today = dateKey(new Date());
  const count = new Date(month.getFullYear(), month.getMonth() + 1, 0).getDate();
  const layouts = [{ id: "single", label: "Single", Icon: Square }, { id: "grid", label: "Grid", Icon: Grid2X2 }, { id: "focus", label: "Focus", Icon: PanelLeft }] as const;
  return <div className="monitor-controls">
    <div className="monitor-control-actions">
      <button className={`live-toggle ${date === null ? "active" : ""}`} onClick={() => onDate(null)} aria-pressed={date === null}><Radio size={13} />Live</button>
      <details className="date-picker" onKeyDown={e => { if (e.key === "Escape") { e.currentTarget.removeAttribute("open"); e.currentTarget.querySelector("summary")?.focus(); } }}>
        <summary><CalendarDays size={14} />{date ? new Date(`${date}T12:00:00`).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }) : "Select date"}</summary>
        <div className="calendar-popover">
          <div className="calendar-heading"><button aria-label="Previous month" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() - 1, 1))}><ChevronLeft size={16} /></button><strong aria-live="polite">{month.toLocaleDateString("en-US", { month: "long", year: "numeric" })}</strong><button aria-label="Next month" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() + 1, 1))}><ChevronRight size={16} /></button></div>
          <div className="calendar-days">
            {["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"].map(day => <span key={day}>{day}</span>)}
            {Array.from({ length: month.getDay() }, (_, i) => <span key={`blank-${i}`} />)}
            {Array.from({ length: count }, (_, i) => {
              const key = dateKey(new Date(month.getFullYear(), month.getMonth(), i + 1));
              return <button key={key} disabled={key > today} className={`${date === key ? "selected" : ""} ${today === key ? "today" : ""}`} aria-label={`${key}${eventDates.has(key) ? ", has incidents" : ""}`} aria-pressed={date === key} onClick={e => { onDate(key); e.currentTarget.closest("details")?.removeAttribute("open"); }}>{i + 1}{eventDates.has(key) && <i />}</button>;
            })}
          </div>
          <div className="calendar-footer"><span><i />Incidents recorded</span><button onClick={e => { setMonth(new Date(new Date().getFullYear(), new Date().getMonth(), 1)); onDate(today); e.currentTarget.closest("details")?.removeAttribute("open"); }}>Today</button></div>
        </div>
      </details>
      <div className="layout-switch" role="group" aria-label="Camera layout">{layouts.map(({ id, label, Icon }) => <button key={id} aria-label={`${label} view`} aria-pressed={layout === id} className={layout === id ? "active" : ""} onClick={() => onLayout(id)}><Icon size={14} /><span>{label}</span></button>)}</div>
    </div>
  </div>;
}
