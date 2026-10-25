import { adaptIncidentThread, addIncidentNote, resolveIncidentThread } from "./incidentThreads";
import { recordAudit } from "./reviewAudit";
import type { IncidentThreadChanges } from "./types";
import Navbar from "./Navbar";
import Brand from "./Brand";
import { useEffect, useRef, useState } from "react";
import {
  Activity,
  ArrowUpRight,
  Bell,
  Cctv,
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
  Shield,
  TriangleAlert,
  Upload,
  Video,
  Webcam,
  WifiOff,
  X,
} from "lucide-react";
import type { LookoutState } from "./types";
import { initialState, request } from "./api";
import EventTrace from "./EventTrace";
import ResizableWorkspace from "./ResizableWorkspace";
import LiveCameraPlaceholder from "./LiveCameraPlaceholder";
import CameraCard from "./CameraCard";
import PlaybackTime from "./PlaybackTime";
import { demoIncidents } from "./demoIncidents";
import FullscreenControls from "./FullscreenControls";
import usePlaybackShortcuts from "./usePlaybackShortcuts";
import EditorTimeline, { type TimelineMarker } from "./EditorTimeline";
import MonitoringControls, { dateKey, type CameraLayout } from "./MonitoringControls";
// COCO keypoint pairs drawn as limbs (UI-6).
const LIMBS = [
  [0, 1], [0, 2], [1, 3], [2, 4], [5, 6], [5, 7], [7, 9], [6, 8],
  [8, 10], [5, 11], [6, 12], [11, 12], [11, 13], [13, 15], [12, 14], [14, 16],
];
type FloorPlanData = NonNullable<LookoutState["floor_plan"]>;
type Overlay = NonNullable<LookoutState["overlays"]>[number];
// UI-4: top-down inset in meters, scaled to fit everything it shows.
function FloorPlan({ plan, people }: { plan: FloorPlanData; people: Overlay[] }) {
  const pts = [
    ...plan.points,
    ...plan.zones.flatMap((z) => z.polygon),
    ...plan.landmarks.flatMap((l) => l.polygon),
    ...people.flatMap((p) => [p.floor, ...(p.approach?.floor_path || [])].filter(Boolean) as number[][]),
  ];
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  const minX = Math.min(...xs) - 0.5, minY = Math.min(...ys) - 0.5;
  const w = Math.max(...xs) + 0.5 - minX, h = Math.max(...ys) + 0.5 - minY;
  const unit = Math.max(w, h) / 100;
  const poly = (p: number[][]) => p.map((v) => v.join(",")).join(" ");
  return (
    <svg viewBox={`${minX} ${minY} ${w} ${h}`} preserveAspectRatio="xMidYMid meet" role="img" aria-label="Floor plan in meters">
      {plan.zones.map((z) => (
        <polygon key={z.id} className="fp-zone" points={poly(z.polygon)} vectorEffect="non-scaling-stroke" />
      ))}
      {plan.landmarks.map((l) => (
        <polygon key={l.id} className="fp-landmark" points={poly(l.polygon)} vectorEffect="non-scaling-stroke" />
      ))}
      {plan.points.map((p, i) => (
        <circle key={i} className="fp-ref" cx={p[0]} cy={p[1]} r={unit * 0.8} />
      ))}
      {people.map((p, i) =>
        p.approach?.warning && p.approach.floor_path ? (
          <line
            key={`path-${p.id || i}`}
            className="fp-path"
            x1={p.approach.floor_path[0][0]}
            y1={p.approach.floor_path[0][1]}
            x2={p.approach.floor_path[1][0]}
            y2={p.approach.floor_path[1][1]}
            vectorEffect="non-scaling-stroke"
          />
        ) : null,
      )}
      {people.map((p, i) =>
        p.floor ? (
          <g key={`p-${p.id || i}`} className={`fp-person ${p.approach?.warning ? "warned" : ""}`}>
            <circle cx={p.floor[0]} cy={p.floor[1]} r={unit * 2.2} />
            <text x={p.floor[0] + unit * 3} y={p.floor[1] + unit * 1.5} fontSize={unit * 6}>
              {p.track_id ?? i + 1}
            </text>
          </g>
        ) : null,
      )}
      <line className="fp-scale" x1={minX + unit * 4} y1={minY + h - unit * 4} x2={minX + unit * 4 + 1} y2={minY + h - unit * 4} vectorEffect="non-scaling-stroke" />
      <text className="fp-scale-label" x={minX + unit * 4} y={minY + h - unit * 6} fontSize={unit * 5}>1 m</text>
    </svg>
  );
}
// Rhythmic-movement analysis needs at least 8 analyzed frames per second.
const ANALYSIS_FPS = 12;
type Landmark = { id: string; name: string; vertices: number[][] };
type Rule = {
  id: string;
  landmark_id: string;
  schedule: { type: "always" | "window" | "nap"; start?: string; end?: string };
  severity: string;
  summary: string;
  status: "draft" | "active";
};
const demoTracks = [
  { x: 9.3, y: 40.1, w: 9, h: 25.2, confidence: 0.94 },
  { x: 40.1, y: 36.2, w: 6.8, h: 16.4, confidence: 0.89 },
  { x: 57, y: 27, w: 6.2, h: 24, confidence: 0.92 },
  { x: 77.7, y: 16.5, w: 6, h: 21, confidence: 0.96 },
];
const rooms = [
  {
    name: "Toddler room",
    id: "CAM 01",
    image: "/playroom-cctv.png",
    alt: "AI-generated CCTV-style playroom scene with toddlers playing",
    tracks: demoTracks,
  },
  {
    name: "Activity room",
    id: "CAM 02",
    image: "/playroom-cctv.png",
    alt: "Illustrative playroom fixture, reused for the second demo camera",
    tracks: demoTracks,
  },
  { name: "Entrance", id: "CAM 03", image: "", alt: "", tracks: [] },
];
function DemoScene({ room, zones, position }: { room: number; zones: boolean; position?: number }) {
  const camera = rooms[room];
  return (
    <div className="demo-scene">
      <img src={camera.image} alt={camera.alt} />
      {zones && (
        <div className="demo-tracks" aria-label="Illustrative tracking boxes">
          {camera.tracks.map((t, i) => (
            <div
              className="demo-person"
              key={i}
              style={{ left: `${t.x}%`, top: `${t.y}%`, width: `${t.w}%`, height: `${t.h}%` }}
            >
              <span title={`Illustrative detection · person · confidence ${t.confidence.toFixed(2)} · track ${i + 1}`}>
                person <b className="detection-confidence">{t.confidence.toFixed(2)}</b><small className="detection-track-id">#{String(i + 1).padStart(2, "0")}</small>
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
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
  const [signedOut, setSignedOut] = useState(() => sessionStorage.getItem("nestwatch-workspace-closed") === "true");
  const audioFile = useRef<File | null>(null);
  const [audioPeaks, setAudioPeaks] = useState<number[] | null>(null);
  const [cameraLayout, setCameraLayout] = useState<CameraLayout>("single");
  const [reviewDate, setReviewDate] = useState<string | null>(() => dateKey(new Date()));
  const [state, setState] = useState<LookoutState>(initialState),
    [connected, setConnected] = useState(false),
    [page, setPage] = useState(() => { const requested = new URLSearchParams(window.location.search).get("page"); return requested === "history" || requested === "settings" ? requested : "monitor"; }),
    [room, setRoom] = useState(0),
    [playing, setPlaying] = useState(true),
    [zones, setZones] = useState(true),
    [source, setSource] = useState(""),
    [sourceType, setSourceType] = useState("illustration"),
    [position, setPosition] = useState(0),
    [duration, setDuration] = useState(120),
    [toast, setToast] = useState(""),
    [scenarioOpen, setScenarioOpen] = useState(false),
    [sourceOpen, setSourceOpen] = useState(false),
    [cameraSpec, setCameraSpec] = useState(""),
    [cameraMessage, setCameraMessage] = useState(""),
    [serverFrame, setServerFrame] = useState(""),
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
    [cloudEnabled, setCloudEnabled] = useState(false),
    [calibrating, setCalibrating] = useState(false),
    [floorOpen, setFloorOpen] = useState(false),
    [calPoints, setCalPoints] = useState<
      { u: number; v: number; x: string; y: string }[]
    >([]),
    [calMessage, setCalMessage] = useState(""),
    [rulesOpen, setRulesOpen] = useState(false),
    [drawing, setDrawing] = useState(false),
    [drawPoints, setDrawPoints] = useState<{ u: number; v: number }[]>([]),
    [landmarkName, setLandmarkName] = useState(""),
    [ruleText, setRuleText] = useState(""),
    [ruleBusy, setRuleBusy] = useState(false),
    [ruleMessage, setRuleMessage] = useState(""),
    [report, setReport] = useState<{
      id: string;
      markdown: string;
      source: "claude" | "facts";
      removed_lines: number;
    } | null>(null);
  const video = useRef<HTMLVideoElement>(null),
    file = useRef<HTMLInputElement>(null),
    stage = useRef<HTMLDivElement>(null),
    stream = useRef<MediaStream | null>(null),
    seq = useRef(0),
    stateRef = useRef(state),
    // SRC-6: playback holds while server analysis of an upload is behind, so skeletons match the picture.
    catchUp = useRef<{ since: number; analyzedTo: number } | null>(null),
    settingsHydrated = useRef(false);
  stateRef.current = state;
  const [catchingUp, setCatchingUp] = useState(false);
  const endCatchUp = () => {
    catchUp.current = null;
    setCatchingUp(false);
  };
  // SRC-5: leaving the camera view (Settings, another camera) re-creates the <video>; give each new one the live camera.
  const attachVideo = (element: HTMLVideoElement | null) => {
    video.current = element;
    if (element && sourceType === "webcam" && stream.current && element.srcObject !== stream.current)
      element.srcObject = stream.current;
  };
  const incidentDate = (at: string | number) => dateKey(new Date(typeof at === "number" ? at * 1000 : at));
  const datedState = reviewDate ? { ...state, incidents: state.incidents.filter(i => incidentDate(i.opened_at) === reviewDate) } : state;
  const isLiveFeed = room === 2 || (room === 0 && (sourceType === "server" || sourceType === "webcam"));
  const [liveRecordingStart, setLiveRecordingStart] = useState<string | null>(null);
  const [liveRecordedSeconds, setLiveRecordedSeconds] = useState(0);
  useEffect(() => {
    if (sourceType !== "webcam" && sourceType !== "server") { setLiveRecordingStart(null); setLiveRecordedSeconds(0); return; }
    const supplied = state.session.recording_started_at;
    const start = supplied && Number.isFinite(Date.parse(supplied)) ? supplied : new Date().toISOString();
    setLiveRecordingStart(start);
    const update = () => setLiveRecordedSeconds(Math.max(0, (Date.now() - Date.parse(start)) / 1000));
    update(); const timer = window.setInterval(update, 1000);
    return () => window.clearInterval(timer);
  }, [sourceType, source, state.session.epoch, state.session.recording_started_at]);
  const timelineDuration = isLiveFeed ? room === 2 ? 0 : liveRecordedSeconds : duration;
  const currentSourceKey = sourceType === "illustration" ? "fixture" : sourceType === "recording" ? state.session.media_id : sourceType === "server" ? "server_camera" : "webcam";
  const mockIncidents = room !== 0 || sourceType === "illustration" ? demoIncidents(room) : [];
  const cameraIncidents = [
    ...(room === 0 && sourceType !== "illustration" ? datedState.incidents.filter(i => !i.source_key || i.source_key === currentSourceKey) : []),
    ...mockIncidents.filter(i => !reviewDate || incidentDate(i.opened_at) === reviewDate),
  ].sort((a, b) => (a.media_time_ms ?? 0) - (b.media_time_ms ?? 0));
  const traceState = { ...datedState, incidents: cameraIncidents };
  const [explicitIncident, setExplicitIncident] = useState<string | null>(null);
  const [hoveredIncident, setHoveredIncident] = useState<string | null>(null);
  const [openedThreadId, setOpenedThreadId] = useState<string | null>(null);
  const [selectedNoteId, setSelectedNoteId] = useState<string | null>(null);
  const [threadChanges, setThreadChanges] = useState<Record<string, IncidentThreadChanges>>({});
  const recordingStartedAt = sourceType === "illustration" || room === 1 ? new Date(new Date().setHours(9, 0, 0, 0)).toISOString() : isLiveFeed ? liveRecordingStart ?? undefined : state.session.recording_started_at;
  const incidentThreads = cameraIncidents.map(incident => adaptIncidentThread(incident, {
    cameraId: rooms[room].id, cameraName: rooms[room].name, recordingStartedAt,
    thumbnailUrl: sourceType === "illustration" || room === 1 ? rooms[room].image : serverFrame || undefined,
    attempts: state.attempts, changes: threadChanges[incident.id],
  }));
  const timelineMarkers = incidentThreads.filter(thread => thread.startSeconds !== undefined).map(thread => ({
    id: thread.id, time: thread.startSeconds!, endTime: thread.endSeconds, title: thread.title, status: thread.status,
    demo: thread.source.origin === "fixture", notes: thread.messages.filter(message => message.kind === "note" && message.anchorSeconds !== undefined).map(message => ({ id: message.id, time: message.anchorSeconds!, title: message.text })),
  }));
  const playheadIncidentId = timelineMarkers.find(marker => marker.endTime !== undefined && position >= marker.time && position <= marker.endTime)?.id;
  const selectedIncident = cameraIncidents.some(i => i.id === openedThreadId) ? openedThreadId : cameraIncidents.some(i => i.id === explicitIncident) ? explicitIncident : playheadIncidentId || null;
  function openIncidentThread(id: string, noteId?: string) {
    const at = new Date().toISOString();
    setExplicitIncident(id); setOpenedThreadId(id); setSelectedNoteId(noteId ?? null);
    setThreadChanges(current => ({ ...current, [id]: { ...current[id], messages: current[id]?.messages ?? [], lastReadAt: at } }));
    recordAudit({ action: "open_thread", userId: form.primary_name, cameraId: rooms[room].id, incidentId: id, at });
  }
  useEffect(() => { setOpenedThreadId(null); setSelectedNoteId(null); setExplicitIncident(null); }, [room, reviewDate, currentSourceKey]);
  const active = state.incidents.find(
    (i) => i.status === "open" || i.status === "acknowledged",
  );
  const canUseStaffUI = ["primary", "backup", "staff", "admin", "local_operator", "primary caregiver", "backup caregiver"].includes((state.caregivers[0]?.role ?? "local_operator").toLowerCase());
  const visibleOverlays = (zones && canUseStaffUI ? state.overlays || [] : []).filter(
    (o) =>
      o.epoch === state.session.epoch &&
      Math.abs(o.media_time_ms - position * 1000) < 500,
  );
  const savedCalibration = state.settings.calibration as
    | {
        error_m: number;
        ignored: number[];
        points: { image: number[]; floor: number[] }[];
      }
    | undefined;
  const calibrationReady =
    calPoints.length >= 4 &&
    calPoints.every(
      (p) =>
        p.x.trim() !== "" &&
        p.y.trim() !== "" &&
        Number.isFinite(Number(p.x)) &&
        Number.isFinite(Number(p.y)),
    );
  const landmarks = (state.settings.landmarks || []) as Landmark[];
  const rules = (state.settings.rules || []) as Rule[];
  const draftLandmarks = new Set(
    rules.filter((r) => r.status === "draft").map((r) => r.landmark_id),
  );
  const ruleLandmarks = new Set(
    rules.filter((r) => r.status === "active").map((r) => r.landmark_id),
  );
  const scheduleLabel = (r: Rule) =>
    r.schedule.type === "window"
      ? `${r.schedule.start}–${r.schedule.end}`
      : r.schedule.type === "nap"
        ? "During nap mode"
        : "Always";
  async function ruleAction(run: () => Promise<LookoutState>, done: string) {
    try {
      setState(await run());
      setRuleMessage(done);
    } catch (e) {
      setRuleMessage(e instanceof Error ? e.message : "Request failed");
    }
  }
  async function saveLandmark() {
    await ruleAction(
      () =>
        request("/landmarks", {
          name: landmarkName,
          vertices: drawPoints.map((p) => [p.u, p.v]),
        }),
      `Landmark "${landmarkName.trim()}" saved.`,
    );
    setDrawing(false);
    setDrawPoints([]);
    setLandmarkName("");
  }
  async function draftRule() {
    setRuleBusy(true);
    try {
      const body = await request<LookoutState & { rule?: Rule; question?: string }>(
        "/rules/draft",
        { text: ruleText },
      );
      setState(body);
      if (body.rule) {
        setRuleMessage("Draft ready. Check the outlined landmark, then confirm.");
        setRuleText("");
      } else setRuleMessage(body.question || "Claude needs more detail.");
    } catch (e) {
      setRuleMessage(e instanceof Error ? e.message : "Drafting failed");
    }
    setRuleBusy(false);
  }
  function toggleCalibration() {
    setRulesOpen(false);
    setDrawing(false);
    if (calibrating) {
      setCalibrating(false);
      return;
    }
    setCalPoints(
      savedCalibration?.points.map((p) => ({
        u: p.image[0],
        v: p.image[1],
        x: String(p.floor[0]),
        y: String(p.floor[1]),
      })) || [],
    );
    setCalMessage(
      savedCalibration
        ? `Saved calibration · average error ${savedCalibration.error_m.toFixed(2)} m`
        : "",
    );
    setCalibrating(true);
  }
  async function saveCalibration() {
    try {
      const next = await request("/calibration", {
        points: calPoints.map((p) => ({
          image: [p.u, p.v],
          floor: [Number(p.x), Number(p.y)],
        })),
      });
      setState(next);
      const saved = next.settings.calibration as { error_m: number; ignored: number[] };
      setCalMessage(
        `Saved · average error ${saved.error_m.toFixed(2)} m${saved.ignored.length ? ` · ignored point ${saved.ignored.map((i) => i + 1).join(", ")}` : ""}. Predictive warnings are on.`,
      );
    } catch (e) {
      setCalMessage(e instanceof Error ? e.message : "Calibration failed");
    }
  }
  async function clearCalibration() {
    try {
      setState(await request("/calibration", undefined, "DELETE"));
      setCalPoints([]);
      setCalMessage("Calibration removed. Predictive warnings are off.");
    } catch {
      setCalMessage("Could not remove the calibration");
    }
  }
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
    if (signedOut) return;
    let live = true;
    const refresh = async () => {
      try {
        const s = await request<LookoutState>("/state", undefined, "GET");
        if (live) {
          setState(s);
          setConnected(true);
          if (!settingsHydrated.current) {
            settingsHydrated.current = true;
            // SRC-4: the server camera keeps running without this page, so a reload returns to it.
            if (s.session.source_type === "server_camera") {
              setSourceType("server");
              setAnalysisReady(true);
            }
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
  }, [signedOut]);
  useEffect(() => {
    if (!playing || source || room === 2) return;
    let previous = performance.now();
    const id = setInterval(() => {
      const now = performance.now();
      const elapsed = (now - previous) / 1000;
      previous = now;
      setPosition(p => (p + elapsed) % (Number.isFinite(duration) && duration > 0 ? duration : 120));
    }, 100);
    return () => clearInterval(id);
  }, [playing, source, duration, room]);
  useEffect(() => {
    if (!source && sourceType !== "webcam") return;
    // One reused canvas; skip a tick while the previous upload is in flight so slow
    // analysis sheds frames instead of queueing stale ones.
    const canvas = document.createElement("canvas");
    let inFlight = false;
    const id = setInterval(() => {
      const v = video.current,
        s = stateRef.current;
      if (
        inFlight ||
        !v ||
        (v.paused && !catchUp.current) ||
        v.readyState < 2 ||
        !connected ||
        !analysisReady ||
        s.session.status !== "active"
      )
        return;
      if (source) {
        // SRC-6: the server decodes the uploaded file and analyzes every frame up to this playhead.
        inFlight = true;
        request<{ overlays?: LookoutState["overlays"]; analyzed_to_ms?: number }>("/playhead", {
          session_id: s.session.id,
          epoch: s.session.epoch,
          media_time_ms: Math.round(v.currentTime * 1000),
        })
          .then((r) => {
            if (r.overlays) setState((prev) => ({ ...prev, overlays: r.overlays }));
            const analyzedTo = r.analyzed_to_ms ?? -1;
            const behind = v.currentTime * 1000 - analyzedTo;
            const hold = catchUp.current;
            if (!hold && behind > 500 && !v.paused && !v.ended) {
              catchUp.current = { since: Date.now(), analyzedTo };
              v.pause();
              setCatchingUp(true);
            } else if (hold) {
              if (analyzedTo > hold.analyzedTo) catchUp.current = { since: Date.now(), analyzedTo };
              const stalled = Date.now() - (catchUp.current?.since ?? hold.since) > 15000;
              if (behind <= 150 || stalled) {
                if (stalled) notify("Analysis stopped making progress, so playback continues without waiting.");
                endCatchUp();
                v.play().catch(() => {});
              }
            }
          })
          .catch(() => {})
          .finally(() => {
            inFlight = false;
          });
        return;
      }
      canvas.width = 640;
      canvas.height = Math.round((640 * v.videoHeight) / v.videoWidth);
      canvas.getContext("2d")?.drawImage(v, 0, 0, canvas.width, canvas.height);
      inFlight = true;
      request<{ overlays?: LookoutState["overlays"] }>("/frames", {
        session_id: s.session.id,
        epoch: s.session.epoch,
        frame_seq: ++seq.current,
        media_time_ms: Math.round(v.currentTime * 1000),
        image: canvas.toDataURL("image/jpeg", 0.65).split(",")[1],
      })
        .then((r) => {
          if (r.overlays) setState((prev) => ({ ...prev, overlays: r.overlays }));
        })
        .catch(() => {
          setAnalysisReady(false);
          notify("Frame analysis connection failed. Video continues locally.");
        })
        .finally(() => {
          inFlight = false;
        });
    }, 1000 / ANALYSIS_FPS);
    return () => clearInterval(id);
  }, [source, sourceType, connected, analysisReady]);
  useEffect(() => {
    if (sourceType !== "server" || !connected) return;
    // SRC-4: the server analyzes its own camera. This page only shows each analyzed frame with
    // the overlays computed from it, by long polling, so a hidden tab never slows analysis.
    const abort = new AbortController();
    (async () => {
      let after = -1;
      while (!abort.signal.aborted) {
        try {
          const r = await fetch(`/api/camera/frame?after=${after}`, {
            signal: abort.signal,
          });
          if (r.status === 204) continue;
          if (r.ok) {
            const f: {
              frame_seq: number;
              media_time_ms: number;
              image: string;
              overlays: LookoutState["overlays"];
            } = await r.json();
            after = f.frame_seq;
            setServerFrame(`data:image/jpeg;base64,${f.image}`);
            setPosition(f.media_time_ms / 1000);
            setState((prev) => ({ ...prev, overlays: f.overlays }));
            continue;
          }
        } catch {
          if (abort.signal.aborted) return;
        }
        // No server camera yet, or the server is restarting.
        await new Promise((resolve) => setTimeout(resolve, 1000));
      }
    })();
    return () => abort.abort();
  }, [sourceType, connected]);
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
  async function action(
    id: string,
    kind: string,
    channel: "dashboard" | "app" = "dashboard",
  ) {
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
              : { actor: state.caregivers[0]?.name || "Caregiver", channel },
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
    audioFile.current = f;
    setAudioPeaks(null);
    setAnalysisReady(false);
    stream.current?.getTracks().forEach((t) => t.stop());
    setSource(URL.createObjectURL(f));
    setSourceType("recording");
    // Decode only the uploaded source, never microphone or unrelated audio.
    void (async () => {
      const context = new AudioContext();
      try {
        const audio = await context.decodeAudioData(await f.arrayBuffer());
        const channels = Array.from({ length: audio.numberOfChannels }, (_, i) => audio.getChannelData(i));
        const peaks = Array.from({ length: 480 }, (_, i) => {
          const start = Math.floor(i * audio.length / 480);
          const end = Math.floor((i + 1) * audio.length / 480);
          let peak = 0;
          for (const channel of channels)
            for (let j = start; j < end; j++) peak = Math.max(peak, Math.abs(channel[j]));
          return peak;
        });
        if (audioFile.current === f) setAudioPeaks(peaks);
      } catch { /* Source has no decodable audio track. */ }
      finally { await context.close(); }
    })();
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
        setState(await request("/session/start", { media_time_ms: 0 })); // SRC-6: analysis starts at 0
        setAnalysisReady(true);
        notify("Video connected. Analysis follows playback.");
      } catch {
        notify("Playing locally. Server upload failed; analysis unavailable.");
      }
    } else notify("Video loaded locally. Connect backend for analysis.");
    setBusy(false);
  }
  async function webcam() {
    audioFile.current = null;
    setAudioPeaks(null);
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
  async function serverCamera() {
    audioFile.current = null;
    setAudioPeaks(null);
    if (!connected) {
      setCameraMessage("Start the ollo server to use a server camera.");
      return;
    }
    setBusy(true);
    setCameraMessage("");
    try {
      setState(
        await request("/source", {
          source_type: "server_camera",
          camera: cameraSpec.trim(),
        }),
      );
      setState(await request("/session/start", {}));
      stream.current?.getTracks().forEach((t) => t.stop());
      if (source.startsWith("blob:")) URL.revokeObjectURL(source);
      setSource("");
      setServerFrame("");
      setSourceType("server");
      setRoom(0);
      setPosition(0);
      setPlaying(true);
      setAnalysisReady(true);
      setSourceOpen(false);
      notify("Server camera connected. Analysis continues when this tab is hidden.");
    } catch (e) {
      setCameraMessage(e instanceof Error ? e.message : "Could not connect the camera");
    }
    setBusy(false);
  }
  async function togglePlay() {
    if (room === 2) return;
    endCatchUp();
    const next = !playing;
    if (next) setExplicitIncident(null);
    setPlaying(next);
    if (video.current) {
      if (next) video.current.play().catch(() => {});
      else video.current.pause();
    }
    if (connected) {
      try {
        setState(await request(`/session/${next ? "start" : "pause"}`, next && video.current ? { media_time_ms: Math.round(video.current.currentTime * 1000) } : {}));
        seq.current = 0;
      } catch {
        setAnalysisReady(false);
      }
    }
  }
  function seekPlayback(seconds: number) {
    if (isLiveFeed) return;
    endCatchUp();
    setExplicitIncident(null);
    setPlaying(false);
    setPosition(seconds);
    if (video.current) {
      video.current.pause();
      video.current.currentTime = seconds;
    }
  }
  usePlaybackShortcuts({
    enabled: !signedOut && page === "monitor" && !sourceOpen && !report && !scenarioOpen && !calibrating && !drawing && !rulesOpen && !window.location.pathname.startsWith("/respond/"),
    position, duration, playing,
    onToggle: () => { void togglePlay(); },
    onPause: () => { setPlaying(false); video.current?.pause(); },
    onSeek: seekPlayback,
    onMute: () => { if (state.session.audio_permitted === true) setMuted(m => !m); },
    onFullscreen: () => {
      if (document.fullscreenElement) void document.exitFullscreen().catch(() => {});
      else void stage.current?.requestFullscreen?.().catch(() => {});
    },
    onLayout: setCameraLayout,
    incidents: timelineMarkers,
    onForward: () => { if (!isLiveFeed) { setExplicitIncident(null); setPlaying(true); void video.current?.play().catch(() => {}); } },
  });
  async function reset() {
    audioFile.current = null;
    setAudioPeaks(null);
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
  if (signedOut) return <div className="workspace-closed"><Brand /><h1>Workspace closed</h1><button className="button primary" onClick={() => { sessionStorage.removeItem("nestwatch-workspace-closed"); setSignedOut(false); setPage("monitor"); }}>Open local workspace</button></div>;
  if (mobileId) {
    const incident = state.incidents.find((i) => i.id === mobileId);
    return (
      <div className="mobile-response">
        <Navbar accountName={state.caregivers[0]?.name || "Local operator"} connected={connected} notifications={state.incidents} />
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
              {incident.assigned_responder &&
                ["acknowledged", "resolved"].includes(incident.status) && (
                  <p className="mobile-owner">
                    Handled by {incident.assigned_responder} via{" "}
                    {incident.acknowledged_via || "dashboard"}
                  </p>
                )}
              <p className="muted">
                Acknowledging means you are responding. Resolve only after
                checking the room.
              </p>
              {incident.status === "open" ? (
                <button
                  className="button primary full"
                  onClick={() => action(incident.id, "acknowledge", "app")}
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
              {incident.status === "open" && (
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
    <div className={`app-shell ${page === "monitor" ? "editor-workspace" : ""}`}>
      <main className="main">
        <Navbar
          layout={cameraLayout}
          onLayout={page === "monitor" ? setCameraLayout : undefined}
          accountName={state.caregivers[0]?.name || "Local operator"}
          connected={connected}
          notifications={state.incidents}
          onNavigate={setPage}
          onSignOut={() => {
            sessionStorage.setItem("nestwatch-workspace-closed", "true");
            setPlaying(false);
            video.current?.pause();
            setSource("");
            setSourceType("illustration");
            setAnalysisReady(false);
            setSignedOut(true);
          }}
        />
        {page === "monitor" ? (
          <>

            <ResizableWorkspace>
              <div className="monitor-column">
                <div className={`camera-layout layout-${cameraLayout}`}>
                <CameraCard rooms={rooms} camera={room} order={cameraLayout === "grid" ? room : undefined} onSelect={index => { setRoom(index); setOpenedThreadId(null); setSelectedNoteId(null); }} status={room === 2 ? "Offline" : room === 0 && sourceType !== "illustration" ? isLiveFeed ? "Live" : "Recorded" : undefined}>
                  <div
                    className={`camera-stage ${state.camera.health === "offline" ? "offline" : ""}`}
                    ref={stage}
                  >
                    {room === 2 ? <LiveCameraPlaceholder /> : room === 0 ? (
                      <>
                        {source || sourceType === "webcam" ? (
                          <video
                            ref={attachVideo}
                            src={source || undefined}
                            autoPlay
                            playsInline
                            muted={muted || state.session.audio_permitted !== true}
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
                            onSeeked={(e) => {
                              seq.current = 0;
                              if (connected && analysisReady)
                                request<LookoutState>("/session/start", { media_time_ms: Math.round(e.currentTarget.currentTime * 1000) })
                                  .then(setState)
                                  .catch(() =>
                                    notify(
                                      "Could not reset analysis after seeking",
                                    ),
                                  );
                            }}
                          />
                        ) : sourceType === "server" ? (
                          serverFrame ? (
                            <img
                              className="server-frame"
                              src={serverFrame}
                              alt="Server camera picture"
                              onLoad={(e) =>
                                setMediaAspect(
                                  e.currentTarget.naturalWidth /
                                    e.currentTarget.naturalHeight,
                                )
                              }
                            />
                          ) : (
                            <div className="server-frame waiting">
                              Connecting to {state.camera.capture?.source || "the camera"}…
                            </div>
                          )
                        ) : (
                          <DemoScene room={room} zones={zones && canUseStaffUI} position={position} />
                        )}
                        <div className="camera-shade" />
                        <div className="on-video-top">
                          {sourceType !== "illustration" && (
                            <div className="source-badge">
                              <span
                                className={`status-dot ${state.camera.health === "offline" ? "red" : ""}`}
                              />
                              {state.camera.health === "offline"
                                ? "Analysis unavailable"
                                : catchingUp
                                  ? "Analyzing… playback waits"
                                  : !analysisReady
                                  ? "Local playback"
                                  : state.camera.health === "degraded"
                                    ? "Analysis delayed"
                                    : state.session.status === "active"
                                      ? "Monitoring active"
                                      : "Analysis paused"}
                              <span className="island-divider" />
                              <span>
                                {sourceType === "server"
                                  ? "Server capture"
                                  : connected
                                    ? "Frame stream"
                                    : "Local playback"}
                              </span>
                            </div>
                          )}

                        </div>
                        {sourceType !== "illustration" && (
                          <div
                            className={`real-video-overlay ${calibrating || drawing ? "calibrating" : ""}`}
                            style={mediaRect}
                            onClick={(e) => {
                              if (!calibrating && !drawing) return;
                              const r = e.currentTarget.getBoundingClientRect();
                              const u = (e.clientX - r.left) / r.width,
                                v = (e.clientY - r.top) / r.height;
                              if (u < 0 || u > 1 || v < 0 || v > 1) return;
                              if (drawing)
                                setDrawPoints((points) =>
                                  points.length >= 12 ? points : [...points, { u, v }],
                                );
                              else
                                setCalPoints((points) =>
                                  points.length >= 20
                                    ? points
                                    : [...points, { u, v, x: "", y: "" }],
                                );
                            }}
                          >
                            <svg
                              className="approach-paths"
                              viewBox="0 0 1000 1000"
                              preserveAspectRatio="none"
                            >
                              {landmarks
                                .filter(
                                  (l) =>
                                    rulesOpen ||
                                    draftLandmarks.has(l.id) ||
                                    (zones && ruleLandmarks.has(l.id)),
                                )
                                .map((l) => (
                                  <polygon
                                    key={l.id}
                                    className={`landmark-shape ${draftLandmarks.has(l.id) ? "draft" : ruleLandmarks.has(l.id) ? "ruled" : ""}`}
                                    points={l.vertices
                                      .map((v) => `${v[0] * 1000},${v[1] * 1000}`)
                                      .join(" ")}
                                    vectorEffect="non-scaling-stroke"
                                  />
                                ))}
                              {drawing && drawPoints.length > 1 && (
                                <polyline
                                  className="landmark-shape draft"
                                  points={drawPoints
                                    .map((p) => `${p.u * 1000},${p.v * 1000}`)
                                    .join(" ")}
                                  vectorEffect="non-scaling-stroke"
                                />
                              )}
                              {visibleOverlays.map((o, i) =>
                                o.keypoints ? (
                                  <g key={`sk-${o.id || i}`} className="skeleton">
                                    {LIMBS.filter(
                                      ([a, b]) =>
                                        (o.keypoints![a]?.[2] ?? 0) >= 0.4 &&
                                        (o.keypoints![b]?.[2] ?? 0) >= 0.4,
                                    ).map(([a, b]) => (
                                      <line
                                        key={`${a}-${b}`}
                                        x1={o.keypoints![a][0] * 1000}
                                        y1={o.keypoints![a][1] * 1000}
                                        x2={o.keypoints![b][0] * 1000}
                                        y2={o.keypoints![b][1] * 1000}
                                        vectorEffect="non-scaling-stroke"
                                      />
                                    ))}
                                  </g>
                                ) : null,
                              )}
                              {visibleOverlays.map((o, i) =>
                                o.approach?.warning && o.approach.path ? (
                                  <line
                                    key={o.id || i}
                                    x1={o.approach.path[0][0] * 1000}
                                    y1={o.approach.path[0][1] * 1000}
                                    x2={o.approach.path[1][0] * 1000}
                                    y2={o.approach.path[1][1] * 1000}
                                    stroke="var(--status-open)"
                                    strokeWidth="2"
                                    strokeDasharray="6 4"
                                    vectorEffect="non-scaling-stroke"
                                  />
                                ) : null,
                              )}
                            </svg>
                            {visibleOverlays.map((o, i) =>
                              o.approach?.warning && o.approach.path ? (
                                <span
                                  key={`end-${o.id || i}`}
                                  className="approach-end"
                                  style={{
                                    left: `${o.approach.path[1][0] * 100}%`,
                                    top: `${o.approach.path[1][1] * 100}%`,
                                  }}
                                />
                              ) : null,
                            )}
                            {landmarks
                              .filter(
                                (l) =>
                                  rulesOpen ||
                                  draftLandmarks.has(l.id) ||
                                  (zones && ruleLandmarks.has(l.id)),
                              )
                              .map((l) => (
                                <span
                                  key={`name-${l.id}`}
                                  className="landmark-name"
                                  style={{
                                    left: `${(l.vertices.reduce((a, v) => a + v[0], 0) / l.vertices.length) * 100}%`,
                                    top: `${(l.vertices.reduce((a, v) => a + v[1], 0) / l.vertices.length) * 100}%`,
                                  }}
                                >
                                  {l.name}
                                </span>
                              ))}
                            {drawing &&
                              drawPoints.map((p, i) => (
                                <span
                                  key={`draw-${i}`}
                                  className="cal-point"
                                  style={{ left: `${p.u * 100}%`, top: `${p.v * 100}%` }}
                                >
                                  {i + 1}
                                </span>
                              ))}
                            {calibrating &&
                              calPoints.map((p, i) => (
                                <span
                                  key={`cal-${i}`}
                                  className="cal-point"
                                  style={{
                                    left: `${p.u * 100}%`,
                                    top: `${p.v * 100}%`,
                                  }}
                                >
                                  {i + 1}
                                </span>
                              ))}
                            {zones && (state.settings.zone as { enabled?: boolean } | undefined)?.enabled !== false && (
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
                                  fill="var(--primary-soft)"
                                  stroke="var(--status-resolved)"
                                  strokeWidth="2"
                                  strokeDasharray="7 5"
                                  vectorEffect="non-scaling-stroke"
                                />
                              </svg>
                            )}
                            {visibleOverlays.map((o, i) => (
                              <div
                                key={o.id || i}
                                className={`tracking-box ${o.approach?.warning ? "approaching" : ""}`}
                                style={{
                                  left: `${o.x * 100}%`,
                                  top: `${o.y * 100}%`,
                                  width: `${o.width * 100}%`,
                                  height: `${o.height * 100}%`,
                                }}
                              >
                                <span>
                                  {o.approach?.warning
                                    ? `${o.label.split(" · ")[0]} · Restricted area in ~${o.approach.eta_s ?? 3} s`
                                    : o.label}
                                </span>
                              </div>
                            ))}
                          </div>
                        )}
                        {floorOpen && sourceType !== "illustration" && (
                          <div className="floor-plan">
                            <span className="floor-plan-title">Floor plan · meters</span>
                            {state.floor_plan ? (
                              <FloorPlan plan={state.floor_plan} people={visibleOverlays} />
                            ) : (
                              <p>
                                Calibrate the floor to see the floor plan (ruler
                                button).
                              </p>
                            )}
                          </div>
                        )}
                        {rulesOpen && (
                          <div className="calibration-panel rules-panel">
                            <strong>Rules</strong>
                            <p>
                              Describe a rule in your own words. Claude drafts
                              it; nothing is enforced until you confirm.
                            </p>
                            <div className="rule-compose">
                              <input
                                aria-label="Describe a rule"
                                placeholder="Keep kids away from the kitchen gate during nap time"
                                value={ruleText}
                                maxLength={300}
                                onChange={(e) => setRuleText(e.target.value)}
                                onKeyDown={(e) => {
                                  if (e.key === "Enter" && ruleText.trim().length >= 3 && !ruleBusy)
                                    draftRule();
                                }}
                              />
                              <button
                                className="button light"
                                disabled={ruleText.trim().length < 3 || ruleBusy}
                                onClick={draftRule}
                              >
                                {ruleBusy ? "Drafting…" : "Draft"}
                              </button>
                            </div>
                            {ruleMessage && (
                              <p className="calibration-message">{ruleMessage}</p>
                            )}
                            {rules.length > 0 && (
                              <ul className="rule-list">
                                {rules.map((r) => (
                                  <li key={r.id} className={r.status}>
                                    <div>
                                      <span>{r.summary}</span>
                                      <small>
                                        {landmarks.find((l) => l.id === r.landmark_id)?.name} ·{" "}
                                        {scheduleLabel(r)} · {r.severity} ·{" "}
                                        {r.status === "draft" ? "draft, not enforced" : "active"}
                                      </small>
                                    </div>
                                    {r.status === "draft" && (
                                      <button
                                        className="button light"
                                        onClick={() =>
                                          ruleAction(
                                            () => request(`/rules/${r.id}/confirm`, {}),
                                            "Rule confirmed and active.",
                                          )
                                        }
                                      >
                                        Confirm
                                      </button>
                                    )}
                                    <button
                                      className="button"
                                      aria-label={`Remove rule: ${r.summary}`}
                                      onClick={() =>
                                        ruleAction(
                                          () => request(`/rules/${r.id}`, undefined, "DELETE"),
                                          "Rule removed.",
                                        )
                                      }
                                    >
                                      {r.status === "draft" ? "Discard" : "Remove"}
                                    </button>
                                  </li>
                                ))}
                              </ul>
                            )}
                            <strong className="panel-subhead">Landmarks</strong>
                            {landmarks.length ? (
                              <ul className="rule-list">
                                {landmarks.map((l) => (
                                  <li key={l.id}>
                                    <div>
                                      <span>{l.name}</span>
                                    </div>
                                    <button
                                      className="button"
                                      aria-label={`Remove landmark ${l.name}`}
                                      onClick={() =>
                                        ruleAction(
                                          () => request(`/landmarks/${l.id}`, undefined, "DELETE"),
                                          `Landmark "${l.name}" removed with its rules.`,
                                        )
                                      }
                                    >
                                      Remove
                                    </button>
                                  </li>
                                ))}
                              </ul>
                            ) : (
                              <p className="calibration-empty">
                                No landmarks yet. Draw the places your rules
                                refer to, like a gate or the stairs.
                              </p>
                            )}
                            {drawing ? (
                              <div className="landmark-draw">
                                <p>
                                  Click 3 or more points around the place on the
                                  video, then name it.
                                </p>
                                <input
                                  aria-label="Landmark name"
                                  placeholder="Kitchen gate"
                                  value={landmarkName}
                                  maxLength={40}
                                  onChange={(e) => setLandmarkName(e.target.value)}
                                />
                                <div className="calibration-actions">
                                  <button
                                    className="button light"
                                    disabled={drawPoints.length < 3 || !landmarkName.trim()}
                                    onClick={saveLandmark}
                                  >
                                    Save landmark
                                  </button>
                                  <button
                                    className="button"
                                    onClick={() => setDrawPoints((p) => p.slice(0, -1))}
                                    disabled={!drawPoints.length}
                                  >
                                    Undo point
                                  </button>
                                  <button
                                    className="button"
                                    onClick={() => {
                                      setDrawing(false);
                                      setDrawPoints([]);
                                    }}
                                  >
                                    Cancel
                                  </button>
                                </div>
                              </div>
                            ) : (
                              <div className="calibration-actions">
                                <button className="button" onClick={() => setDrawing(true)}>
                                  Draw landmark
                                </button>
                                <button className="button" onClick={() => setRulesOpen(false)}>
                                  Close
                                </button>
                              </div>
                            )}
                          </div>
                        )}
                        {calibrating && (
                          <div className="calibration-panel">
                            <strong>Floor calibration</strong>
                            <p>
                              Click spots on the floor you can measure, such as
                              tape marks or tile corners. Enter each one's
                              position in meters from one corner of the room.
                              Use 5 or more points so a mistyped measurement
                              can be caught.
                            </p>
                            {calPoints.length ? (
                              <ol>
                                {calPoints.map((p, i) => (
                                  <li key={i}>
                                    <span>{i + 1}</span>
                                    <label>
                                      X m
                                      <input
                                        type="number"
                                        step="0.1"
                                        value={p.x}
                                        aria-label={`Point ${i + 1} X in meters`}
                                        onChange={(e) =>
                                          setCalPoints((points) =>
                                            points.map((q, j) =>
                                              j === i ? { ...q, x: e.target.value } : q,
                                            ),
                                          )
                                        }
                                      />
                                    </label>
                                    <label>
                                      Y m
                                      <input
                                        type="number"
                                        step="0.1"
                                        value={p.y}
                                        aria-label={`Point ${i + 1} Y in meters`}
                                        onChange={(e) =>
                                          setCalPoints((points) =>
                                            points.map((q, j) =>
                                              j === i ? { ...q, y: e.target.value } : q,
                                            ),
                                          )
                                        }
                                      />
                                    </label>
                                    <button
                                      aria-label={`Remove point ${i + 1}`}
                                      onClick={() =>
                                        setCalPoints((points) =>
                                          points.filter((_, j) => j !== i),
                                        )
                                      }
                                    >
                                      <X size={12} />
                                    </button>
                                  </li>
                                ))}
                              </ol>
                            ) : (
                              <p className="calibration-empty">
                                No points yet. Click the floor on the video.
                              </p>
                            )}
                            {calMessage && (
                              <p className="calibration-message">{calMessage}</p>
                            )}
                            <div className="calibration-actions">
                              <button
                                className="button light"
                                disabled={!calibrationReady}
                                onClick={saveCalibration}
                              >
                                Save
                              </button>
                              {savedCalibration && (
                                <button className="button" onClick={clearCalibration}>
                                  Remove saved
                                </button>
                              )}
                              <button
                                className="button"
                                onClick={() => setCalibrating(false)}
                              >
                                Close
                              </button>
                            </div>
                          </div>
                        )}
                        {state.camera.health === "offline" && (
                          <div className="offline-message">
                            <WifiOff size={28} />
                            <h3>Analysis unavailable</h3>
                            {sourceType === "server" ? (
                              <>
                                <p>
                                  No new frames from{" "}
                                  {state.camera.capture?.source ||
                                    state.session.camera_label ||
                                    "the camera"}
                                  . Reconnecting automatically. Monitoring
                                  cannot be confirmed.
                                </p>
                                <button
                                  className="button"
                                  onClick={() => {
                                    setCameraMessage("");
                                    setSourceOpen(true);
                                  }}
                                >
                                  Choose a source
                                </button>
                              </>
                            ) : (
                              <>
                                <p>
                                  Check the camera connection. Monitoring cannot
                                  be confirmed.
                                </p>
                                <button
                                  className="button"
                                  onClick={() => scenario("normal")}
                                >
                                  Restore demo
                                </button>
                              </>
                            )}
                          </div>
                        )}
                        {sourceType !== "illustration" &&
                          state.session.status === "active" &&
                          state.camera.analysis_fps !== undefined && (
                            <div className="video-footer">
                              <span
                                className={
                                  state.camera.analysis_fps < 8 ||
                                  state.camera.health === "offline"
                                    ? "analysis-rate low"
                                    : "analysis-rate"
                                }
                                title={
                                  state.camera.analysis_fps < 8
                                    ? `Rhythmic-movement checks need at least 8 analyzed frames per second.${sourceType === "server" ? "" : " Keep this tab visible."}`
                                    : sourceType === "server"
                                      ? "Frames analyzed per second by the server, whether or not this tab is visible"
                                      : "Frames analyzed per second on this computer"
                                }
                              >
                                {state.camera.detector === "pose"
                                  ? "Pose"
                                  : "Person"}{" "}
                                ·{" "}
                                {state.camera.health === "offline"
                                  ? "no frames"
                                  : `${state.camera.analysis_fps.toFixed(1)} fps`}
                              </span>
                            </div>
                          )}
                      </>
                    ) : (
                      <>
                        <DemoScene room={room} zones={zones && canUseStaffUI} position={position} />
                        <div className="camera-shade" />
                      </>
                    )}

                    {room !== 2 && <FullscreenControls live={isLiveFeed} stage={stage} position={position} duration={duration} playing={playing} muted={muted || state.session.audio_permitted !== true} onToggle={() => { void togglePlay(); }} onMute={() => setMuted(m => !m)} onSeek={seekPlayback} />}
                  </div>

                </CameraCard>
                {cameraLayout !== "single" && <div className="additional-cameras">
                  {rooms.map((camera, index) => index !== room && <CameraCard key={camera.id} rooms={rooms} camera={index} order={cameraLayout === "grid" ? index : undefined} onSelect={selected => { setRoom(selected); setOpenedThreadId(null); setSelectedNoteId(null); }} status={index === 2 ? "Offline" : index === 0 && sourceType !== "illustration" ? isLiveFeed ? "Live" : "Recorded" : undefined}>
                    <div className="camera-stage">
                      <button className="camera-preview-content" onClick={() => { setRoom(index); setOpenedThreadId(null); setSelectedNoteId(null); }} aria-label={`Focus ${camera.name}`}>
                        {index === 2 ? <LiveCameraPlaceholder /> : index === 0 && sourceType !== "illustration" ? serverFrame && sourceType === "server" ? <img src={serverFrame} alt="Current server camera preview" /> : <div className="preview-source-placeholder"><Video size={24} /><span>{sourceType === "webcam" ? "Webcam connected" : "Video source connected"}</span><small>Select to view and control</small></div> : <DemoScene room={index} zones={zones && canUseStaffUI} position={position} />}
                      </button>
                    </div>
                  </CameraCard>)}
                  {cameraLayout === "grid" ? <div className="empty-camera-slot" aria-label="Empty camera slot 4" /> : <button className="add-camera-tile" onClick={() => { setCameraMessage(""); setSourceOpen(true); }}><Plus size={20} /><strong>Connect a camera</strong><span>RTSP or HTTP stream</span><small>One analyzed source at a time</small></button>}
                </div>}
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
                          disabled={room === 2}
                          title="Play / pause (Space)"
                          aria-keyshortcuts="Space"
                        >
                          {playing ? (
                            <Pause size={16} fill="currentColor" />
                          ) : (
                            <Play size={16} fill="currentColor" />
                          )}
                        </button>
                        <PlaybackTime position={position} duration={duration} live={isLiveFeed} disabled={room === 2} onSeek={seekPlayback} />
                        {!isLiveFeed && <span className="speed">1×</span>}
                      </div>
                    <div className="camera-floating-actions" aria-label="Camera controls">
                      <button className={`icon-button ${zones ? "enabled" : ""}`} aria-label="Toggle zone overlay" aria-pressed={zones} title="Toggle zone overlay" onClick={() => setZones(!zones)}><Focus size={14} /></button>
                      <button className="icon-button" aria-label="Fullscreen camera" title="Fullscreen" onClick={() => stage.current?.requestFullscreen?.()}><Maximize2 size={14} /></button>
                    </div>

                    </div>
                    <EditorTimeline
                      camera={`${rooms[room].name} · ${rooms[room].id}`}
                      room={room}
                      duration={timelineDuration}
                      position={position}
                      playing={room === 2 ? false : playing}
                      live={isLiveFeed}
                      liveDisconnected={room === 2}
                      demo={room !== 2 && (room !== 0 || sourceType === "illustration")}
                      audioPermitted={state.session.audio_permitted === true}
                      peaks={state.session.audio_permitted === true ? audioPeaks : null}
                      video={video}
                      selectedId={selectedIncident}
                      hoveredId={hoveredIncident}
                      recordingStartedAt={recordingStartedAt}

                      markers={timelineMarkers}
                      onSeek={(seconds, marker?: TimelineMarker) => {
                        setExplicitIncident(marker?.id ?? null);
                        if (marker) openIncidentThread(marker.id, marker.noteId);
                        if (isLiveFeed) return;
                        setPlaying(false);
                        setPosition(seconds);
                        if (video.current) {
                          video.current.pause();
                          video.current.currentTime = seconds;
                        }
                      }}
                    />
                  </div>
              </div>
              <div className="monitor-side-panel">
                <details className="sidebar-section" open><summary>Date</summary>
                <MonitoringControls compact date={reviewDate} onDate={setReviewDate} footageDates={new Set([...(recordingStartedAt ? [dateKey(new Date(recordingStartedAt))] : []), ...mockIncidents.map(i => incidentDate(i.opened_at))])} openIncidentDates={new Set((sourceType === "illustration" ? mockIncidents : state.incidents).filter(i => i.status === "open").map(i => incidentDate(i.opened_at)))} eventDates={new Set((room !== 0 || sourceType === "illustration" ? mockIncidents : state.incidents).map(i => incidentDate(i.opened_at)))} />
                </details>
                <details className="sidebar-section sidebar-events" open><summary>Incidents<span>{traceState.incidents.length.toString().padStart(2, "0")}</span></summary>
              <EventTrace
                state={traceState}
                threads={incidentThreads}
                openedId={openedThreadId}
                selectedNoteId={selectedNoteId}
                position={position}
                canSeek={!isLiveFeed}
                canAnnotate={canUseStaffUI}
                onOpen={openIncidentThread}
                onBack={() => { setOpenedThreadId(null); setSelectedNoteId(null); }}
                onJump={(seconds) => { if (isLiveFeed) return; setPosition(seconds); setPlaying(true); if (video.current) { video.current.currentTime = seconds; void video.current.play().catch(() => setPlaying(false)); } }}
                onAddNote={(id, draft) => {
                  const message = addIncidentNote({ ...draft, incidentId: id, cameraId: rooms[room].id, userId: form.primary_name, authorName: form.primary_name });
                  setThreadChanges(current => ({ ...current, [id]: { ...current[id], messages: [...(current[id]?.messages ?? []), message], lastReadAt: message.at } }));
                }}
                onResolve={(id, outcome) => {
                  const { resolution, message } = resolveIncidentThread({ incidentId: id, cameraId: rooms[room].id, userId: form.primary_name, outcome });
                  setThreadChanges(current => ({ ...current, [id]: { ...current[id], messages: [...(current[id]?.messages ?? []), message], resolution, lastReadAt: message.at } }));
                }}
                room={room}
                selected={selectedIncident}
                recordingStartedAt={recordingStartedAt}
                userId={form.primary_name}
                cameraId={rooms[room].id}
                cameraThumbnail={sourceType === "illustration" || room === 1 ? rooms[room].image : serverFrame || undefined}
                onHover={setHoveredIncident}
                onSelect={setExplicitIncident}
                onAction={action}
                onSeek={(time) => {
                  if (isLiveFeed) return;
                  setPlaying(false);
                  setPosition(time);
                  if (video.current) {
                    video.current.pause();
                    video.current.currentTime = time;
                  }
                }}
                onReport={async (id) => {
                  try {
                    const r = await request<{
                      markdown: string;
                      source: "claude" | "facts";
                      removed_lines: number;
                    }>(`/incidents/${id}/report`, undefined, "GET");
                    setReport({ id, ...r });
                  } catch (e) {
                    notify(e instanceof Error ? e.message : "Report unavailable");
                  }
                }}
              />
                </details>


              </div>

            </ResizableWorkspace>
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
                    a.download = "ollo-incidents.json";
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
            <div className="eyebrow">MAKE NESTWATCH YOURS</div>
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
                      <p>Prerecorded video, browser webcam, or a camera the server reads</p>
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
                        } catch (e) {
                          notify(
                            e instanceof Error && e.message.includes("cannot reach") ? e.message : "Configure calling credentials and allowlisted teammates first.",
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
                      <strong>Claude second opinion</strong>
                      <p>
                        After a local alert, send up to 4 face-blurred crops of
                        that person to the configured Claude model for context.
                        Never delays or cancels an alert. Nothing is sent while
                        nothing happens.
                        {state.analysis?.cloud?.requests
                          ? ` This session: ${state.analysis.cloud.requests} review${state.analysis.cloud.requests === 1 ? "" : "s"}${state.analysis.cloud.cost_known ? ` · $${state.analysis.cloud.cost_usd.toFixed(4)}` : ""}.`
                          : ""}
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
                      Alerts come from local rules on this computer. Video
                      cannot establish airway status or confirm that a child
                      is safe.
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
      {report && (
        <div className="modal-backdrop" onClick={() => setReport(null)}>
          <div
            className="source-modal report-modal"
            role="dialog"
            aria-modal="true"
            aria-label="Incident report"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="modal-top">
              <span className="eyebrow">
                {report.source === "claude"
                  ? "WRITTEN BY CLAUDE · EVERY LINE CITES LOGGED FACTS"
                  : "PLAIN TIMELINE FROM LOGGED FACTS"}
              </span>
              <button
                className="icon-button"
                aria-label="Close report"
                onClick={() => setReport(null)}
              >
                <X size={18} />
              </button>
            </div>
            {report.removed_lines > 0 && (
              <p className="muted">
                {report.removed_lines} line{report.removed_lines === 1 ? "" : "s"}{" "}
                removed for missing evidence or diagnosis language.
              </p>
            )}
            <pre className="report-text">{report.markdown}</pre>
            <div className="calibration-actions">
              <button
                className="button light"
                onClick={() => {
                  const url = URL.createObjectURL(
                    new Blob([report.markdown], { type: "text/markdown" }),
                  );
                  const a = document.createElement("a");
                  a.href = url;
                  a.download = `ollo-incident-${report.id.slice(0, 8)}.md`;
                  a.click();
                  URL.revokeObjectURL(url);
                }}
              >
                <Download size={14} /> Download .md
              </button>
              <button className="button" onClick={() => setReport(null)}>
                Close
              </button>
            </div>
          </div>
        </div>
      )}
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
            <form
              className="server-camera"
              onSubmit={(e) => {
                e.preventDefault();
                serverCamera();
              }}
            >
              <div className="source-option">
                <Cctv size={20} />
                <span>
                  Camera read by the ollo server
                  <small>
                    Webcam index or RTSP/HTTP stream · analysis continues when
                    this tab is hidden
                  </small>
                </span>
              </div>
              <div className="server-camera-row">
                <input
                  aria-label="Camera index or stream URL"
                  placeholder="0, or rtsp://camera.local/stream"
                  value={cameraSpec}
                  onChange={(e) => setCameraSpec(e.target.value)}
                />
                <button
                  className="button"
                  type="submit"
                  disabled={busy || !cameraSpec.trim()}
                >
                  Connect
                </button>
              </div>
              {cameraMessage && (
                <p className="server-camera-message" role="alert">
                  {cameraMessage}
                </p>
              )}
            </form>
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
