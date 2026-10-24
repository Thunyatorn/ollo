import { useEffect, useMemo, useRef, type RefObject } from "react";
import { AudioLines, Video } from "lucide-react";

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

export default function EditorTimeline({ camera, room, duration, position, playing, demo, peaks, video, markers, selectedId, onSeek }: {
  camera: string; room: number; duration: number; position: number; playing: boolean; demo: boolean;
  peaks: number[] | null; video: RefObject<HTMLVideoElement | null>; markers: TimelineMarker[];
  selectedId?: string | null;
  onSeek: (seconds: number, marker?: TimelineMarker) => void;
}) {
  const playhead = useRef<HTMLDivElement>(null);
  const selection = selectedId;
  const clearAndSeek = (time: number) => onSeek(time);
  const anchor = useRef({ position, at: performance.now() });
  const safeDuration = Number.isFinite(duration) && duration > 0 ? duration : 120;
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
  return <div className="editor-timeline"
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
    <div className="editor-ruler" aria-hidden="true">{[0, 1, 2, 3, 4].map(n => <span key={n}>{timecode(safeDuration * n / 4)}</span>)}</div>
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
          {end !== null && <div className={`editor-incident-range ${selected ? "selected" : ""}`} style={{ left: `${marker.time / safeDuration * 100}%`, width: `${(end - marker.time) / safeDuration * 100}%` }} />}
          <div className={`editor-incident-marker ${selected ? "selected" : ""}`} style={{ left: `${marker.time / safeDuration * 100}%` }} title={`${timecode(marker.time)} · ${marker.title} · Start`}><span /></div>
          {end !== null && <div className={`editor-incident-marker end-marker ${selected ? "selected" : ""}`} style={{ left: `${end / safeDuration * 100}%` }} title={`${timecode(end)} · ${marker.title} · Resolved`}><span /></div>}
        </div>;
      })}
    </div>
    <div className="editor-playhead" ref={playhead} style={{ left: `${position / safeDuration * 100}%` }} aria-hidden="true"><span /></div>
    <div className="editor-track-caption"><span><i />Incidents</span></div>
  </div>;
}
