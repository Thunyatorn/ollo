import { useEffect, useRef, useState, type RefObject } from "react";
import PlaybackTime, { PlaybackLiveLabel } from "./PlaybackTime";
import { Minimize2, Pause, Play, Volume2, VolumeX } from "lucide-react";
export default function FullscreenControls({ stage, position, duration, playing, muted, live = false, onToggle, onMute, onSeek }: {
  live?: boolean;
  stage: RefObject<HTMLDivElement | null>; position: number; duration: number; playing: boolean; muted: boolean;
  onToggle: () => void; onMute: () => void; onSeek: (seconds: number) => void;
}) {
  const [fullscreen, setFullscreen] = useState(false), [visible, setVisible] = useState(true);
  const panel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const element = stage.current;
    let timer: ReturnType<typeof setTimeout>;
    const reveal = () => { setVisible(true); clearTimeout(timer); timer = setTimeout(() => { if (!panel.current?.matches(":hover, :focus-within")) setVisible(false); }, 2500); };
    const changed = () => { setFullscreen(document.fullscreenElement === element); reveal(); };
    element?.addEventListener("pointermove", reveal);
    element?.addEventListener("pointerdown", reveal);
    element?.addEventListener("keydown", reveal);
    document.addEventListener("fullscreenchange", changed);
    changed();
    return () => { clearTimeout(timer); element?.removeEventListener("pointermove", reveal); element?.removeEventListener("pointerdown", reveal); element?.removeEventListener("keydown", reveal); document.removeEventListener("fullscreenchange", changed); };
  }, [stage]);
  if (!fullscreen) return null;
  const total = Number.isFinite(duration) && duration > 0 ? duration : 120;
  return <div ref={panel} className={`fullscreen-controls ${visible || !playing ? "visible" : ""}`} aria-label="Fullscreen playback controls">
    {!live && <input type="range" aria-label="Fullscreen playback position" min={0} max={total} step={0.1} value={Math.min(position, total)} onChange={e => onSeek(Number(e.target.value))} style={{ background: `linear-gradient(to right, var(--primary) ${Math.min(100, position / total * 100)}%, var(--border-strong) 0)` }} />}
    <div className="fullscreen-control-row"><button aria-label={playing ? "Pause fullscreen playback" : "Play fullscreen playback"} onClick={onToggle}>{playing ? <Pause size={23} fill="currentColor" /> : <Play size={23} fill="currentColor" />}</button><button aria-label={muted ? "Unmute fullscreen video" : "Mute fullscreen video"} onClick={onMute}>{muted ? <VolumeX size={23} /> : <Volume2 size={23} />}</button>{live ? <PlaybackLiveLabel /> : <PlaybackTime position={position} duration={total} disabled={false} onSeek={onSeek} />}<button className="fullscreen-exit" aria-label="Exit fullscreen" title="Exit fullscreen (Esc)" onClick={() => void document.exitFullscreen().catch(() => {})}><Minimize2 size={23} /></button></div>
  </div>;
}
