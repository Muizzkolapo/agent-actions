const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

export const EM_DASH = "—"

/** Coarse wall-clock duration: 48s, 2m 19s, 1h 6m. */
export function fmtDuration(seconds: number): string {
  if (!seconds || seconds < 0) return "0s"
  const s = Math.round(seconds)
  if (s < 60) return `${s}s`
  if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`
}

/** Precise below a minute, coarse above it. Renders an em dash for no value. */
export function fmtSeconds(seconds: number | null | undefined): string {
  if (seconds == null || seconds < 0) return EM_DASH
  if (seconds === 0) return "0s"
  if (seconds < 1) return `${Math.round(seconds * 1000)}ms`
  if (seconds < 60) return `${seconds < 10 ? seconds.toFixed(1) : Math.round(seconds)}s`
  return fmtDuration(seconds)
}

export function fmtClock(iso: string): string {
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso
  return d.toTimeString().slice(0, 8)
}

/** HH:MM:SS.mmm — the Log Explorer time column. */
export function fmtClockMs(iso: string): string {
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso
  return `${d.toTimeString().slice(0, 8)}.${String(d.getMilliseconds()).padStart(3, "0")}`
}

export function fmtTimestamp(iso: string): string {
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso
  return `${MONTHS[d.getMonth()]} ${d.getDate()}, ${d.getFullYear()} ${d.toTimeString().slice(0, 8)}`
}

/** Today collapses to HH:MM; older dates keep a month and day. */
export function fmtTimestampShort(iso: string): string {
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso
  const time = d.toTimeString().slice(0, 5)
  const now = new Date()
  if (d.toDateString() === now.toDateString()) return time
  const yesterday = new Date(now)
  yesterday.setDate(yesterday.getDate() - 1)
  if (d.toDateString() === yesterday.toDateString()) return `Yesterday ${time}`
  return `${MONTHS[d.getMonth()]} ${d.getDate()} ${time}`
}

export function pct(part: number, total: number): string {
  if (total <= 0) return "0%"
  return `${((part / total) * 100).toFixed(2)}%`
}

export function plural(n: number, word: string): string {
  return `${n.toLocaleString()} ${word}${n === 1 ? "" : "s"}`
}
