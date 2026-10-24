import { useRef, useState } from "react";

const stamp = (seconds: number) => `${Math.floor(seconds / 60).toString().padStart(2, "0")}:${Math.floor(seconds % 60).toString().padStart(2, "0")}`;
export default function PlaybackTime({ position, duration, disabled, onSeek }: { position: number; duration: number; disabled: boolean; onSeek: (seconds: number) => void }) {
  const [draft, setDraft] = useState<string | null>(null);
  const [invalid, setInvalid] = useState(false);
  const cancelBlur = useRef(false);
  const commit = () => {
    if (draft === null) return;
    const text = draft.trim();
    const valid = /^\d+(?:\.\d+)?$/.test(text) || /^\d+:([0-5]?\d)(?:\.\d+)?$/.test(text);
    if (!valid) { setInvalid(true); return; }
    const parts = text.split(":").map(Number);
    const seconds = parts.length === 2 ? parts[0] * 60 + parts[1] : parts[0];
    onSeek(Math.max(0, Math.min(duration, seconds)));
    setDraft(null); setInvalid(false);
  };
  return <div className="timecode seek-timecode">{disabled ? <span>LIVE / NOT CONNECTED</span> : <>
    <input aria-label="Playback time" aria-invalid={invalid} title="Enter minutes:seconds or seconds to seek" value={draft ?? stamp(position)} onFocus={event => { setDraft(stamp(position)); event.currentTarget.select(); }} onChange={event => { setDraft(event.target.value); setInvalid(false); }} onBlur={() => { if (!cancelBlur.current) commit(); cancelBlur.current = false; setDraft(null); setInvalid(false); }} onKeyDown={event => {
      if (event.key === "Enter") { event.preventDefault(); commit(); }
      if (event.key === "Escape") { cancelBlur.current = true; setDraft(null); setInvalid(false); event.currentTarget.blur(); }
    }} spellCheck={false} />
    <span className="playback-duration" aria-label="Video duration">{stamp(duration)}</span>
  </>}</div>;
}
