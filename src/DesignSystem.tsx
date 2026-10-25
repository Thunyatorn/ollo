import Navbar from "./Navbar";
import Brand from "./Brand";
import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  Activity,
  AudioLines,
  ArrowLeft,
  ArrowUpRight,
  Bell,
  Check,
  ChevronDown,
  Clock3,
  Download,
  Grid2X2,
  MessageSquare,
  Pause,
  Play,
  Plus,
  Settings2,
  Shield,
  Upload,
  Video,
  Volume2,
  X,
} from "lucide-react";
import "./design-system.css";
import MonitoringControls, { type CameraLayout } from "./MonitoringControls";
import EditorTimeline from "./EditorTimeline";

const sections = [
  "Overview",
  "Color",
  "Materials",
  "Typography",
  "Spacing & shape",
  "Buttons",
  "Inputs",
  "Status & feedback",
  "Navigation",
  "Monitoring",
  "Cards & activity",
  "Overlays",
];
const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, "-");
type Note = { section: string; text: string; created: string };
const colors = [
  ["Canvas", "#101113"],
  ["Sidebar", "#111214"],
  ["Surface", "#17181b"],
  ["Raised", "#24262a"],
  ["Border", "#36393f"],
  ["Primary text", "#edf0f2"],
  ["Body text", "#d1d5db"],
  ["Muted text", "#7a828c"],
  ["Primary blue", "#9bd7ff"],
  ["Blue edge", "#547b95"],
  ["Raised surface", "#1b2026"],
  ["Success", "#aebf9e"],
  ["Amber", "#e4be86"],
  ["Danger", "#df8c83"],
];
function MonitoringPlayback() {
  const [playing, setPlaying] = useState(false);
  const [position, setPosition] = useState(35);
  const previewVideo = useRef<HTMLVideoElement | null>(null);
  useEffect(() => {
    if (!playing) return;
    let previous = performance.now();
    const timer = setInterval(() => {
      const now = performance.now();
      const elapsed = (now - previous) / 1000;
      previous = now;
      setPosition(p => (p + elapsed) % 120);
    }, 100);
    return () => clearInterval(timer);
  }, [playing]);
  return <><div className="ds-player"><button className="icon-button" aria-label={playing ? "Pause preview" : "Play preview"} onClick={() => setPlaying(!playing)}>{playing ? <Pause size={16} /> : <Play size={16} />}</button><code>{String(Math.floor(position / 60)).padStart(2, "0")}:{String(Math.floor(position % 60)).padStart(2, "0")} / 02:00</code></div><div className="ds-editor-preview"><EditorTimeline camera="Toddler room · CAM 01" room={0} duration={120} position={position} playing={playing} demo peaks={null} video={previewVideo} markers={[{ id: "preview-incident", time: 28, endTime: 46, title: "Motion near restricted area", demo: true }]} onSeek={seconds => { setPosition(seconds); setPlaying(false); }} /></div></>;
}

