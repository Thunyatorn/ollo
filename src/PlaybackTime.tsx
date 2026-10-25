import { useRef, useState } from "react";

import { formatPlaybackTime, parsePlaybackTime } from "./timecode";
export function PlaybackLiveLabel() {
  return <span className="playback-live-label" aria-label="Live footage"><i aria-hidden="true" />LIVE</span>;
}
export default function PlaybackTime({ position, duration, disabled, live = false, onSeek }: { position: number; duration: number; disabled: boolean; live?: boolean; onSeek: (seconds: number) => void }) {
  const [draft, setDraft] = useState<string | null>(null);
  const [invalid, setInvalid] = useState(false);
  const cancelBlur = useRef(false);
  const commit = () => {
    if (draft === null) return;
    const seconds = parsePlaybackTime(draft, duration);
    if (seconds === null) {
      setInvalid(true);
      window.setTimeout(() => setInvalid(false), 180);
    } else onSeek(seconds);
    setDraft(formatPlaybackTime(seconds ?? position, duration));
  };
  return <div className="timecode seek-timecode">{live || disabled ? <PlaybackLiveLabel /> : <>
    <input aria-label="Current time. Type a time to jump." inputMode="numeric" aria-invalid={invalid} title="Enter minutes:seconds or seconds to seek" value={draft ?? formatPlaybackTime(position, duration)} onFocus={event => { setDraft(formatPlaybackTime(position, duration)); event.currentTarget.select(); }} onChange={event => { setDraft(event.target.value); setInvalid(false); }} onBlur={() => { if (!cancelBlur.current) commit(); cancelBlur.current = false; setDraft(null); }} onKeyDown={event => {
      if (event.key === "Enter") { event.preventDefault(); event.currentTarget.blur(); }
      if (event.key === "Escape") { cancelBlur.current = true; setDraft(null); setInvalid(false); event.currentTarget.blur(); }
    }} spellCheck={false} />
    <span className="playback-duration" aria-label={`Duration, ${Math.floor(duration / 60)} minutes ${Math.floor(duration % 60)} seconds`}>{formatPlaybackTime(duration, duration)}</span>
  </>}</div>;
}
