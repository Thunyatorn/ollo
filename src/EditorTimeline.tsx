import TimelineOverview from "./TimelineOverview";
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type RefObject } from "react";
import { AudioLines, TriangleAlert, Video } from "lucide-react";

export type TimelineMarker = { id: string; time: number; endTime?: number; title: string; demo?: boolean };
const timecode = (s: number) => `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

// Seeded envelopes keep illustrative room audio stable while scrubbing.
function demoWaveform(seed: number) {
  let noise = seed + 17;
  const random = () => { noise = (noise * 1664525 + 1013904223) >>> 0; return noise / 4294967296; };
  const bursts = Array.from({ length: 26 }, () => ({ center: random(), width: .003 + random() * .022, volume: .12 + random() * .8 }));
  return Array.from({ length: 480 }, (_, i) => {
    const t = i / 480;
    const envelope = bursts.reduce((sum, b) => sum + b.volume * Math.exp(-(((t - b.center) / b.width) ** 2)), .035);
    return Math.min(.98, envelope * (.18 + random() * .82));
  });
}

export default function EditorTimeline({ camera, room, duration, position, playing, demo, peaks, video, markers, selectedId, liveDisconnected = false, onSeek }: {
  camera: string; room: number; duration: number; position: number; playing: boolean; demo: boolean;
  peaks: number[] | null; video: RefObject<HTMLVideoElement | null>; markers: TimelineMarker[];
  selectedId?: string | null;
  liveDisconnected?: boolean;
  onSeek: (seconds: number, marker?: TimelineMarker) => void;
}) {
  const playhead = useRef<HTMLDivElement>(null);
  const timeline = useRef<HTMLDivElement>(null);
  const viewport = useRef<HTMLDivElement>(null);
  const [view, setView] = useState({ start: 0, span: 1 });
  useEffect(() => { setView({ start: 0, span: 1 }); }, [duration, room]);
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
        element.firstElementChild?.animate([{ transform: "translateX(0)" }, { transform: `translateX(${delta > 0 ? -4 : 4}px)` }, { transform: "translateX(0)" }], { duration: 180 });
      } else element.scrollLeft += delta;
    };
    element.addEventListener("wheel", wheel, { passive: false });
    return () => element.removeEventListener("wheel", wheel);
  }, [liveDisconnected]);
  const selection = selectedId;
  const clearAndSeek = (time: number) => onSeek(time);
  const anchor = useRef({ position, at: performance.now() });
  const safeDuration = Number.isFinite(duration) && duration > 0 ? duration : 120;
  const targetInterval = safeDuration * view.span / Math.max(2, Math.min(6, Math.floor(rulerWidth / 180)));
  const interval = [.1, .2, .5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200].find(value => value >= targetInterval) ?? Math.ceil(targetInterval / 3600) * 3600;
  const minorInterval = interval / 5;
  const tickCount = Math.floor(safeDuration / minorInterval + .00001);
  useEffect(() => { anchor.current = { position, at: performance.now() }; }, [position, playing, room]);
  useEffect(() => {
    let frame = 0;
    const draw = (now: number) => {
      const elapsed = playing ? (now - anchor.current.at) / 1000 : 0;
      const time = !demo && video.current ? video.current.currentTime : playing ? (anchor.current.position + elapsed) % safeDuration : anchor.current.position;
      if (playhead.current) playhead.current.style.left = `${Math.max(0, Math.min(100, time / safeDuration * 100))}%`;
      frame = requestAnimationFrame(draw);
    };
    frame = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(frame);
  }, [playing, safeDuration, demo, video]);
  const waveform = useMemo(() => demo ? demoWaveform(room * 923) : peaks, [demo, room, peaks]);
  const path = useMemo(() => waveform?.map((value, i) => {
    const x = (i / waveform.length) * 1200;
    const h = Math.max(.6, value * 17);
    return `M${x.toFixed(2)},${(20 - h).toFixed(2)}v${(h * 2).toFixed(2)}`;
  }).join(" "), [waveform]);
  if (liveDisconnected) return <div className="editor-timeline live-timeline" aria-label="Live camera timeline, not connected">
    <div className="editor-ruler"><span>Live feed</span><span>Waiting for signal</span></div>
    <div className="editor-track"><div className="editor-clip"><div className="editor-clip-name"><Video size={12} /><strong>{camera}</strong><span className="live-feed-badge">LIVE</span></div><div className="live-timeline-waiting">Not connected</div></div></div>
  </div>;
  return <div className="editor-timeline" ref={timeline}>
    <TimelineOverview start={view.start} span={view.span} onChange={(start, span) => setView({ start, span })} />
    <div className="timeline-viewport" ref={viewport} onScroll={event => {
      const element = event.currentTarget;
      const start = element.scrollLeft / (element.clientWidth / view.span);
      if (Math.abs(start - view.start) > .0001) setView(current => ({ ...current, start }));
    }}>
    <div className="timeline-content" style={{ width: `${100 / view.span}%` }}
      onPointerDown={e => {
        if (e.button !== 0) return;
        const target = e.target instanceof Element ? e.target : null;
        if (target?.closest("button, input, .editor-track-caption")) return;
        e.preventDefault();
        e.currentTarget.setPointerCapture(e.pointerId);
        const bounds = e.currentTarget.getBoundingClientRect();
        clearAndSeek(Math.max(0, Math.min(1, (e.clientX - bounds.left) / bounds.width)) * safeDuration);
      }}
      onPointerMove={e => {
        if (!e.currentTarget.hasPointerCapture(e.pointerId)) return;
        const bounds = e.currentTarget.getBoundingClientRect();
        clearAndSeek(Math.max(0, Math.min(1, (e.clientX - bounds.left) / bounds.width)) * safeDuration);
      }}
      onPointerUp={e => { if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId); }}
    >
    <div className="editor-ruler" aria-hidden="true">
      <div className="editor-ruler-ticks">{Array.from({ length: tickCount + 1 }, (_, index) => <i key={index} className={index % 5 === 0 ? "major" : ""} style={{ left: `${index * minorInterval / safeDuration * 100}%` }} />)}</div>
      {Array.from({ length: Math.floor(safeDuration / interval + .00001) + 1 }, (_, index) => {
        const time = index * interval;
        return <span className={`ruler-label ${index === 0 ? "first" : time >= safeDuration - .00001 ? "last" : ""}`} key={index} style={{ left: `${time / safeDuration * 100}%` }}>{interval < 1 ? `${time.toFixed(1)}s` : timecode(time)}</span>;
      })}
    </div>
    <div className="editor-track">
      <div className="editor-clip">
        <div className="editor-clip-name"><Video size={12} /><strong>{camera}</strong><span>{waveform ? <AudioLines size={12} /> : "VIDEO"}</span></div>
        {waveform ? <svg className="editor-waveform" viewBox="0 0 1200 40" preserveAspectRatio="none" role="img" aria-label={demo ? "Illustrative demo audio waveform" : "Recorded audio waveform"}><path d="M0 20H1200" className="waveform-center" /><path d={path} /></svg> : <div className="editor-no-audio">Audio waveform unavailable</div>}
      </div>
      <input type="range" className="editor-scrubber" aria-label="Video playback position" min="0" max={safeDuration} step="0.01" value={Math.min(position, safeDuration)} onPointerDown={() => clearAndSeek(position)} onChange={e => clearAndSeek(Number(e.target.value))} />
      {markers.filter(m => m.time >= 0 && m.time <= safeDuration).map(marker => {
        const end = marker.endTime !== undefined && marker.endTime > marker.time ? Math.min(marker.endTime, safeDuration) : null;
        const selected = selection === marker.id;
        return <div className="editor-incident" key={marker.id} aria-hidden="true">
          {end !== null && <div className={`editor-incident-range ${selected ? "selected" : ""}`} style={{ left: `calc(${marker.time / safeDuration * 100}% + 11px)`, width: `max(0px, calc(${(end - marker.time) / safeDuration * 100}% - 22px))` }} />}
          <div className={`editor-incident-marker ${selected ? "selected" : ""}`} style={{ left: `${marker.time / safeDuration * 100}%` }} title={`${timecode(marker.time)} · ${marker.title} · Start`}><TriangleAlert size={14} strokeWidth={2} /></div>
          {end !== null && <div className={`editor-incident-marker end-marker ${selected ? "selected" : ""}`} style={{ left: `${end / safeDuration * 100}%` }} title={`${timecode(end)} · ${marker.title} · Resolved`}><TriangleAlert size={14} strokeWidth={2} /></div>}
        </div>;
      })}
    </div>
    <div className="editor-playhead" ref={playhead} style={{ left: `${position / safeDuration * 100}%` }} aria-hidden="true"><span /></div>
    </div>
    </div>
  </div>;
}
