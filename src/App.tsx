import { useEffect, useRef, useState } from "react";
import {
  Activity,
  ArrowUpRight,
  Bell,
  Check,
  CheckCheck,
  ChevronDown,
  ChevronRight,
  Clock3,
  Download,
  Eye,
  Focus,
  Grid2X2,
  History,
  LockKeyhole,
  Maximize2,
  Pause,
  Phone,
  Play,
  Plus,
  RotateCcw,
  ScanLine,
  Settings2,
  Shield,
  SlidersHorizontal,
  Upload,
  Video,
  Volume2,
  VolumeX,
  Webcam,
  WifiOff,
  X,
} from "lucide-react";
import type { LookoutState } from "./types";
import { initialState, request } from "./api";
import EventTrace from "./EventTrace";
const demoTracks = [
  { x: 9.3, y: 40.1, w: 9, h: 25.2 },
  { x: 40.1, y: 36.2, w: 6.8, h: 16.4 },
  { x: 57, y: 27, w: 6.2, h: 24 },
  { x: 77.7, y: 16.5, w: 6, h: 21 },
];
const rooms = [
  {
    name: "Toddler room",
    id: "CAM 01",
    status: "Active",
    type: "Toddler room · East wing",
  },
  {
    name: "Nursery",
    id: "CAM 02",
    status: "Not connected",
    type: "Infant room · East wing",
  },
  {
    name: "Playroom",
    id: "CAM 03",
    status: "Not connected",
    type: "Shared space · West wing",
  },
];
const fmt = (value: string | number) =>
  new Date(typeof value === "number" ? value * 1000 : value).toLocaleTimeString(
    "en-US",
    { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false },
  );
const stamp = (n: number) =>
  `${Math.floor(n / 60)
    .toString()
    .padStart(2, "0")}:${Math.floor(n % 60)
    .toString()
    .padStart(2, "0")}`;
