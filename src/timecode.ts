/** Elapsed time only. Clock times need an explicit recording timezone. */
export function parsePlaybackTime(value: string, duration: number): number | null {
  if (!/^\d+(?::[0-5]\d){0,2}$/.test(value)) return null;
  const seconds = value.split(":").reduce((total, part) => total * 60 + Number(part), 0);
  return Number.isFinite(seconds) ? Math.max(0, Math.min(Math.max(0, duration), seconds)) : null;
}
export function formatPlaybackTime(seconds: number, duration = seconds): string {
  const safe = Math.max(0, Math.floor(seconds));
  const minutes = Math.floor(safe / 60);
  return duration >= 3600
    ? `${Math.floor(safe / 3600)}:${String(minutes % 60).padStart(2, "0")}:${String(safe % 60).padStart(2, "0")}`
    : `${String(minutes).padStart(2, "0")}:${String(safe % 60).padStart(2, "0")}`;
}
export function clockTime(start: string | undefined, seconds: number, showSeconds = false, showPeriod = true): string {
  if (!start || !Number.isFinite(Date.parse(start))) return formatPlaybackTime(seconds);
  const formatter = new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit", ...(showSeconds ? { second: "2-digit" as const } : {}) });
  const date = new Date(Date.parse(start) + seconds * 1000);
  return showPeriod ? formatter.format(date) : formatter.formatToParts(date).filter(part => part.type !== "dayPeriod").map(part => part.value).join("").trim();
}
