import { useEffect, useRef } from "react";

type PlaybackShortcuts = {
  enabled: boolean;
  position: number;
  playing: boolean;
  duration: number;
  incidents?: { time: number }[];
  onForward?: () => void;
  onToggle: () => void;
  onPause: () => void;
  onSeek: (position: number) => void;
  onMute: () => void;
  onFullscreen: () => void;
  onLayout: (layout: "single" | "grid" | "focus") => void;
};

export default function usePlaybackShortcuts(options: PlaybackShortcuts) {
  const current = useRef(options);
  current.current = options;
  useEffect(() => {
    let reverseTimer: ReturnType<typeof setInterval> | undefined;
    const stopReverse = () => { clearInterval(reverseTimer); reverseTimer = undefined; };
    const handle = (event: KeyboardEvent) => {
      const o = current.current;
      if (!o.enabled || event.defaultPrevented || event.isComposing || event.metaKey || event.ctrlKey || event.altKey) return;
      const target = event.target instanceof HTMLElement ? event.target : null;
      if (target?.closest("input, textarea, select, [contenteditable]:not([contenteditable='false']), [role='textbox'], [role='slider']")) return;
      if (event.key === "Escape") {
        document.querySelectorAll<HTMLDetailsElement>("details[open]:not(.sidebar-section)").forEach(detail => detail.open = false);
        return;
      }
      if (event.key === "?") {
        if (event.repeat) return;
        event.preventDefault(); window.dispatchEvent(new Event("ollo:shortcuts"));
        return;
      }
      if (document.querySelector("details[open]:not(.sidebar-section), [role='dialog'], [role='menu'], dialog[open], :popover-open")) return;
      const key = event.key.toLowerCase();
      if (key === " " && target?.closest("button, a, summary, [role='button']")) return;
      const total = Number.isFinite(o.duration) && o.duration > 0 ? o.duration : 120;
      if (["j", "k", "l", " ", "arrowleft", "arrowright", "home", "end", ",", ".", "[", "]"].includes(key)) stopReverse();
      if (["arrowleft", "arrowright", "home", "end"].includes(key)) {
        event.preventDefault();
        const step = event.shiftKey ? 10 : 5;
        o.onSeek(key === "home" ? 0 : key === "end" ? total : Math.max(0, Math.min(total, o.position + (key === "arrowleft" ? -step : step))));
        return;
      }
      if (key === "j") {
        event.preventDefault(); o.onPause();
        reverseTimer = setInterval(() => { const latest = current.current; if (!latest.enabled || latest.playing || latest.position <= 0 || document.activeElement?.matches("input, textarea, select")) { stopReverse(); return; } latest.onSeek(Math.max(0, latest.position - .2)); }, 200);
        return;
      }
      if ([",", ".", "[", "]"].includes(key)) {
        event.preventDefault(); o.onPause();
        const times = (o.incidents || []).map(i => i.time).sort((a, b) => a - b);
        const next = key === "[" ? times.filter(t => t < o.position - .1).at(-1) ?? 0 : key === "]" ? times.find(t => t > o.position + .1) ?? total : o.position + (key === "." ? 1 : key === "j" ? -5 : -1);
        o.onSeek(Math.max(0, Math.min(total, next))); return;
      }
      if (event.repeat) return;
      const actions: Record<string, () => void> = {
        " ": o.onToggle, k: o.onPause, l: o.onForward ?? o.onToggle, u: o.onMute, f: o.onFullscreen,
        "1": () => o.onLayout("single"), "2": () => o.onLayout("grid"), "3": () => o.onLayout("focus"),
      };
      if (actions[key]) { event.preventDefault(); actions[key](); }
    };
    window.addEventListener("keydown", handle);
    return () => { stopReverse(); window.removeEventListener("keydown", handle); };
  }, []);
}
