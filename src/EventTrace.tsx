import EventExport from "./EventExport";
import { useEffect, useRef, useState } from "react";
import { clockTime } from "./timecode";
import TraceBadge from "./TraceBadge";
import {
  Check,
  CheckCheck,
  Phone,
  ScanLine,
  Sparkles,
  WifiOff,
  X,
} from "lucide-react";
import type { LookoutState } from "./types";

const clock = (ms: number) =>
  `${Math.floor(ms / 60000)
    .toString()
    .padStart(2, "0")}:${Math.floor((ms / 1000) % 60)
    .toString()
    .padStart(2, "0")}`;

export default function EventTrace({
  state,
  room,
  selected,
  onAction,
  onSeek,
  onReport,
  recordingStartedAt, onHover, onSelect, userId = "Local operator", cameraId = "camera", cameraThumbnail,
}: {
  userId?: string; cameraId?: string; cameraThumbnail?: string;
  recordingStartedAt?: string;
  onHover?: (id: string | null) => void;
  onSelect?: (id: string) => void;
  state: LookoutState;
  room: number;
  selected: string | null;
  onAction: (id: string, action: string) => void;
  onSeek: (seconds: number) => void;
  onReport: (id: string) => void;
}) {
  const [filter, setFilter] = useState("All");
  const root = useRef<HTMLElement>(null);
  useEffect(() => { root.current?.querySelector(".trace-event.expanded")?.scrollIntoView({ block: "nearest", behavior: "instant" }); }, [selected]);
  const statusOf = (status: string) => ["resolved", "dismissed", "closed"].includes(status) ? "Resolved" : status === "acknowledged" ? "In review" : "Open";
  const incidents = state.incidents.filter(i => filter === "All" || statusOf(i.status) === filter);
  const titleOf = (title: string) => title === "Motion near restricted area" ? "Someone near the doorway" : title === "Activity flagged for review" ? "Someone lowered quickly near the play area" : title;
  return (
    <aside className="event-trace" ref={root}>
      <header>
        <div>
          <ScanLine size={15} />
          <h2>Event trace</h2>
        </div>
        <span>{incidents.length.toString().padStart(2, "0")}</span>
      </header>
      <div className="trace-filters" role="group" aria-label="Filter events">{["All", "Open", "Resolved"].map(value => <button key={value} aria-pressed={filter === value} onClick={() => setFilter(value)}>{value}</button>)}</div>
      <div className="trace-scroll">
        {!incidents.length ? (
          <div className="trace-empty">
            <span className="quiet-orbit">
              {room === 2 ? <WifiOff size={18} /> : <Check size={18} />}
            </span>
            <p>{room === 2 ? "Camera not connected" : "Nothing flagged on this day"}</p>
            <span>{room === 2 ? "Waiting for a live feed." : filter === "All" ? "Events will appear here when something needs a look." : "No events match this filter."}</span>
          </div>
        ) : (
          incidents.map((incident) => {
            const expanded = selected === incident.id;
            const startTime = incident.media_time_ms !== undefined && recordingStartedAt
              ? clockTime(recordingStartedAt, incident.media_time_ms / 1000)
              : new Date(typeof incident.opened_at === "number" ? incident.opened_at * 1000 : incident.opened_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
            const thumbnail = incident.evidence_url || cameraThumbnail;
            const attempts =
              state.attempts?.filter((a) => a.incident_id === incident.id) ||
              [];
            return (
              <article
                key={incident.id}
                className={`trace-event ${incident.priority === "critical" ? "critical" : ""} ${expanded ? "expanded" : ""}`}
              >
                <button className="trace-summary" aria-expanded={expanded} aria-controls={`trace-details-${incident.id}`} onClick={() => { onSelect?.(incident.id); if (incident.media_time_ms !== undefined) onSeek(incident.media_time_ms / 1000); }} onMouseEnter={() => onHover?.(incident.id)} onMouseLeave={() => onHover?.(null)} onFocus={() => onHover?.(incident.id)} onBlur={() => onHover?.(null)} onKeyDown={event => {
                  if (!["ArrowDown", "ArrowUp"].includes(event.key)) return;
                  event.preventDefault(); const rows = Array.from(root.current?.querySelectorAll<HTMLButtonElement>(".trace-summary") || []); rows[(rows.indexOf(event.currentTarget) + (event.key === "ArrowDown" ? 1 : -1) + rows.length) % rows.length]?.focus();
                }}>
                  {thumbnail ? <img className="trace-thumbnail" src={thumbnail} alt={`${incident.room} camera screenshot`} /> : <span className="trace-thumbnail" aria-label="Camera screenshot unavailable"><ScanLine size={18} /></span>}
                  <span className="trace-row-content">
                    <span className="trace-thread-heading"><strong>Incident</strong><time>{startTime}</time></span>
                    <span className="trace-thread-description" title={titleOf(incident.title)}>{titleOf(incident.title)}</span>
                  </span>
                </button>
                {expanded && (
                  <div className="trace-detail" id={`trace-details-${incident.id}`}>
                    <span className={`trace-status-word status-${statusOf(incident.status).toLowerCase().replace(" ", "-")}`}><i />{statusOf(incident.status)}{incident.origin === "fixture" && " · Demo"}</span>
                    {incident.assigned_responder && <p>Handled by {incident.assigned_responder}{incident.resolved_at && ` · ${new Date(incident.resolved_at).toLocaleString()}`}</p>}
                    <p>Detection confidence: not supplied</p>
                    {incident.observations.map((observation, index) => <p key={index}>{observation}</p>)}
                    <div className="trace-response-log">
                      {incident.demo_response ? incident.demo_response.map((step, index) => <div className="trace-activity-step" key={index}>
                        <TraceBadge className="trace-time-button" onClick={() => onSeek(step.time_ms / 1000)} aria-label={`Seek to ${clock(step.time_ms)}`}>{clock(step.time_ms)}</TraceBadge>
                        <div>{step.tool && <TraceBadge className="trace-tool-badge">{step.tool === "Phone call" && <Phone size={10} />}{step.tool}</TraceBadge>}<p>{step.description}</p></div>
                      </div>) : <>
                        {incident.media_time_ms !== undefined && <div className="trace-timepoints"><TraceBadge className="trace-time-button" onClick={() => onSeek(incident.media_time_ms! / 1000)}>{clock(incident.media_time_ms)}</TraceBadge>{incident.media_end_time_ms !== undefined && <TraceBadge className="trace-time-button" onClick={() => onSeek(incident.media_end_time_ms! / 1000)}>{clock(incident.media_end_time_ms)}</TraceBadge>}</div>}
                        {attempts.map(attempt => <p key={attempt.id}><TraceBadge className="trace-tool-badge"><Phone size={10} />{attempt.payload?.provider === "cartesia_agent" ? "Agent phone call" : "Phone call"}</TraceBadge> {state.caregivers[attempt.step]?.name || "Caregiver"} · {attempt.status.replaceAll("_", " ")}{attempt.payload?.mode === "simulation" ? " (simulated)" : ""}</p>)}
                        {incident.assigned_responder && <p>{incident.assigned_responder}{incident.acknowledged_via ? ` · ${incident.acknowledged_via} response` : " · assigned responder"}</p>}
                        <p>{incident.status === "resolved" ? "Incident resolved after review." : incident.status === "acknowledged" ? "Caregiver is responding." : incident.status === "dismissed" ? "Dismissed after review." : "Awaiting caregiver response."}</p>
                      </>}
                    </div>
                    {incident.limitations?.map((text) => (
                      <p className="trace-limitation" key={text}>
                        Possible concern only. {text}
                      </p>
                    ))}
                    {incident.second_opinion && (
                      <div className="trace-opinion">
                        <div>
                          <Sparkles size={13} />
                          <strong>Claude second opinion</strong>
                        </div>
                        <span>
                          {
                            {
                              concern_visible: "Concern visible",
                              benign_explanation_likely:
                                "Benign explanation likely",
                              insufficient_view: "Cannot tell from this view",
                            }[incident.second_opinion.assessment]
                          }{" "}
                          · {incident.second_opinion.visibility} view
                        </span>
                        {incident.second_opinion.observations
                          .slice(0, 2)
                          .map((o) => (
                            <p key={o.frame_seq + o.description}>
                              {o.description}
                            </p>
                          ))}
                        {incident.second_opinion.alternative_explanations[0] && (
                          <p>
                            Alternative:{" "}
                            {incident.second_opinion.alternative_explanations[0]}
                          </p>
                        )}
                        <small>
                          Context only. It never delays, cancels, or downgrades
                          the alert. Faces blurred · {incident.second_opinion.model}
                          {incident.second_opinion.cost_usd != null &&
                            ` · $${incident.second_opinion.cost_usd.toFixed(4)}`}
                        </small>
                      </div>
                    )}
                    {incident.primary_due_at && (
                      <div className="trace-call">
                        <div>
                          <Phone size={13} />
                          <strong>Caregiver escalation</strong>
                        </div>
                        <span>
                          {state.session.calls_armed
                            ? "Live calling enabled"
                            : "Simulation · no real call placed"}
                        </span>
                        {[0, 1].map((step) => {
                          const attempt = attempts.find((a) => a.step === step);
                          const due = step
                            ? incident.backup_due_at
                            : incident.primary_due_at;
                          const status =
                            incident.status !== "open"
                              ? incident.status === "acknowledged"
                                ? "Acknowledged"
                                : "Closed"
                              : attempt
                                ? attempt.status.replaceAll("_", " ")
                                : due && due > Date.now() / 1000
                                  ? `Queued · ${Math.ceil(due - Date.now() / 1000)}s`
                                  : "Awaiting dispatch";
                          return (
                            <div className="trace-call-step" key={step}>
                              <span>
                                {state.caregivers[step]?.name ||
                                  (step ? "Backup" : "Primary")}
                              </span>
                              <span>{status}</span>
                            </div>
                          );
                        })}
                      </div>
                    )}
                    {incident.clip_url && (
                      <figure className="trace-clip">
                        <video
                          src={incident.clip_url}
                          controls
                          muted
                          playsInline
                          preload="metadata"
                        />
                        <figcaption>Evidence clip · 5 s before to 5 s after · heads blurred</figcaption>
                      </figure>
                    )}
                    <EventExport incident={incident} cameraId={cameraId} userId={userId} />
                    <div className="trace-actions">
                      {incident.status === "open" && (
                        <button
                          className="button amber-button"
                          onClick={() => onAction(incident.id, "acknowledge")}
                        >
                          <Check size={13} />
                          Acknowledge
                        </button>
                      )}
                      {incident.status === "acknowledged" && (
                        <button
                          className="button"
                          onClick={() => onAction(incident.id, "resolve")}
                        >
                          <CheckCheck size={13} />
                          Resolve incident
                        </button>
                      )}
                      {["open", "acknowledged"].includes(incident.status) && (
                        <button
                          className="icon-button"
                          aria-label="Dismiss after review"
                          onClick={() => onAction(incident.id, "dismiss")}
                        >
                          <X size={14} />
                        </button>
                      )}
                      {!incident.demo_response && <button
                        className="text-button"
                        onClick={() => onReport(incident.id)}
                      >
                        Report
                      </button>}
                    </div>
                  </div>
                )}
              </article>
            );
          })
        )}
      </div>

    </aside>
  );
}
