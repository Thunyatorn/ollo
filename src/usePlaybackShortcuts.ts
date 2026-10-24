import { useEffect, useRef } from "react";

type PlaybackShortcuts = {
  enabled: boolean;
  position: number;
  duration: number;
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
    const handle = (event: KeyboardEvent) => {
      const o = current.current;
      if (!o.enabled || event.defaultPrevented || event.isComposing || event.metaKey || event.ctrlKey || event.altKey) return;
      const target = event.target instanceof HTMLElement ? event.target : null;
      if (target?.closest("input, textarea, select, [contenteditable]:not([contenteditable='false']), [role='textbox'], [role='slider']")) return;
      if (event.key === "Escape") {
        document.querySelectorAll<HTMLDetailsElement>("details[open]").forEach(detail => detail.open = false);
        return;
      }
      if (event.key === "?") {
        if (event.repeat) return;
        const guide = document.querySelector<HTMLDetailsElement>(".shortcut-help");
        if (guide) { event.preventDefault(); guide.open = !guide.open; guide.querySelector("summary")?.focus(); }
        return;
      }
      if (document.querySelector("details[open], [role='dialog']")) return;
      const key = event.key.toLowerCase();
      if (key === " " && target?.closest("button, a, summary, [role='button']")) return;
      const total = Number.isFinite(o.duration) && o.duration > 0 ? o.duration : 120;
      if (["arrowleft", "arrowright", "home", "end"].includes(key)) {
        event.preventDefault();
        const step = event.shiftKey ? 10 : 5;
        o.onSeek(key === "home" ? 0 : key === "end" ? total : Math.max(0, Math.min(total, o.position + (key === "arrowleft" ? -step : step))));
        return;
      }
      if (event.repeat) return;
      const actions: Record<string, () => void> = {
        " ": o.onToggle, k: o.onPause, m: o.onMute, f: o.onFullscreen,
        "1": () => o.onLayout("single"), "2": () => o.onLayout("grid"), "3": () => o.onLayout("focus"),
      };
      if (actions[key]) { event.preventDefault(); actions[key](); }
    };
    window.addEventListener("keydown", handle);
    return () => window.removeEventListener("keydown", handle);
  }, []);
}
