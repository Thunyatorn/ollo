import { useEffect, useRef } from "react";
import WaveSurfer from "wavesurfer.js";

/** Visual peaks only: the renderer never loads a URL or plays generated sound. */
export default function AudioWaveform({ peaks, duration, illustrative }: { peaks: number[]; duration: number; illustrative: boolean }) {
  const container = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!container.current) return;
    const color = getComputedStyle(document.documentElement).getPropertyValue("--waveform-ink").trim();
    const wave = WaveSurfer.create({
      container: container.current,
      peaks: [peaks], duration: Math.max(1, duration),
      height: 26, waveColor: color, progressColor: color,
      cursorWidth: 0, barWidth: 1, barGap: 1, barRadius: 0,
      normalize: false, interact: false, hideScrollbar: true,
    });
    return () => wave.destroy();
  }, [peaks, duration]);
  return <div ref={container} className="audio-waveform" role="img" aria-label={illustrative ? "Illustrative audio waveform, generated for this demo" : "Recorded audio waveform"} title={illustrative ? "Illustrative waveform · not recorded audio" : "Recorded audio waveform"} />;
}
