import {
  Check,
  CheckCheck,
  ChevronDown,
  Circle,
  Phone,
  ScanLine,
  Sparkles,
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
  onSelect,
  onAction,
  onSeek,
  onReport,
}: {
  state: LookoutState;
  room: number;
  selected: string | null;
  onSelect: (id: string | null) => void;
  onAction: (id: string, action: string) => void;
  onSeek: (seconds: number) => void;
  onReport: (id: string) => void;
}) {
  const incidents = room === 0 ? state.incidents : [];
  return (
    <aside className="event-trace">
      <header>
        <div>
          <ScanLine size={15} />
          <h2>Event trace</h2>
        </div>
        <span>{incidents.length.toString().padStart(2, "0")}</span>
      </header>
      <div className="trace-scroll">
        {!incidents.length ? (
          <div className="trace-empty">
            <span className="quiet-orbit">
              <Check size={18} />
            </span>
            <p>Things are chilling</p>
            <span>Recorded events will appear here.</span>
          </div>
        ) : (
          incidents.map((incident) => {
            const expanded =
              selected === incident.id ||
              (selected === null &&
                (incident.status === "open" ||
                  incident.status === "acknowledged"));
            const attempts =
              state.attempts?.filter((a) => a.incident_id === incident.id) ||
              [];
            return (
              <article
                key={incident.id}
                className={`trace-event ${incident.priority === "critical" ? "critical" : ""} ${expanded ? "expanded" : ""}`}
              >
                <button
                  className="trace-summary"
                  onClick={() => onSelect(expanded ? "collapsed" : incident.id)}
                  aria-expanded={expanded}
                >
                  <span className="trace-node">
                    <Circle size={7} fill="currentColor" />
                  </span>
                  <div>
                    <span className="trace-meta">
                      <time>
                        {incident.media_time_ms === undefined
                          ? "EVENT"
                          : clock(incident.media_time_ms)}
                      </time>
                      <span>
                        {incident.origin === "fixture"
                          ? "DEMO"
                          : incident.priority.toUpperCase()}
                      </span>
                    </span>
                    <h3>{incident.title}</h3>
                    <span className={`trace-status ${incident.status}`}>
                      {incident.status === "open"
                        ? "Needs review"
                        : incident.status}
                    </span>
                    {incident.assigned_responder &&
                      (incident.status === "acknowledged" ||
                        incident.status === "resolved") && (
                        <span className="trace-owner">
                          Handled by {incident.assigned_responder}
                          {incident.acknowledged_via &&
                            ` via ${incident.acknowledged_via}`}
                        </span>
                      )}
                  </div>
                  <ChevronDown size={13} />
                </button>
                {expanded && (
                  <div className="trace-detail">
                    <p>{incident.observations[0]}</p>
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
                      {incident.media_time_ms !== undefined && (
                        <button
                          className="text-button"
                          onClick={() => onSeek(incident.media_time_ms! / 1000)}
                        >
                          Jump to moment
                        </button>
                      )}
                      <button
                        className="text-button"
                        onClick={() => onReport(incident.id)}
                      >
                        Report
                      </button>
                    </div>
                  </div>
                )}
              </article>
            );
          })
        )}
      </div>
      <footer>
        <span className="status-dot" />
        {room ? "Camera not connected" : "This session"}
        <span>
          {state.session.calls_armed ? "Calls armed" : "Calls simulated"}
        </span>
      </footer>
    </aside>
  );
}
