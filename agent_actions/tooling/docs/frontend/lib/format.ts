const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

export const EM_DASH = "—"

/** Coarse wall-clock duration: 48s, 2m 19s, 1h 6m. */
export function fmtDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return "0s"
  const s = Math.round(seconds)
  if (s < 60) return `${s}s`
  if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`
}

/**
 * Precise below a minute, coarse above it. Sub-millisecond durations are real —
 * a tool action completes in tens of microseconds — so they keep two decimals
 * rather than rounding to the 0ms that reads as "not measured".
 */
export function fmtSeconds(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return EM_DASH
  if (seconds === 0) return "0s"
  if (seconds < 0.001) return `${(seconds * 1000).toFixed(2)}ms`
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

const HOUR_MS = 3_600_000
const DAY_MS = 86_400_000

/** A histogram tick. The clock alone reads as a lie once the window spans days,
 *  so the date joins it at whatever resolution the span needs. */
export function fmtSpanTick(ms: number, spanMs: number): string {
  const d = new Date(ms)
  if (isNaN(d.getTime())) return EM_DASH
  const clock = d.toTimeString().slice(0, spanMs < HOUR_MS ? 8 : 5)
  if (spanMs < DAY_MS) return clock
  return `${MONTHS[d.getMonth()]} ${d.getDate()} ${clock}`
}

/** What a histogram covers: a duration while it fits in a day, dated bounds past
 *  that — "2217h 46m" is not a span a reader can place. */
export function fmtSpan(min: number, max: number): string {
  const span = max - min
  if (span < DAY_MS) return fmtSeconds(span / 1000)
  return `${fmtSpanTick(min, span)} → ${fmtSpanTick(max, span)}`
}

/** A bar width. Run records come straight off disk, so the parts are clamped:
 *  a record whose counts exceed its total must not paint past its track. */
export function pct(part: number, total: number): string {
  if (!Number.isFinite(part) || !Number.isFinite(total) || total <= 0) return "0%"
  const ratio = Math.min(1, Math.max(0, part / total))
  return `${(ratio * 100).toFixed(2)}%`
}

export function plural(n: number, word: string): string {
  return `${n.toLocaleString()} ${word}${n === 1 ? "" : "s"}`
}

/** Clamped to [0, 100] for the same reason as `pct`. */
export function pctNumber(part: number, total: number): number {
  if (!Number.isFinite(part) || !Number.isFinite(total) || total <= 0) return 0
  return Math.min(100, Math.max(0, (part / total) * 100))
}