export default function DesignSystem() {
  const [layout, setLayout] = useState<CameraLayout>("single");
  const [date, setDate] = useState<string | null>(null);
  const [notes, setNotes] = useState<Note[]>(() => {
    try {
      return JSON.parse(localStorage.getItem("ollo-design-notes") || "[]");
    } catch {
      return [];
    }
  });
  const [target, setTarget] = useState("Overview"),
    [draft, setDraft] = useState(""),
    [notice, setNotice] = useState(""),
    [enabled, setEnabled] = useState(true),
    [tab, setTab] = useState("Monitor"),
    [modal, setModal] = useState(false);
  function save() {
    if (!draft.trim()) return;
    const next = [
      ...notes,
      {
        section: target,
        text: draft.trim(),
        created: new Date().toISOString(),
      },
    ];
    try {
      localStorage.setItem("ollo-design-notes", JSON.stringify(next));
      setNotes(next);
      setDraft("");
      setNotice("Comment saved in this browser.");
    } catch {
      setNotice(
        "Browser storage is unavailable. Copy your comment before leaving.",
      );
    }
  }
  function exportNotes() {
    const url = URL.createObjectURL(
      new Blob(
        [
          notes
            .map((n) => `## ${n.section}\n${n.text}\n\n${n.created}`)
            .join("\n\n") || "No comments yet.",
        ],
        { type: "text/markdown" },
      ),
    );
    const a = document.createElement("a");
    a.href = url;
    a.download = "ollo-design-feedback.md";
    a.click();
    URL.revokeObjectURL(url);
  }
  function Section({
    name,
    children,
    description,
  }: {
    name: string;
    children: ReactNode;
    description: string;
  }) {
    return (
      <section id={slug(name)} className="ds-section">
        <div className="ds-section-heading">
          <div>
            <span className="eyebrow">
              {String(sections.indexOf(name)).padStart(2, "0")} / SYSTEM
            </span>
            <h2>{name}</h2>
            <p>{description}</p>
          </div>
          <button
            className="button"
            onClick={() => {
              setTarget(name);
              document.getElementById("ds-comment")?.focus();
            }}
          >
            <MessageSquare size={13} /> Comment
            {notes.filter((n) => n.section === name).length
              ? ` (${notes.filter((n) => n.section === name).length})`
              : ""}
          </button>
        </div>
        {children}
      </section>
    );
  }
  return (
    <div className="ds-page">
      <Navbar />
      <aside className="ds-nav">
        <a href="/" className="ds-logo">
          <Brand /><span>DESIGN SYSTEM</span>
        </a>
        <p className="ds-muted">A shared language for video intelligence.</p>
        <nav aria-label="Design system sections">
          {sections.map((name, i) => (
            <a key={name} href={`#${slug(name)}`}>
              <span>{String(i).padStart(2, "0")}</span>
              {name}
            </a>
          ))}
        </nav>
        <a className="button" href="/">
          <ArrowLeft size={13} /> Back to app
        </a>
        <p className="ds-muted">
          Current product styles
          <br />
          Recorder materials · 02
        </p>
      </aside>
      <main className="ds-main">
        <header id="overview" className="ds-hero">
          <div className="ds-row">
            <span className="pill subtle">OLLO / INTERFACE LIBRARY</span>
            <span className="ds-muted">Built from the current app</span>
          </div>
          <h1>A clearer view.</h1>
          <p>
            Charcoal surfaces, precise controls, and a restrained blue signal.
            Recorder-inspired textures bring depth to the interface without competing with the camera feed.
          </p>
          <div className="ds-row">
            <a href="#color" className="button light">
              Explore the system <ArrowUpRight size={14} />
            </a>
            <button className="button" onClick={exportNotes}>
              <Download size={14} /> Export comments ({notes.length})
            </button>
          </div>
          <div className="ds-stats">
            <div>
              <strong>{colors.length}</strong>
              <span>Color tokens</span>
            </div>
            <div>
              <strong>{sections.length - 1}</strong>
              <span>Component sections</span>
            </div>
            <div>
              <strong>Aa</strong>
              <span>System sans serif</span>
            </div>
            <div>
              <strong>02</strong>
              <span>Living reference</span>
            </div>
          </div>
        </header>
        <Section
          name="Color"
          description="Quiet neutrals create hierarchy. Light blue highlights actions; green confirms and amber calls for attention."
        >
          <div className="ds-swatches">
            {colors.map(([name, color]) => (
              <div key={name} className="ds-swatch">
                <div style={{ background: color }} />
                <strong>{name}</strong>
                <code>{color}</code>
              </div>
            ))}
          </div>
        </Section>
        <Section name="Materials" description="Borrow the precision of a CCTV recorder. Keep large surfaces neutral; use blue at edges, selected controls, and the timeline.">
          <div className="ds-material-grid">
            {[
              { name: "Brushed header", style: "brushed", token: "--material-header · --texture-lines", text: "Fine horizontal texture and a soft top highlight. Camera toolbars and panel headers." },
              { name: "Recessed control", style: "inset", token: "--material-inset · --bevel-inset", text: "Dark inset surfaces keep controls grounded. Layout switches and scrubber wells." },
              { name: "Signal blue", style: "signal", token: "--material-signal · --primary", text: "A gentle blue gradient for the timeline and primary actions. Keep it out of large backgrounds." },
              { name: "Precision edge", style: "edge", token: "--edge-blue · --bevel-raised", text: "A thin blue-gray border and a one-pixel highlight. Selected panels and floating controls." },
            ].map(material => <article className="ds-material-card" key={material.name}><div className={`ds-material-sample material-${material.style}`}><span>CAM 01</span><AudioLines size={22} /></div><div><h3>{material.name}</h3><code>{material.token}</code><p>{material.text}</p></div></article>)}
          </div>
          <p className="ds-material-rule">Charcoal is the canvas. Blue shows interaction and signal. Yellow marks incidents; green and red keep their status meanings. Texture stays on interface surfaces, never over video.</p>
        </Section>
        <Section
          name="Typography"
          description="Inter when available, with native system fallbacks. Compact, readable, and restrained."
        >
          <div className="ds-panel">
            {[
              ["Page heading", "25px / 500", "A clearer view of care."],
              ["Section heading", "18px / 500", "Everything in its place."],
              ["Body", "13px / 400", "Stay close to the moments that matter."],
              ["Control", "10px / 400", "View camera settings"],
              ["Eyebrow", "8px / 600", "LIVE MONITORING"],
            ].map(([name, spec, example], i) => (
              <div className="ds-type" key={name}>
                <div>
                  <strong>{name}</strong>
                  <code>{spec}</code>
                </div>
                <span
                  style={{
                    fontSize: [25, 18, 13, 10, 8][i],
                    fontWeight: i === 4 ? 600 : i < 2 ? 500 : 400,
                    letterSpacing: i === 4 ? "1.8px" : undefined,
                  }}
                >
                  {example}
                </span>
              </div>
            ))}
          </div>
        </Section>
        <Section
          name="Spacing & shape"
          description="Dense controls, generous section spacing, and subtle corners."
        >
          <div className="ds-two">
            <div className="ds-panel ds-stack">
              {[4, 8, 12, 16, 24, 32].map((n) => (
                <div className="ds-space" key={n}>
                  <code>{n}px</code>
                  <i style={{ width: n * 5 }} />
                </div>
              ))}
            </div>
            <div className="ds-panel ds-row">
              {[4, 5, 6].map((n) => (
                <div className="ds-radius" key={n} style={{ borderRadius: n }}>
                  {n}px<small>radius</small>
                </div>
              ))}
              <div className="ds-radius" style={{ borderRadius: "50%" }}>
                50%<small>avatar</small>
              </div>
            </div>
          </div>
        </Section>
        <Section
          name="Buttons"
          description="Primary, secondary, attention, icon-only, and disabled states. Hover or focus to inspect."
        >
          <div className="ds-panel ds-stack">
            <div className="ds-row">
              <button
                className="button light"
                onClick={() => setNotice("Primary action previewed.")}
              >
                <Plus size={13} /> Add camera
              </button>
              <button
                className="button primary"
                onClick={() =>
                  setNotice("Response acknowledged in this preview.")
                }
              >
                <Check size={13} /> Respond
              </button>
              <button
                className="button"
                onClick={() => setNotice("Secondary action previewed.")}
              >
                <Upload size={13} /> Upload video
              </button>
              <button
                className="button amber-button"
                onClick={() => setNotice("Alert action previewed.")}
              >
                <Bell size={13} /> Review alert
              </button>
              <button className="button" disabled>
                Unavailable
              </button>
            </div>
            <div className="ds-row">
              {[Play, Pause, Volume2, Settings2, Plus, X].map((Icon, i) => (
                <button
                  key={i}
                  aria-label={
                    ["Play", "Pause", "Volume", "Settings", "Add", "Close"][i]
                  }
                  className="icon-button"
                  onClick={() =>
                    setNotice(
                      `${["Play", "Pause", "Volume", "Settings", "Add", "Close"][i]} previewed.`,
                    )
                  }
                >
                  <Icon size={16} />
                </button>
              ))}
            </div>
          </div>
        </Section>
        <Section
          name="Inputs"
          description="Labeled fields, selection, validation, and an interactive monitoring switch."
        >
          <div className="ds-panel ds-two">
            <div className="ds-stack">
              <label className="ds-field">
                Room name
                <input defaultValue="Toddler room" />
              </label>
              <label className="ds-field">
                Camera source
                <select defaultValue="demo">
                  <option value="demo">Demo camera</option>
                  <option>Uploaded video</option>
                  <option>Server camera</option>
                </select>
              </label>
              <label className="ds-field">
                Unavailable field
                <input disabled placeholder="Connect a camera first" />
              </label>
            </div>
            <div className="ds-stack">
              <label className="ds-field">
                Notification email
                <input
                  type="email"
                  aria-invalid="true"
                  aria-describedby="email-hint"
                  defaultValue="maya@"
                />
                <small id="email-hint" className="ds-error">
                  Enter a complete email address.
                </small>
              </label>
              <label className="ds-check">
                <input type="checkbox" defaultChecked /> Notify backup caregiver
              </label>
              <div className="ds-row">
                Monitoring
                <button
                  role="switch"
                  aria-checked={enabled}
                  aria-label="Monitoring"
                  onClick={() => setEnabled(!enabled)}
                  className={`toggle ${enabled ? "on" : ""}`}
                >
                  <i />
                </button>
                <span className="ds-muted">{enabled ? "On" : "Off"}</span>
              </div>
            </div>
          </div>
        </Section>
        <Section
          name="Status & feedback"
          description="State is communicated with words and symbols as well as color."
        >
          <div className="ds-panel ds-stack">
            <div className="ds-row">
              <span className="pill subtle">Monitoring active</span>
              <span className="pill amber">Needs attention</span>
              <span className="pill">Demo workspace</span>
              <span className="pill">Offline</span>
            </div>
            <div className="ds-row">
              <span className="status-dot" /> Connected{" "}
              <span className="status-dot inactive" /> Disconnected{" "}
              <span className="status-dot red" /> Recording
            </div>
            <div className="ds-banner">
              <Shield size={17} />
              <span>
                <strong>All clear</strong>
                <br />
                No open incidents in this room.
              </span>
            </div>
            <div className="ds-banner ds-warning">
              <Bell size={17} />
              <span>
                <strong>Caregiver attention needed</strong>
                <br />
                Review the latest activity before responding.
              </span>
            </div>
          </div>
        </Section>
        <Section
          name="Navigation"
          description="Selected navigation, breadcrumbs, camera selection, and compact counters."
        >
          <div className="ds-two">
            <div className="ds-panel">
              <nav aria-label="Navigation examples">
                {["Monitor", "Incidents", "Settings"].map((name, i) => (
                  <button
                    key={name}
                    className={tab === name ? "selected" : ""}
                    onClick={() => setTab(name)}
                  >
                    {i === 0 ? (
                      <Grid2X2 size={15} />
                    ) : i === 1 ? (
                      <Bell size={15} />
                    ) : (
                      <Settings2 size={15} />
                    )}
                    {name}
                    {i === 1 && <span className="nav-count">2</span>}
                  </button>
                ))}
              </nav>
              <p className="ds-muted">Selected: {tab}</p>
            </div>
            <div className="ds-panel ds-stack">
              <div className="breadcrumb">
                Workspace / <span>Toddler room</span>
              </div>
              <button
                className="room selected"
                onClick={() => setNotice("Camera selection previewed.")}
              >
                <span className="status-dot" />
                <span>
                  Toddler room<span className="sub">CAM 01 · Live</span>
                </span>
                <ChevronDown size={13} />
              </button>
            </div>
          </div>
        </Section>
        <Section
          name="Monitoring"
          description="Illustrative camera media, tracking, live status, and playback controls."
        >
          <div className="camera-card">
            <div className="camera-toolbar">
              <div>
                <Video size={14} />
                <strong>Toddler room</strong>
                <span className="camera-id">CAM 01</span>
              </div>
              <span className="pill">Illustration · No live analysis</span>
            </div>
            <div className="ds-camera">
              <img
                src="/playroom-cctv.png"
                alt="Illustrative playroom camera scene"
              />
              <div className="ds-track">PERSON 01 · DEMO</div>
              <span className="ds-camera-label">
                <span className="status-dot" /> Demo feed
              </span>
            </div>
            <MonitoringPlayback />
          </div>
          <div className="ds-control-preview monitor-side-panel"><MonitoringControls date={date} onDate={setDate} layout={layout} onLayout={setLayout} eventDates={new Set()} /></div>
        </Section>
        <Section
          name="Cards & activity"
          description="Caregiver identity, incident hierarchy, recent activity, and empty states."
        >
          <div className="ds-two">
            <div className="ds-panel ds-stack">
              <div className="ds-row">
                <div className="caregiver-avatar">
                  MC
                  <span />
                </div>
                <div>
                  <strong>Maya Chen</strong>
                  <p className="ds-muted">Primary caregiver · Available</p>
                </div>
                <span className="pill subtle">On duty</span>
              </div>
              <div className="ds-banner ds-warning">
                <Bell size={18} />
                <div>
                  <strong>Movement near a zone</strong>
                  <p>Illustrative incident · Toddler room</p>
                  <button className="button" onClick={() => setModal(true)}>
                    Review incident <ArrowUpRight size={12} />
                  </button>
                </div>
              </div>
            </div>
            <div className="ds-panel">
              <div className="activity-event">
                <span className="event-icon">
                  <Check size={12} />
                </span>
                <div>
                  <p>Monitoring started</p>
                  <time>10:24:00</time>
                </div>
              </div>
              <div className="activity-event">
                <span className="event-icon event-alert">
                  <Bell size={12} />
                </span>
                <div>
                  <p>Caregiver notified</p>
                  <time>10:24:08</time>
                </div>
              </div>
              <div className="ds-empty">
                <Activity size={22} />
                <strong>No more activity</strong>
                <span>New events will appear here.</span>
              </div>
            </div>
          </div>
        </Section>
        <Section
          name="Overlays"
          description="Dialogs request a focused decision. Toasts provide brief confirmation."
        >
          <div className="ds-panel ds-row">
            <button className="button" onClick={() => setModal(true)}>
              Open sample dialog
            </button>
            <button
              className="button"
              onClick={() =>
                setNotice("Changes saved. This is a sample notification.")
              }
            >
              Show sample toast
            </button>
            <span className="ds-muted">
              Preview only · no camera or caregiver actions
            </span>
          </div>
        </Section>
        <footer className="ds-footer">
          Ollo design system · Current app reference · Leave a note to shape the
          next iteration.
        </footer>
      </main>
      <aside className="ds-feedback">
        <div className="ds-row">
          <MessageSquare size={17} />
          <h2>Review notes</h2>
          <span className="pill">{notes.length}</span>
        </div>
        <p className="ds-muted">
          Comments stay in this browser. Export to share them.
        </p>
        <label className="ds-field">
          Section
          <select value={target} onChange={(e) => setTarget(e.target.value)}>
            {sections.map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </label>
        <label className="ds-field">
          Your feedback
          <textarea
            id="ds-comment"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="What works? What should change?"
          />
        </label>
        <button
          className="button light full"
          disabled={!draft.trim()}
          onClick={save}
        >
          Save comment
        </button>
        <div className="ds-notes">
          {notes.length === 0 ? (
            <div className="ds-empty">
              <MessageSquare size={24} />
              <strong>A space for your thoughts</strong>
              <span>Use any section’s Comment button to start.</span>
            </div>
          ) : (
            notes.map((n, i) => (
              <article key={n.created + i}>
                <div className="ds-row">
                  <a href={`#${slug(n.section)}`}>{n.section}</a>
                  <button
                    aria-label={`Delete comment ${i + 1}`}
                    className="icon-button"
                    onClick={() => {
                      const next = notes.filter((_, j) => j !== i);
                      try {
                        localStorage.setItem(
                          "ollo-design-notes",
                          JSON.stringify(next),
                        );
                        setNotes(next);
                      } catch {
                        setNotice("Unable to update browser storage.");
                      }
                    }}
                  >
                    <X size={12} />
                  </button>
                </div>
                <p>{n.text}</p>
              </article>
            ))
          )}
        </div>
        <button className="button full" onClick={exportNotes}>
          <Download size={13} /> Export feedback
        </button>
      </aside>
      {notice && (
        <div className="ds-toast" role="status">
          <Check size={15} />
          {notice}
          <button
            aria-label="Dismiss notification"
            onClick={() => setNotice("")}
          >
            <X size={14} />
          </button>
        </div>
      )}
      {modal && (
        <div className="ds-modal-backdrop" onClick={() => setModal(false)}>
          <div
            className="ds-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="ds-dialog-title"
            onClick={(e) => e.stopPropagation()}
            onKeyDown={(e) => {
              if (e.key === "Escape") setModal(false);
              if (e.key === "Tab") {
                const buttons =
                  e.currentTarget.querySelectorAll<HTMLButtonElement>("button");
                const first = buttons[0],
                  last = buttons[buttons.length - 1];
                if (e.shiftKey && document.activeElement === first) {
                  e.preventDefault();
                  last.focus();
                } else if (!e.shiftKey && document.activeElement === last) {
                  e.preventDefault();
                  first.focus();
                }
              }
            }}
          >
            <span className="pill amber">Preview incident</span>
            <h2 id="ds-dialog-title">Review this moment</h2>
            <p>
              This sample shows the dialog style used for focused decisions. No
              notification will be sent.
            </p>
            <div className="ds-row">
              <button
                autoFocus
                className="button"
                onClick={() => setModal(false)}
              >
                Cancel
              </button>
              <button
                className="button light"
                onClick={() => {
                  setModal(false);
                  setNotice("Sample incident acknowledged.");
                }}
              >
                Acknowledge preview
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
