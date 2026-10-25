import AudioWaveform from "./AudioWaveform";
import { clockTime } from "./timecode";
import TimelineOverview from "./TimelineOverview";
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type RefObject } from "react";
import { Pin, Video } from "lucide-react";

export type TimelineMarker = { id: string; time: number; endTime?: number; title: string; status?: string; demo?: boolean; noteId?: string; notes?: { id: string; time: number; title: string }[] };
const timecode = (s: number) => `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

// Synthetic room ambience: clustered speech, pauses and occasional transients.
// Seeded once per room so zooming and scrubbing do not change the illustration.
function demoWaveform(seed: number) {
  let noise = seed + 17;
  const random = () => { noise = (noise * 1664525 + 1013904223) >>> 0; return noise / 4294967296; };
  const phrases = Array.from({ length: 34 }, () => ({ start: random(), length: .008 + random() * .035, gain: .15 + random() * .6, cadence: 3 + random() * 8, phase: random() * Math.PI }));
  const transients = Array.from({ length: 18 }, () => ({ at: random(), gain: .25 + random() * .6 }));
  return Array.from({ length: 2400 }, (_, index) => {
    const t = index / 2400;
    let energy = .025 + random() * .025;
    for (const phrase of phrases) {
      const x = (t - phrase.start) / phrase.length;
      if (x > 0 && x < 1) energy += phrase.gain * Math.sin(Math.PI * x) ** 1.5 * (.12 + .88 * Math.abs(Math.sin(x * phrase.cadence * Math.PI + phrase.phase)) ** 2);
    }
    for (const transient of transients) energy += transient.gain * Math.exp(-Math.abs(t - transient.at) / .0009);
    return Math.min(.96, energy * (.55 + random() * .45));
  });
}

export default function EditorTimeline({ camera, room, duration, position, playing, demo, audioPermitted = false, peaks, video, markers, selectedId, hoveredId, recordingStartedAt, live = false, liveDisconnected = false, onSeek }: {
  camera: string; room: number; duration: number; position: number; playing: boolean; demo: boolean;
  audioPermitted?: boolean;
  peaks: number[] | null; video: RefObject<HTMLVideoElement | null>; markers: TimelineMarker[];
  selectedId?: string | null;
  hoveredId?: string | null;
  recordingStartedAt?: string;
  liveDisconnected?: boolean;
  live?: boolean;
  onSeek: (seconds: number, marker?: TimelineMarker) => void;
}) {
  const playhead = useRef<HTMLDivElement>(null);
  const timeline = useRef<HTMLDivElement>(null);
  const viewport = useRef<HTMLDivElement>(null);
  const [scrubbing, setScrubbing] = useState(false);
  const [view, setView] = useState({ start: 0, span: live ? 1 : Math.min(1, 1800 / Math.max(1, duration)) });
  useEffect(() => { setView({ start: 0, span: live ? 1 : Math.min(1, 1800 / Math.max(1, duration)) }); }, [live ? 0 : duration, room, recordingStartedAt, live]);
  const [rulerWidth, setRulerWidth] = useState(800);
  useEffect(() => {
    if (!timeline.current) return;
    const observer = new ResizeObserver(([entry]) => setRulerWidth(entry.contentRect.width));
    observer.observe(timeline.current);
    return () => observer.disconnect();
  }, [liveDisconnected]);
  useLayoutEffect(() => {
    if (viewport.current) viewport.current.scrollLeft = view.start * viewport.current.clientWidth / view.span;
  }, [view.start, view.span, rulerWidth]);
  useEffect(() => {
    const element = viewport.current;
    if (!element) return;
    const wheel = (event: WheelEvent) => {
      const delta = event.deltaX || (event.shiftKey ? event.deltaY : 0);
      if (!delta) return;
      event.preventDefault();
      const max = element.scrollWidth - element.clientWidth;
      if (max <= 1 || (element.scrollLeft <= 0 && delta < 0) || (element.scrollLeft >= max - 1 && delta > 0)) {
        if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches) element.firstElementChild?.animate([{ transform: "translateX(0)" }, { transform: `translateX(${delta > 0 ? -4 : 4}px)` }, { transform: "translateX(0)" }], { duration: 180 });
      } else element.scrollLeft += delta;
    };
    element.addEventListener("wheel", wheel, { passive: false });
    return () => element.removeEventListener("wheel", wheel);
  }, [liveDisconnected]);
  const selection = selectedId;
  const clearAndSeek = (time: number, disableSnap = false) => {
    const edges = markers.flatMap(m => [m.time, m.endTime].filter((v): v is number => v !== undefined));
    const nearest = edges.sort((a, b) => Math.abs(a - time) - Math.abs(b - time))[0];
    onSeek(!disableSnap && nearest !== undefined && Math.abs(nearest - time) <= duration * view.span * 8 / rulerWidth ? nearest : time);
  };
  useEffect(() => {
    const marker = markers.find(m => m.id === selectedId);
    if (marker) setView(current => marker.time / safeDuration < current.start || marker.time / safeDuration > current.start + current.span ? { ...current, start: Math.max(0, Math.min(1 - current.span, marker.time / safeDuration - current.span / 4)) } : current);
  }, [selectedId]);
  const anchor = useRef({ position, at: performance.now() });
  const safeDuration = Number.isFinite(duration) && duration > 0 ? duration : 1;
  const targetInterval = safeDuration * view.span / Math.max(2, Math.min(6, Math.floor(rulerWidth / 180)));
  const interval = [.1, .2, .5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200].find(value => value >= targetInterval) ?? Math.ceil(targetInterval / 3600) * 3600;
  const minorInterval = interval / 5;
  const firstTick = Math.max(0, Math.floor(view.start * safeDuration / minorInterval));
  const lastTick = Math.min(Math.floor(safeDuration / minorInterval), Math.ceil((view.start + view.span) * safeDuration / minorInterval));
  const firstLabel = Math.max(0, Math.floor(view.start * safeDuration / interval));
  const lastLabel = Math.min(Math.floor(safeDuration / interval), Math.ceil((view.start + view.span) * safeDuration / interval));
  useEffect(() => { anchor.current = { position, at: performance.now() }; }, [position, playing, room]);
  useEffect(() => {
    let frame = 0;
    const draw = (now: number) => {
      const elapsed = playing ? (now - anchor.current.at) / 1000 : 0;
      const time = !demo && video.current ? video.current.currentTime : playing ? (anchor.current.position + elapsed) % safeDuration : anchor.current.position;
      if (playhead.current) playhead.current.style.left = live || liveDisconnected ? "100%" : `${Math.max(0, Math.min(100, time / safeDuration * 100))}%`;
      frame = requestAnimationFrame(draw);
    };
    frame = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(frame);
  }, [playing, safeDuration, demo, video, live, liveDisconnected]);
  const waveform = useMemo(() => demo ? demoWaveform(room * 923) : audioPermitted ? peaks : null, [audioPermitted, demo, room, peaks]);
  if (liveDisconnected) return <div className="editor-timeline live-timeline" aria-label={liveDisconnected ? "Live camera timeline, not connected" : "Live camera timeline"}>
    <div className="editor-ruler"><span>Live feed</span><span>{liveDisconnected ? "Waiting for signal" : "Live edge"}</span></div>
    <div className="editor-track"><div className="editor-clip"><div className="editor-clip-name"><Video size={12} /><strong>{camera}</strong><span className="live-feed-badge">LIVE</span></div><div className="live-timeline-waiting">{liveDisconnected ? "Not connected" : "Live video"}</div></div></div>
    <div className="editor-playhead live-playhead" ref={playhead} style={{ left: "100%" }} aria-label="Playhead at live edge"><span /></div>
  </div>;
  return <div className="editor-timeline" ref={timeline}>
    <TimelineOverview start={view.start} span={view.span} duration={safeDuration} onChange={(start, span) => setView({ start, span })} />
    <div className="timeline-viewport" ref={viewport} onScroll={event => {
      const element = event.currentTarget;
      const start = element.scrollLeft / (element.clientWidth / view.span);
      if (Math.abs(start - view.start) > .0001) setView(current => ({ ...current, start }));
    }}>
    <div className="timeline-content" style={{ width: `${100 / view.span}%` }}
      onPointerDown={e => {
        if (live || e.button !== 0) return;
        const target = e.target instanceof Element ? e.target : null;
        if (target?.closest("button, input, .editor-track-caption")) return;
        e.preventDefault();
        e.currentTarget.setPointerCapture(e.pointerId);
        setScrubbing(true);
        const bounds = e.currentTarget.getBoundingClientRect();
        clearAndSeek(Math.max(0, Math.min(1, (e.clientX - bounds.left) / bounds.width)) * safeDuration, e.altKey);
      }}
      onPointerMove={e => {
        if (!e.currentTarget.hasPointerCapture(e.pointerId)) return;
        const bounds = e.currentTarget.getBoundingClientRect();
        clearAndSeek(Math.max(0, Math.min(1, (e.clientX - bounds.left) / bounds.width)) * safeDuration, e.altKey);
      }}
      onLostPointerCapture={() => setScrubbing(false)} onPointerUp={e => { setScrubbing(false); if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId); }}
    >
    <div className="editor-ruler" aria-hidden="true">
      <div className="editor-ruler-ticks">{Array.from({ length: lastTick - firstTick + 1 }, (_, offset) => { const index = firstTick + offset; return <i key={index} className={index % 5 === 0 ? "major" : ""} style={{ left: `${index * minorInterval / safeDuration * 100}%` }} />; })}</div>
      {Array.from({ length: lastLabel - firstLabel + 1 }, (_, offset) => {
        const index = firstLabel + offset;
        const time = index * interval;
        return <span className={`ruler-label ${index === 0 ? "first" : time >= safeDuration - .00001 ? "last" : ""}`} key={index} style={{ left: `${time / safeDuration * 100}%` }}>{recordingStartedAt ? clockTime(recordingStartedAt, time, interval < 60, false) : interval < 1 ? `${time.toFixed(1)}s` : timecode(time)}</span>;
      })}
    </div>
    <div className="editor-track">
      <div className="editor-clip">
        <div className="editor-clip-name"><Video size={12} /><strong>{camera}</strong>{live && <span>LIVE</span>}</div>
        {waveform ? <AudioWaveform peaks={waveform} duration={safeDuration} illustrative={demo} /> : <div className="editor-no-audio">Audio waveform unavailable</div>}
      </div>
      <input disabled={live} type="range" className="editor-scrubber" aria-label="Video playback position" min="0" max={safeDuration} step="0.01" value={live ? safeDuration : Math.min(position, safeDuration)} onPointerDown={() => clearAndSeek(position)} onChange={e => clearAndSeek(Number(e.target.value))} />
      {markers.filter(m => m.time >= 0 && m.time <= safeDuration).map(marker => {
        const end = marker.endTime !== undefined && marker.endTime > marker.time ? Math.min(marker.endTime, safeDuration) : null;
        const selected = selection === marker.id || hoveredId === marker.id;
        return <div className={`editor-incident status-${marker.status ?? "open"}`} key={marker.id}>
          <button className={`editor-incident-range ${selected ? "selected" : ""}`} style={{ left: `${marker.time / safeDuration * 100}%`, width: `${Math.max((end ?? marker.time + 1) - marker.time, safeDuration * .004) / safeDuration * 100}%` }} onClick={() => onSeek(marker.time, marker)} aria-label={`Jump to ${marker.title} at ${timecode(marker.time)}`} title={marker.title}><span className="incident-fold" /></button>
          {marker.notes?.filter(note => note.time >= 0 && note.time <= safeDuration).map(note => <button key={note.id} className="timeline-note-pin" aria-label={`Open note: ${note.title}`} title={note.title} style={{ left: `${note.time / safeDuration * 100}%` }} onClick={() => onSeek(note.time, { ...marker, noteId: note.id })}><Pin size={12} /></button>)}
        </div>;
      })}
    </div>
    <div className="editor-playhead" ref={playhead} style={{ left: `${live ? 100 : position / safeDuration * 100}%` }} aria-hidden="true"><span />{scrubbing && <small className="scrub-bubble">{clockTime(recordingStartedAt, position)}</small>}</div>
    </div>
    </div>
  </div>;
}