export default function App() {
  const [state, setState] = useState<LookoutState>(initialState),
    [connected, setConnected] = useState(false),
    [page, setPage] = useState("monitor"),
    [room, setRoom] = useState(0),
    [selectedIncident, setSelectedIncident] = useState<string | null>(null),
    [playing, setPlaying] = useState(true),
    [zones, setZones] = useState(true),
    [source, setSource] = useState(""),
    [sourceType, setSourceType] = useState("illustration"),
    [position, setPosition] = useState(0),
    [duration, setDuration] = useState(120),
    [toast, setToast] = useState(""),
    [scenarioOpen, setScenarioOpen] = useState(false),
    [sourceOpen, setSourceOpen] = useState(false),
    [muted, setMuted] = useState(true),
    [settingsTab, setSettingsTab] = useState("General"),
    [form, setForm] = useState({
      room_label: "Toddler room",
      primary_name: "Maya Chen",
      backup_name: "James Wilson",
      escalation_seconds: 8,
    }),
    [busy, setBusy] = useState(false),
    [mobileDone, setMobileDone] = useState(false),
    [analysisReady, setAnalysisReady] = useState(false),
    [mediaAspect, setMediaAspect] = useState(1.6),
    [stageAspect, setStageAspect] = useState(1.6),
    [cloudEnabled, setCloudEnabled] = useState(false);
  const video = useRef<HTMLVideoElement>(null),
    file = useRef<HTMLInputElement>(null),
    stage = useRef<HTMLDivElement>(null),
    stream = useRef<MediaStream | null>(null),
    seq = useRef(0),
    stateRef = useRef(state),
    settingsHydrated = useRef(false);
  stateRef.current = state;
  const active = state.incidents.find(
    (i) => i.status === "open" || i.status === "acknowledged",
  );
  const mediaRect =
    mediaAspect > stageAspect
      ? {
          left: "0%",
          width: "100%",
          height: `${(stageAspect / mediaAspect) * 100}%`,
          top: `${(1 - stageAspect / mediaAspect) * 50}%`,
        }
      : {
          top: "0%",
          height: "100%",
          width: `${(mediaAspect / stageAspect) * 100}%`,
          left: `${(1 - mediaAspect / stageAspect) * 50}%`,
        };
  useEffect(() => {
    if (!stage.current) return;
    const observer = new ResizeObserver((entries) => {
      const r = entries[0]?.contentRect;
      if (r) setStageAspect(r.width / r.height);
    });
    observer.observe(stage.current);
    return () => observer.disconnect();
  }, [page]);
  const notify = (s: string) => {
    setToast(s);
    window.setTimeout(() => setToast(""), 4200);
  };
  useEffect(() => {
    const close = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setSourceOpen(false);
        setScenarioOpen(false);
      }
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, []);
  useEffect(() => {
    if (page === "settings" && connected) {
      setCloudEnabled(state.settings.cloud_review_enabled === true);
      setForm({
        room_label: state.camera.room_label,
        primary_name: state.caregivers[0]?.name || "Maya Chen",
        backup_name: state.caregivers[1]?.name || "James Wilson",
        escalation_seconds: Number(state.settings.primary_delay_seconds || 8),
      });
    }
  }, [page, connected]);
  useEffect(() => {
    let live = true;
    const refresh = async () => {
      try {
        const s = await request<LookoutState>("/state", undefined, "GET");
        if (live) {
          setState(s);
          setConnected(true);
          if (!settingsHydrated.current) {
            settingsHydrated.current = true;
            setCloudEnabled(s.settings.cloud_review_enabled === true);
            setForm({
              room_label: s.camera.room_label,
              primary_name: s.caregivers[0]?.name || "Maya Chen",
              backup_name: s.caregivers[1]?.name || "James Wilson",
              escalation_seconds: Number(s.settings.primary_delay_seconds || 8),
            });
          }
        }
      } catch {
        if (live) setConnected(false);
      }
    };
    refresh();
    const id = setInterval(refresh, 1500);
    return () => {
      live = false;
      clearInterval(id);
      stream.current?.getTracks().forEach((t) => t.stop());
    };
  }, []);
  useEffect(() => {
    if (!playing || source) return;
    const id = setInterval(() => setPosition((p) => (p + 1) % 120), 1000);
    return () => clearInterval(id);
  }, [playing, source]);
  useEffect(() => {
    if (!source && sourceType !== "webcam") return;
    const id = setInterval(() => {
      const v = video.current,
        s = stateRef.current;
      if (
        !v ||
        v.paused ||
        v.readyState < 2 ||
        !connected ||
        !analysisReady ||
        s.session.status !== "active"
      )
        return;
      const canvas = document.createElement("canvas");
      canvas.width = 640;
      canvas.height = Math.round((640 * v.videoHeight) / v.videoWidth);
      canvas.getContext("2d")?.drawImage(v, 0, 0, canvas.width, canvas.height);
      request("/frames", {
        session_id: s.session.id,
        epoch: s.session.epoch,
        frame_seq: ++seq.current,
        media_time_ms: Math.round(v.currentTime * 1000),
        image: canvas.toDataURL("image/jpeg", 0.65).split(",")[1],
      }).catch(() => {
        setAnalysisReady(false);
        notify("Frame analysis connection failed. Video continues locally.");
      });
    }, 500);
    return () => clearInterval(id);
  }, [source, sourceType, connected, analysisReady]);
  async function scenario(kind: string) {
    setScenarioOpen(false);
    stream.current?.getTracks().forEach((t) => t.stop());
    setSource("");
    setSourceType("illustration");
    setAnalysisReady(false);
    if (kind === "normal") {
      if (connected) {
        try {
          setState(
            await request("/demo/scenario", {
              scenario: kind,
              media_time_ms: Math.round(position * 1000),
            }),
          );
          notify("Normal activity fixture loaded");
        } catch {
          notify("Could not load normal fixture. Please retry.");
        }
      } else {
        setState((s) => ({ ...s, camera: { ...s.camera, health: "active" } }));
        notify("Normal activity fixture loaded");
      }
      return;
    }
    if (connected) {
      try {
        setState(
          await request("/demo/scenario", {
            scenario: kind,
            media_time_ms: Math.round(position * 1000),
          }),
        );
        notify(
          kind === "offline"
            ? "Camera offline fixture loaded"
            : "Labeled event fixture created",
        );
        return;
      } catch {
        notify("Server unavailable. Using local fixture.");
      }
    }
    const at = new Date().toISOString();
    setState((s) =>
      kind === "offline"
        ? { ...s, camera: { ...s.camera, health: "offline" } }
        : {
            ...s,
            camera: { ...s.camera, health: "active" },
            incidents: [
              {
                id: crypto.randomUUID(),
                kind,
                title:
                  kind === "distress"
                    ? "Possible distress observed"
                    : "Restricted area entered",
                room: rooms[room].name,
                status: "open",
                opened_at: at,
                media_time_ms: Math.round(position * 1000),
                source_key: "fixture",
                observations:
                  kind === "distress"
                    ? [
                        "Staged concern gesture — immediate caregiver review requested.",
                        "Airway status cannot be determined from video.",
                      ]
                    : [
                        "Configured doorway boundary crossed.",
                        "Check the room and confirm a responder.",
                      ],
                origin: "fixture",
                priority: "high",
                primary_due_at: Date.now() / 1000 + 8,
                backup_due_at: Date.now() / 1000 + 30,
              },
              ...s.incidents,
            ],
            events: [
              {
                id: crypto.randomUUID(),
                type: "incident",
                message:
                  kind === "distress"
                    ? "Possible distress fixture created"
                    : "Doorway crossing fixture created",
                at,
              },
              ...s.events,
            ],
          },
    );
  }
  async function action(id: string, kind: string) {
    if (connected) {
      try {
        setState(
          await request(
            `/incidents/${id}/${kind}`,
            kind === "dismiss"
              ? {
                  reason: "Reviewed and dismissed by operator",
                  actor: state.caregivers[0]?.name || "Caregiver",
                }
              : { actor: state.caregivers[0]?.name || "Caregiver" },
          ),
        );
        notify(
          kind === "acknowledge"
            ? "Response acknowledged"
            : kind === "resolve"
              ? "Incident resolved"
              : "Incident dismissed",
        );
        return;
      } catch {
        notify("Action failed. Please retry.");
        return;
      }
    }
    setState((s) => ({
      ...s,
      incidents: s.incidents.map((i) =>
        i.id === id
          ? {
              ...i,
              status:
                kind === "acknowledge"
                  ? "acknowledged"
                  : kind === "resolve"
                    ? "resolved"
                    : "dismissed",
            }
          : i,
      ),
      events: [
        {
          id: crypto.randomUUID(),
          type: kind,
          message:
            kind === "acknowledge"
              ? "Caregiver acknowledged the incident"
              : kind === "resolve"
                ? "Incident marked resolved"
                : "Incident dismissed after review",
          at: new Date().toISOString(),
        },
        ...s.events,
      ],
    }));
    notify("Demo incident updated");
  }
  async function upload(f: File) {
    if (!f.type.startsWith("video/")) {
      notify("Choose an MP4 or another supported video file");
      return;
    }
    if (f.size > 100 * 1024 * 1024) {
      notify("Please choose a video smaller than 100 MB");
      return;
    }
    setBusy(true);
    setAnalysisReady(false);
    stream.current?.getTracks().forEach((t) => t.stop());
    setSource(URL.createObjectURL(f));
    setSourceType("recording");
    setPosition(0);
    setRoom(0);
    setSourceOpen(false);
    setPlaying(true);
    seq.current = 0;
    if (connected) {
      try {
        const body = new FormData();
        body.append("file", f);
        setState(await request("/video", body));
        setState(await request("/session/start", {}));
        setAnalysisReady(true);
        notify("Video connected. Analysis follows playback.");
      } catch {
        notify("Playing locally. Server upload failed; analysis unavailable.");
      }
    } else notify("Video loaded locally. Connect backend for analysis.");
    setBusy(false);
  }
  async function webcam() {
    try {
      const media = await navigator.mediaDevices.getUserMedia({
        video: true,
        audio: false,
      });
      stream.current?.getTracks().forEach((t) => t.stop());
      stream.current = media;
      setSource("");
      setSourceType("webcam");
      setRoom(0);
      setSourceOpen(false);
      setPlaying(true);
      setAnalysisReady(false);
      seq.current = 0;
      setTimeout(() => {
        if (video.current) video.current.srcObject = media;
      }, 80);
      if (connected) {
        try {
          setState(await request("/source", { source_type: "webcam" }));
          setState(await request("/session/start", {}));
          setAnalysisReady(true);
          notify("Webcam connected. Experimental analysis active.");
        } catch {
          notify("Webcam playing locally; analysis connection failed.");
        }
      } else notify("Webcam playing locally. Connect backend for analysis.");
    } catch {
      notify("Camera access unavailable. You can upload a recording instead.");
    }
  }
  async function togglePlay() {
    const next = !playing;
    setPlaying(next);
    if (video.current) {
      if (next) video.current.play().catch(() => {});
      else video.current.pause();
    }
    if (connected) {
      try {
        setState(await request(`/session/${next ? "start" : "pause"}`, {}));
        seq.current = 0;
      } catch {
        notify("Analysis state could not be updated");
      }
    }
  }
  async function reset() {
    stream.current?.getTracks().forEach((t) => t.stop());
    if (source.startsWith("blob:")) URL.revokeObjectURL(source);
    setSource("");
    setSourceType("illustration");
    setAnalysisReady(false);
    setPlaying(true);
    seq.current = 0;
    if (connected) {
      try {
        setState(await request("/session/reset", {}));
      } catch {
        notify("Reset failed");
        return;
      }
    } else setState(initialState);
    setPosition(0);
    if (video.current) video.current.currentTime = 0;
    setAnalysisReady(false);
    notify("Session reset. Calling disarmed.");
  }
  const mobileId = window.location.pathname.startsWith("/respond/")
    ? window.location.pathname.split("/").pop()
    : null;
  if (mobileId) {
    const incident = state.incidents.find((i) => i.id === mobileId);
    return (
      <div className="mobile-response">
        <div className="brand">
          <Eye size={25} />
          lookout<span className="beta">CAREGIVER</span>
        </div>
        <div className="mobile-response-card">
          <span className="eyebrow">CAREGIVER RESPONSE</span>
          <div className="mobile-icon">
            <Bell size={30} />
          </div>
          <h1>{incident?.title || "Incident response"}</h1>
          <p>{incident?.room || "Toddler room"}</p>
          {incident ? (
            <>
              <div className="mobile-observation">
                {incident.observations.map((o, i) => (
                  <p key={i}>{o}</p>
                ))}
              </div>
              <span className="pill amber">{incident.status}</span>
              <p className="muted">
                Acknowledging means you are responding. Resolve only after
                checking the room.
              </p>
              {incident.status === "open" ? (
                <button
                  className="button primary full"
                  onClick={() => action(incident.id, "acknowledge")}
                >
                  <Check size={18} />I am responding
                </button>
              ) : incident.status === "acknowledged" ? (
                <button
                  className="button primary full"
                  onClick={() => action(incident.id, "resolve")}
                >
                  <CheckCheck size={18} />
                  Mark resolved
                </button>
              ) : (
                <div className="resolved-confirmation">
                  <CheckCheck size={20} />
                  {incident.status === "resolved"
                    ? "Incident resolved. Thank you for responding."
                    : "Incident dismissed after review."}
                </div>
              )}
              {["open", "acknowledged"].includes(incident.status) && (
                <button
                  className="button full"
                  disabled={mobileDone}
                  onClick={async () => {
                    if (!connected) {
                      setMobileDone(true);
                      notify(
                        "Local demo: backup response requested. No real call placed.",
                      );
                      return;
                    }
                    try {
                      setState(
                        await request(`/incidents/${incident.id}/decline`, {
                          actor: state.caregivers[0]?.name || "Caregiver",
                        }),
                      );
                      setMobileDone(true);
                      notify("Backup responder requested");
                    } catch {
                      notify(
                        "Could not request backup. Contact the facility directly.",
                      );
                    }
                  }}
                >
                  {mobileDone
                    ? "Backup responder requested"
                    : "I cannot respond"}
                </button>
              )}
              {mobileDone && (
                <p>
                  Backup escalation requested. If urgent, contact the facility
                  directly.
                </p>
              )}
            </>
          ) : (
            <p className="muted">
              This incident is unavailable or has expired. Open a valid
              caregiver link from the monitoring dashboard.
            </p>
          )}
        </div>
      </div>
    );
  }
  return (
    <div className="app-shell">
      <main className="main">
        <header className="topbar">
          <button
            className="brand compact-brand"
            onClick={() => setPage("monitor")}
            aria-label="Lookout monitor"
          >
            <Eye size={23} strokeWidth={1.6} />
            lookout
          </button>
          <div className="topbar-nav">
            {page !== "monitor" && (
              <button className="button" onClick={() => setPage("monitor")}>
                <Video size={14} />
                Monitor
              </button>
            )}
            <button
              className={`button ${page === "settings" ? "active" : ""}`}
              onClick={() =>
                setPage(page === "settings" ? "monitor" : "settings")
              }
            >
              <Settings2 size={14} />
              Settings
            </button>
          </div>
          <div className="topbar-right">
            <span className={`connection ${connected ? "" : "local"}`}>
              <span className="status-dot" />
              {connected ? "System connected" : "Local demo"}
            </span>

          </div>
        </header>
        {page === "monitor" ? (
          <>
            <section className="monitor-grid">
              <div className="monitor-column">
                <div className="camera-card">
                  <div className="camera-toolbar">
                    <div>
                      <Video size={16} />
                      <select
                        className="camera-select"
                        aria-label="Select camera"
                        value={room}
                        onChange={(e) => {
                          setRoom(Number(e.target.value));
                          setSelectedIncident(null);
                        }}
                      >
                        {rooms.map((r, i) => (
                          <option value={i} key={r.id}>
                            {i === 0 ? state.camera.room_label : r.name}
                            {i ? " · Not connected" : ""}
                          </option>
                        ))}
                      </select>
                      <span className="camera-id">{rooms[room].id}</span>
                    </div>
                    <div>
                      <span className="record-label">
                        <span />{" "}
                        {sourceType === "webcam"
                          ? "LIVE WEBCAM"
                          : sourceType === "recording"
                            ? "RECORDED VIDEO"
                            : "ILLUSTRATIVE DEMO"}
                      </span>
                      <button
                        className={`icon-button ${zones ? "enabled" : ""}`}
                        title="Toggle zone overlay"
                        onClick={() => setZones(!zones)}
                      >
                        <Focus size={16} />
                      </button>
                      <button
                        className="icon-button"
                        title="Fullscreen"
                        onClick={() => stage.current?.requestFullscreen?.()}
                      >
                        <Maximize2 size={16} />
                      </button>
                    </div>
                  </div>
                  <div
                    className={`camera-stage ${state.camera.health === "offline" ? "offline" : ""}`}
                    ref={stage}
                  >
                    {room === 0 ? (
                      <>
                        {source || sourceType === "webcam" ? (
                          <video
                            ref={video}
                            src={source || undefined}
                            autoPlay
                            playsInline
                            muted={muted}
                            onTimeUpdate={(e) =>
                              setPosition(e.currentTarget.currentTime)
                            }
                            onLoadedMetadata={(e) => {
                              setDuration(
                                Number.isFinite(e.currentTarget.duration)
                                  ? e.currentTarget.duration
                                  : 120,
                              );
                              setMediaAspect(
                                e.currentTarget.videoWidth /
                                  e.currentTarget.videoHeight,
                              );
                            }}
                            onEnded={() => setPlaying(false)}
                            onSeeked={() => {
                              seq.current = 0;
                              if (connected && analysisReady)
                                request<LookoutState>("/session/start", {})
                                  .then(setState)
                                  .catch(() =>
                                    notify(
                                      "Could not reset analysis after seeking",
                                    ),
                                  );
                            }}
                          />
                        ) : (
                          <div className="demo-scene">
                            <img
                              src="/playroom-cctv.png"
                              alt="AI-generated CCTV-style playroom scene with toddlers playing"
                            />
                            {zones && (
                              <div
                                className="demo-tracks"
                                aria-label="Illustrative tracking boxes"
                              >
                                {demoTracks.map((t, i) => (
                                  <div
                                    className="demo-person"
                                    key={i}
                                    style={{
                                      left: `${t.x}%`,
                                      top: `${t.y}%`,
                                      width: `${t.w}%`,
                                      height: `${t.h}%`,
                                    }}
                                  >
                                    <span>
                                      PERSON {String(i + 1).padStart(2, "0")}
                                      <i>DEMO</i>
                                    </span>
                                  </div>
                                ))}
                              </div>
                            )}
                          </div>
                        )}
                        <div className="camera-shade" />
                        <div className="on-video-top">
                          <div className="source-badge">
                            <span
                              className={`status-dot ${state.camera.health === "offline" ? "red" : ""}`}
                            />
                            {state.camera.health === "offline"
                              ? "Analysis unavailable"
                              : sourceType === "illustration"
                                ? "Demo workspace"
                                : !analysisReady
                                  ? "Local playback"
                                  : state.camera.health === "degraded"
                                    ? "Analysis delayed"
                                    : state.session.status === "active"
                                      ? "Monitoring active"
                                      : "Analysis paused"}
                            <span className="island-divider" />
                            <span>
                              {sourceType === "illustration"
                                ? "Fixture mode"
                                : connected
                                  ? "Frame stream"
                                  : "Local playback"}
                            </span>
                          </div>
                          <div className="camera-clock">
                            <span>CAM 01 · EAST WING</span>
                            <strong>{stamp(position)}</strong>
                          </div>
                        </div>
                        {sourceType !== "illustration" && (
                          <div className="real-video-overlay" style={mediaRect}>
                            {zones && (
                              <svg
                                viewBox="0 0 1000 1000"
                                preserveAspectRatio="none"
                              >
                                <polygon
                                  points={(
                                    (
                                      state.settings.zone as {
                                        vertices?: number[][];
                                      }
                                    )?.vertices || [
                                      [0.72, 0.15],
                                      [0.94, 0.15],
                                      [0.94, 0.88],
                                      [0.72, 0.88],
                                    ]
                                  )
                                    .map((v) => `${v[0] * 1000},${v[1] * 1000}`)
                                    .join(" ")}
                                  fill="#c3d2aa15"
                                  stroke="#c3d2aa"
                                  strokeWidth="2"
                                  strokeDasharray="7 5"
                                  vectorEffect="non-scaling-stroke"
                                />
                              </svg>
                            )}
                            {state.overlays
                              ?.filter(
                                (o) =>
                                  o.epoch === state.session.epoch &&
                                  Math.abs(o.media_time_ms - position * 1000) <
                                    500,
                              )
                              .map((o, i) => (
                                <div
                                  key={i}
                                  className="tracking-box"
                                  style={{
                                    left: `${o.x * 100}%`,
                                    top: `${o.y * 100}%`,
                                    width: `${o.width * 100}%`,
                                    height: `${o.height * 100}%`,
                                  }}
                                >
                                  <span>{o.label}</span>
                                </div>
                              ))}
                          </div>
                        )}
                        {state.camera.health === "offline" && (
                          <div className="offline-message">
                            <WifiOff size={28} />
                            <h3>Analysis unavailable</h3>
                            <p>
                              Check the camera connection. Monitoring cannot be
                              confirmed.
                            </p>
                            <button
                              className="button"
                              onClick={() => scenario("normal")}
                            >
                              Restore demo
                            </button>
                          </div>
                        )}
                        <div className="video-footer">
                          <span>
                            <LockKeyhole size={11} />{" "}
                            {sourceType === "illustration"
                              ? "AI-generated still · illustrative tracks"
                              : "Controlled demo source · no identity recognition"}
                          </span>
                          <span>LOOKOUT / 01</span>
                        </div>
                      </>
                    ) : (
                      <div className="empty-camera">
                        <Video size={32} />
                        <h3>{rooms[room].name}</h3>
                        <p>No video source connected</p>
                        <button
                          className="button"
                          onClick={() => {
                            setPage("settings");
                          }}
                        >
                          <Plus size={15} />
                          Camera settings
                        </button>
                      </div>
                    )}
                  </div>
                  <div className="playback">
                    <div className="playback-top">
                      <div className="playback-left">
                        <button
                          className="icon-button play-button"
                          aria-label={
                            playing ? "Pause playback" : "Play playback"
                          }
                          onClick={togglePlay}
                        >
                          {playing ? (
                            <Pause size={16} fill="currentColor" />
                          ) : (
                            <Play size={16} fill="currentColor" />
                          )}
                        </button>
                        <button
                          className="icon-button"
                          title="Reset session"
                          onClick={reset}
                        >
                          <RotateCcw size={15} />
                        </button>
                        <span className="timecode">
                          {stamp(position)} <span>/ {stamp(duration)}</span>
                        </span>
                      </div>
                      <div>
                        <span className="speed">1×</span>
                        <button
                          className="icon-button"
                          aria-label={muted ? "Unmute video" : "Mute video"}
                          onClick={() => setMuted(!muted)}
                        >
                          {muted ? (
                            <VolumeX size={15} />
                          ) : (
                            <Volume2 size={15} />
                          )}
                        </button>
                      </div>
                    </div>
                    <div className="timeline">
                      <div className="timeline-markers">
                        {room === 0 &&
                          state.incidents
                            .filter(
                              (i) =>
                                i.media_time_ms !== undefined &&
                                i.source_key ===
                                  (sourceType === "illustration"
                                    ? "fixture"
                                    : sourceType === "recording"
                                      ? state.session.media_id
                                      : "webcam") &&
                                i.media_time_ms <= duration * 1000,
                            )
                            .map((i) => (
                              <button
                                key={i.id}
                                className={`incident-marker ${i.priority === "critical" ? "critical" : ""}`}
                                style={{
                                  left: `${Math.max(1, Math.min(99, (i.media_time_ms! / 1000 / duration) * 100))}%`,
                                }}
                                aria-label={`Jump to ${i.title} at ${stamp(i.media_time_ms! / 1000)}`}
                                title={`${stamp(i.media_time_ms! / 1000)} · ${i.title}`}
                                onClick={() => {
                                  setSelectedIncident(i.id);
                                  setPosition(i.media_time_ms! / 1000);
                                  if (video.current)
                                    video.current.currentTime =
                                      i.media_time_ms! / 1000;
                                }}
                              >
                                <span />
                              </button>
                            ))}
                      </div>
                      <div className="timeline-grid" />
                      <div
                        className="timeline-track"
                        style={{
                          width: `${Math.min((position / duration) * 100, 100)}%`,
                        }}
                      />
                      <input
                        aria-label="Video playback position"
                        type="range"
                        min="0"
                        max={Number.isFinite(duration) ? duration : 120}
                        step=".1"
                        value={position}
                        onChange={(e) => {
                          const p = Number(e.target.value);
                          setPosition(p);
                          if (video.current) video.current.currentTime = p;
                        }}
                      />
                      <div className="timeline-labels">
                        <span>00:00</span>
                        <span>{stamp(duration / 4)}</span>
                        <span>{stamp(duration / 2)}</span>
                        <span>{stamp(duration * 0.75)}</span>
                        <span>{stamp(duration)}</span>
                      </div>
                    </div>
                  </div>
                </div>
                <div className="below-camera">
                  <div>
                    <span className="status-dot" />
                    <span>
                      {sourceType === "illustration"
                        ? "Demo workspace"
                        : "Source connected"}
                    </span>
                    <span className="dot-divider">·</span>
                    <span>{zones ? "1 zone enabled" : "Zones hidden"}</span>
                  </div>
                  <button onClick={() => setPage("settings")}>
                    <SlidersHorizontal size={13} />
                    Monitoring settings
                    <ArrowUpRight size={12} />
                  </button>
                </div>
              </div>
              <EventTrace
                state={state}
                room={room}
                selected={selectedIncident}
                onSelect={setSelectedIncident}
                onAction={action}
                onSeek={(time) => {
                  setPosition(time);
                  if (video.current) video.current.currentTime = time;
                }}
              />
            </section>
          </>
        ) : page === "history" ? (
          <section className="secondary-page">
            <div className="eyebrow">OBSERVE. RESPOND. REVIEW.</div>
            <h1>Incident history</h1>
            <p className="muted">
              Every observation, acknowledgment, and resolution in one place.
            </p>
            <div className="history-stats">
              <div>
                <span>Total incidents</span>
                <strong>
                  {state.incidents.length.toString().padStart(2, "0")}
                </strong>
              </div>
              <div>
                <span>Needs review</span>
                <strong>{open.toString().padStart(2, "0")}</strong>
              </div>
              <div>
                <span>Resolved</span>
                <strong>
                  {state.incidents
                    .filter((i) => i.status === "resolved")
                    .length.toString()
                    .padStart(2, "0")}
                </strong>
              </div>
            </div>
            <div className="history-list">
              <div className="list-heading">
                <h2>Session incidents</h2>
                <button
                  className="button"
                  onClick={() => {
                    const blob = new Blob(
                      [JSON.stringify(state.incidents, null, 2)],
                      { type: "application/json" },
                    );
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement("a");
                    a.href = url;
                    a.download = "lookout-incidents.json";
                    a.click();
                    URL.revokeObjectURL(url);
                  }}
                >
                  <Download size={14} />
                  Export
                </button>
              </div>
              {state.incidents.length ? (
                state.incidents.map((i) => (
                  <div className="history-item" key={i.id}>
                    <div className="history-symbol">
                      <Bell size={18} />
                    </div>
                    <div className="history-detail">
                      <div>
                        <h3>{i.title}</h3>
                        <span
                          className={`pill ${i.status === "open" ? "amber" : ""}`}
                        >
                          {i.status}
                        </span>
                        <span className="tiny-label">{i.origin}</span>
                      </div>
                      <p>
                        {i.room} · {fmt(i.opened_at)}
                      </p>
                      <p>{i.observations.join(" ")}</p>
                      <a
                        href={`/respond/${i.id}`}
                        target="_blank"
                        rel="noreferrer"
                      >
                        Open caregiver response <ArrowUpRight size={12} />
                      </a>
                    </div>
                    <div className="history-actions">
                      {i.status === "open" && (
                        <button
                          className="button"
                          onClick={() => action(i.id, "acknowledge")}
                        >
                          <Check size={14} />
                          Acknowledge
                        </button>
                      )}
                      {i.status === "acknowledged" && (
                        <button
                          className="button"
                          onClick={() => action(i.id, "resolve")}
                        >
                          Resolve
                        </button>
                      )}
                      {i.status === "open" && (
                        <button
                          className="icon-button"
                          title="Dismiss"
                          onClick={() => action(i.id, "dismiss")}
                        >
                          <X size={16} />
                        </button>
                      )}
                    </div>
                  </div>
                ))
              ) : (
                <div className="empty-history">
                  <History size={30} />
                  <h3>A fresh start.</h3>
                  <p>Run scenario or connect video to begin.</p>
                  <button
                    className="button"
                    onClick={() => {
                      setPage("monitor");
                      setScenarioOpen(true);
                    }}
                  >
                    Explore a scenario
                    <ArrowUpRight size={14} />
                  </button>
                </div>
              )}
            </div>
          </section>
        ) : (
          <section className="secondary-page settings-page">
            <div className="eyebrow">MAKE LOOKOUT YOURS</div>
            <h1>Workspace settings</h1>
            <p className="muted">
              Configure your space, responders, and monitoring preferences.
            </p>
            <div className="settings-tabs">
              {["General", "Caregivers", "Monitoring"].map((t) => (
                <button
                  className={settingsTab === t ? "active" : ""}
                  onClick={() => setSettingsTab(t)}
                  key={t}
                >
                  {t}
                </button>
              ))}
            </div>
            <div className="settings-card">
              <h2>
                {settingsTab === "General"
                  ? "Your workspace"
                  : settingsTab === "Caregivers"
                    ? "Response team"
                    : "Monitoring preferences"}
              </h2>
              <p className="muted">
                {settingsTab === "General"
                  ? "A focused environment for your hackathon demonstration."
                  : settingsTab === "Caregivers"
                    ? "Configure display names here. Verified phone destinations are managed securely on the backend."
                    : "Define observable events and how a caregiver is reached."}
              </p>
              {settingsTab === "General" ? (
                <>
                  <label>
                    Room name
                    <input
                      value={form.room_label}
                      onChange={(e) =>
                        setForm({ ...form, room_label: e.target.value })
                      }
                    />
                  </label>
                  <div className="settings-row">
                    <div>
                      <strong>Source</strong>
                      <p>Prerecorded video or browser webcam</p>
                    </div>
                    <button
                      className="button"
                      onClick={() => setSourceOpen(true)}
                    >
                      Manage source
                      <Video size={14} />
                    </button>
                  </div>
                  <div className="settings-row">
                    <div>
                      <strong>Demo scenarios</strong>
                      <p>Labeled fixtures for testing the response flow.</p>
                    </div>
                    <div className="fixture-buttons">
                      {[
                        ["boundary", "Doorway crossing"],
                        ["distress", "Possible distress"],
                        ["normal", "Normal activity"],
                        ["offline", "Camera disconnected"],
                      ].map(([key, label]) => (
                        <button
                          className="button"
                          key={key}
                          onClick={async () => {
                            await scenario(key);
                            setPage("monitor");
                          }}
                        >
                          {label}
                        </button>
                      ))}
                    </div>
                  </div>
                  <div className="settings-row">
                    <div>
                      <strong>Phone escalation</strong>
                      <p>
                        {state.session.calls_armed
                          ? "Real calls armed for configured teammates."
                          : "Simulation · no real calls placed."}
                      </p>
                    </div>
                    <button
                      className="button"
                      onClick={async () => {
                        try {
                          setState(
                            await request("/session/arm-calls", {
                              armed: !state.session.calls_armed,
                            }),
                          );
                        } catch {
                          notify(
                            "Configure calling credentials and allowlisted teammates first.",
                          );
                        }
                      }}
                    >
                      {state.session.calls_armed
                        ? "Disarm calls"
                        : "Arm real calls"}
                    </button>
                  </div>
                  <div className="settings-row">
                    <div>
                      <strong>Session data</strong>
                      <p>Reset incidents and disarm outgoing calls.</p>
                    </div>
                    <button className="button danger-subtle" onClick={reset}>
                      Reset session
                    </button>
                  </div>
                </>
              ) : settingsTab === "Caregivers" ? (
                <>
                  <label>
                    Primary caregiver
                    <input
                      value={form.primary_name}
                      onChange={(e) =>
                        setForm({ ...form, primary_name: e.target.value })
                      }
                    />
                  </label>
                  <label>
                    Backup caregiver
                    <input
                      value={form.backup_name}
                      onChange={(e) =>
                        setForm({ ...form, backup_name: e.target.value })
                      }
                    />
                  </label>
                  <div className="info-note">
                    <LockKeyhole size={16} />
                    <p>
                      Real calls require consenting, allowlisted teammates and
                      configured calling credentials. Phone numbers are never
                      stored in this browser.
                    </p>
                  </div>
                </>
              ) : (
                <>
                  <div className="settings-row">
                    <div>
                      <strong>Doorway zone overlay</strong>
                      <p>Show the configured boundary on the camera.</p>
                    </div>
                    <button
                      className={`toggle standalone ${zones ? "on" : ""}`}
                      aria-label="Toggle boundary overlay"
                      onClick={() => setZones(!zones)}
                    >
                      <i />
                    </button>
                  </div>
                  <div className="settings-row">
                    <div>
                      <strong>Cloud distress review</strong>
                      <p>
                        Send consenting staged frames to configured Claude API.
                      </p>
                    </div>
                    <button
                      className={`toggle standalone ${cloudEnabled ? "on" : ""}`}
                      aria-label="Toggle cloud review"
                      onClick={() => setCloudEnabled(!cloudEnabled)}
                    >
                      <i />
                    </button>
                  </div>
                  <label>
                    Escalation delay (seconds)
                    <input
                      type="number"
                      min="5"
                      max="120"
                      value={form.escalation_seconds}
                      onChange={(e) =>
                        setForm({
                          ...form,
                          escalation_seconds: Number(e.target.value),
                        })
                      }
                    />
                  </label>
                  <div className="info-note">
                    <Activity size={16} />
                    <p>
                      Possible distress review is experimental. Video cannot
                      establish airway status or confirm that a child is safe.
                    </p>
                  </div>
                </>
              )}
              <div className="settings-save">
                <button
                  className="button light"
                  onClick={async () => {
                    if (connected) {
                      try {
                        setState(
                          await request(
                            "/settings",
                            { ...form, cloud_review_enabled: cloudEnabled },
                            "PUT",
                          ),
                        );
                        notify("Workspace preferences saved");
                      } catch {
                        notify("Could not save preferences");
                        return;
                      }
                    } else {
                      setState((s) => ({
                        ...s,
                        camera: { ...s.camera, room_label: form.room_label },
                        caregivers: s.caregivers.map((c, i) => ({
                          ...c,
                          name: i ? form.backup_name : form.primary_name,
                        })),
                        settings: {
                          ...s.settings,
                          cloud_review_enabled: cloudEnabled,
                        },
                      }));
                      notify("Demo preferences saved locally");
                    }
                    localStorage.setItem(
                      "lookout-settings",
                      JSON.stringify(form),
                    );
                  }}
                >
                  <Check size={15} />
                  Save changes
                </button>
              </div>
            </div>
          </section>
        )}
      </main>
      <input
        ref={file}
        type="file"
        accept="video/mp4,video/webm,video/quicktime"
        hidden
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) upload(f);
        }}
      />
      {sourceOpen && (
        <div className="modal-backdrop" onClick={() => setSourceOpen(false)}>
          <div
            className="source-modal"
            role="dialog"
            aria-modal="true"
            aria-label="Connect video source"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="modal-top">
              <span className="eyebrow">BRING YOUR SPACE INTO VIEW</span>
              <button
                className="icon-button"
                aria-label="Close dialog"
                onClick={() => setSourceOpen(false)}
              >
                <X size={18} />
              </button>
            </div>
            <h2>Connect a source</h2>
            <p className="muted">
              Start with controlled demo footage. Your video stays on your
              device until uploaded to the backend.
            </p>
            <button
              className="upload-area"
              onClick={() => file.current?.click()}
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => {
                e.preventDefault();
                const f = e.dataTransfer.files[0];
                if (f) upload(f);
              }}
            >
              <div>
                <Upload size={24} />
              </div>
              <strong>
                {busy ? "Loading your video…" : "Drop a recording here"}
              </strong>
              <span>or click to browse · MP4 / WebM · up to 100 MB</span>
            </button>
            <button className="source-option" onClick={webcam}>
              <Webcam size={20} />
              <span>
                Use this device’s camera
                <small>Browser permission required</small>
              </span>
              <ArrowUpRight size={16} />
            </button>
            <button
              className="source-option"
              onClick={() => {
                stream.current?.getTracks().forEach((t) => t.stop());
                setSource("");
                setSourceType("illustration");
                setAnalysisReady(false);
                setSourceOpen(false);
                if (connected)
                  request<LookoutState>("/source", { source_type: "fixture" })
                    .then(setState)
                    .catch(() => notify("Could not reset backend source"));
              }}
            >
              <Grid2X2 size={20} />
              <span>
                Explore the demo workspace
                <small>Illustrated room with labeled event fixtures</small>
              </span>
              <ArrowUpRight size={16} />
            </button>
            <div className="info-note">
              <Shield size={15} />
              <p>
                Use footage you have permission to share. This prototype
                supports caregiver review and does not diagnose medical
                conditions.
              </p>
            </div>
          </div>
        </div>
      )}
      {toast && (
        <div className="toast" role="status">
          <Check size={16} />
          {toast}
          <button
            aria-label="Dismiss notification"
            onClick={() => setToast("")}
          >
            <X size={14} />
          </button>
        </div>
      )}
    </div>
  );
}
