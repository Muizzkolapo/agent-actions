"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import { ChevronDown, ChevronRight, Copy, Link2, X, ArrowRight } from "lucide-react"
import { useCatalogData } from "@/lib/catalog-context"
import { deriveHealth } from "@/lib/health"
import { EM_DASH, fmtClock, fmtClockMs, fmtSeconds } from "@/lib/format"
import { Card, EmptyState, Kbd, PageTitle, SearchInput, Segmented } from "@/components/graphite"
import type { EventLevel, LogEvent } from "@/lib/mock-data"

export interface LogsIntent {
  level?: EventLevel | "all"
  q?: string
  invocationId?: string
}

/* ─── Level vocabulary ──────────────────────────────────────────────────── */

const LEVELS: EventLevel[] = ["error", "warn", "info", "debug"]

const LEVEL_STYLE: Record<EventLevel, { label: string; text: string; bg: string; fill: string }> = {
  error: { label: "ERR", text: "text-danger-t", bg: "bg-danger-a12", fill: "bg-danger" },
  warn: { label: "WRN", text: "text-warning-t", bg: "bg-warning-a12", fill: "bg-warning" },
  info: { label: "INF", text: "text-accent-t", bg: "bg-accent-a12", fill: "bg-primary" },
  debug: { label: "DBG", text: "text-muted-foreground", bg: "bg-surface-2", fill: "bg-muted-2" },
}

/* ─── Per-class derivations ─────────────────────────────────────────────── */

/** No event class carries a `duration` key — each names its own. */
const DURATION_KEYS = ["execution_time", "elapsed_time", "latency_ms", "timeout_seconds", "retry_after"] as const

function durationKey(data: Record<string, unknown>): string | null {
  for (const k of DURATION_KEYS) if (typeof data[k] === "number") return k
  return null
}

function durationLabel(data: Record<string, unknown>): string {
  const key = durationKey(data)
  if (!key) return EM_DASH
  const value = data[key] as number
  return key === "latency_ms" ? `${value}ms` : `${value}s`
}

/**
 * Span length for the waterfall. `timeout_seconds` and `retry_after` describe a
 * wait or a configured limit rather than work this event performed — plotting
 * them would draw a 5s bar for a guard that timed out *at* 5s.
 */
function durationMs(data: Record<string, unknown>): number {
  if (typeof data.execution_time === "number") return Math.round(data.execution_time * 1000)
  if (typeof data.elapsed_time === "number") return Math.round(data.elapsed_time * 1000)
  if (typeof data.latency_ms === "number") return data.latency_ms
  return 0
}

function tokenLabel(data: Record<string, unknown>): string | null {
  if (typeof data.total_tokens === "number") return data.total_tokens.toLocaleString()
  if (typeof data.tokens === "string") {
    const m = data.tokens.match(/(\d+)/)
    return m ? Number(m[1]).toLocaleString() : null
  }
  if (data.tokens && typeof data.tokens === "object") {
    const t = data.tokens as Record<string, unknown>
    if (typeof t.total_tokens === "number") return t.total_tokens.toLocaleString()
  }
  return null
}

function chipValue(value: unknown): string {
  if (value === null) return "null"
  if (typeof value === "object") return JSON.stringify(value)
  return String(value)
}

function searchIndex(e: LogEvent): string {
  const fields = Object.entries(e.data).map(([k, v]) => `${k}=${chipValue(v)}`)
  return [e.message, e.code, e.eventType, e.category, e.workflow ?? "", e.invocationId ?? "", ...fields]
    .join(" ")
    .toLowerCase()
}

/* ─── Screen ────────────────────────────────────────────────────────────── */

const HISTOGRAM_BUCKETS = 36

export function LogsScreen({ intent }: { intent?: LogsIntent | null }) {
  const data = useCatalogData()
  const health = useMemo(() => deriveHealth(data), [data])
  const events = data.logEvents

  const [view, setView] = useState<"stream" | "grouped">("stream")
  const [level, setLevel] = useState<EventLevel | "all">(intent?.level ?? "all")
  const [search, setSearch] = useState(intent?.q ?? "")
  const [workflow, setWorkflow] = useState("all")
  const [diagnostics, setDiagnostics] = useState(false)
  const [dense, setDense] = useState(true)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [cursorId, setCursorId] = useState<string | null>(null)
  const [trace, setTrace] = useState<string | null>(intent?.invocationId ?? null)
  const [range, setRange] = useState<[number, number] | null>(null)
  const [copied, setCopied] = useState<string | null>(null)

  const indexed = useMemo(
    () => events.map((e) => ({ event: e, haystack: searchIndex(e), time: Date.parse(e.timestamp) })),
    [events],
  )

  const workflows = useMemo(() => {
    const names = new Set<string>()
    for (const e of events) if (e.workflow) names.add(e.workflow)
    return [...names].sort()
  }, [events])

  // Diagnostics, workflow and the histogram range scope the window; level and
  // search filter inside it, so the level counts describe what is selectable.
  const scoped = useMemo(
    () =>
      indexed.filter(({ event, time }) => {
        if (!diagnostics && event.diagnostic) return false
        if (workflow !== "all" && event.workflow !== workflow) return false
        if (range && (isNaN(time) || time < range[0] || time > range[1])) return false
        return true
      }),
    [indexed, diagnostics, workflow, range],
  )

  const searched = useMemo(() => {
    const q = search.trim().toLowerCase()
    return q ? scoped.filter((r) => r.haystack.includes(q)) : scoped
  }, [scoped, search])

  const levelCounts = useMemo(() => {
    const counts: Record<string, number> = { all: searched.length, error: 0, warn: 0, info: 0, debug: 0 }
    for (const { event } of searched) counts[event.level]++
    return counts
  }, [searched])

  const rows = useMemo(
    () =>
      (level === "all" ? searched : searched.filter((r) => r.event.level === level))
        .map((r) => r.event)
        .sort((a, b) => (a.timestamp < b.timestamp ? 1 : a.timestamp > b.timestamp ? -1 : b.seq - a.seq)),
    [searched, level],
  )

  const groups = useMemo(() => {
    const byCode = new Map<string, LogEvent[]>()
    for (const e of rows) {
      const list = byCode.get(e.code)
      if (list) list.push(e)
      else byCode.set(e.code, [e])
    }
    return [...byCode.entries()]
      .map(([code, list]) => ({
        code,
        eventType: list[0].eventType,
        level: list[0].level,
        count: list.length,
        workflows: new Set(list.map((e) => e.workflow).filter(Boolean)).size,
        last: list[0].timestamp,
      }))
      .sort((a, b) => b.count - a.count)
  }, [rows])

  const slowest = useMemo(() => {
    let best: { event: LogEvent; ms: number } | null = null
    for (const { event } of scoped) {
      const ms = durationMs(event.data)
      if (ms > 0 && (!best || ms > best.ms)) best = { event, ms }
    }
    return best
  }, [scoped])

  const histogram = useHistogram(scoped)

  const problemIds = useMemo(
    () => rows.filter((e) => e.level === "error" || e.level === "warn").map((e) => e.id),
    [rows],
  )

  const jump = useCallback(
    (ids: string[], dir: 1 | -1) => {
      if (ids.length === 0) return
      const at = cursorId ? ids.indexOf(cursorId) : -1
      const next = at === -1 ? (dir === 1 ? 0 : ids.length - 1) : (at + dir + ids.length) % ids.length
      const id = ids[next]
      setCursorId(id)
      document.querySelector(`[data-event-row="${CSS.escape(id)}"]`)?.scrollIntoView({ block: "nearest" })
    },
    [cursorId],
  )

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      const tag = (e.target as HTMLElement | null)?.tagName
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return
      if (e.metaKey || e.ctrlKey || e.altKey) return
      const ids = rows.map((r) => r.id)
      switch (e.key) {
        case "j": jump(ids, 1); break
        case "k": jump(ids, -1); break
        case "n": jump(problemIds, 1); break
        case "N": jump(problemIds, -1); break
        case "g": setView((v) => (v === "stream" ? "grouped" : "stream")); break
        case "e": setLevel((l) => (l === "error" ? "all" : "error")); break
        case "w": setLevel((l) => (l === "warn" ? "all" : "warn")); break
        case "t": {
          const target = rows.find((r) => r.id === cursorId) ?? rows[0]
          if (target?.invocationId) setTrace(target.invocationId)
          break
        }
        case "Enter":
          if (cursorId) { e.preventDefault(); setExpandedId((id) => (id === cursorId ? null : cursorId)) }
          break
        case "Escape":
          if (trace) setTrace(null)
          else if (expandedId) setExpandedId(null)
          else if (range) setRange(null)
          break
        default:
          return
      }
    }
    document.addEventListener("keydown", onKeyDown)
    return () => document.removeEventListener("keydown", onKeyDown)
  }, [rows, problemIds, cursorId, jump, trace, expandedId, range])

  const clearFilters = () => {
    setLevel("all")
    setSearch("")
    setWorkflow("all")
    setRange(null)
  }

  const filtersActive = level !== "all" || search !== "" || workflow !== "all" || range !== null

  // The window is a recent slice of each log, so a search can legitimately match
  // nothing that is still in it. Saying so beats an unexplained blank panel.
  const emptyMessage = filtersActive
    ? `No events match these filters. The window holds the ${events.length.toLocaleString()} most recent events across all logs — an older event will not be in it.`
    : "No events in the loaded window."

  const copy = (id: string, text: string) => {
    navigator.clipboard.writeText(text).then(
      () => { setCopied(id); setTimeout(() => setCopied((c) => (c === id ? null : c)), 1500) },
      () => { /* clipboard unavailable */ },
    )
  }

  if (events.length === 0) {
    return (
      <div className="flex max-w-[1180px] animate-view-in flex-col gap-3.5">
        <PageTitle
          title="Logs & Events"
          subtitle="Structured event stream — filter by level, workflow, field or trace id"
        />
        <Card>
          <EmptyState message="No events in this catalog. Run a workflow, then regenerate the docs to load its event log." />
        </Card>
      </div>
    )
  }

  return (
    <div className="flex max-w-[1180px] animate-view-in flex-col gap-3.5">
      <PageTitle
        title="Logs & Events"
        subtitle="Structured event stream — filter by level, workflow, field or trace id"
      />

      <div className="grid grid-cols-[repeat(auto-fit,minmax(215px,1fr))] gap-3">
        <StatCard
          dot="bg-danger"
          label="Errors"
          value={health.errors.toLocaleString()}
          valueClass="text-danger"
          note="across loaded logs"
        />
        <StatCard
          dot="bg-warning"
          label="Warnings"
          value={health.warnings.toLocaleString()}
          valueClass="text-warning-t"
          note="across loaded logs"
        />
        <StatCard
          label="Slowest event"
          value={slowest ? fmtSeconds(slowest.ms / 1000) : EM_DASH}
          note={
            slowest
              ? String(slowest.event.data.action_name ?? slowest.event.code)
              : "no timed events in window"
          }
          mono
        />
        <StatCard
          label="Top event code"
          value={groups[0]?.code || EM_DASH}
          valueClass="text-warning-t"
          note={
            groups[0] && rows.length
              ? `${Math.round((groups[0].count / rows.length) * 100)}% of window`
              : "no events in window"
          }
          mono
        />
      </div>

      <div className="flex flex-wrap items-center gap-2.5">
        <Segmented
          options={[
            { value: "stream", label: "Stream" },
            { value: "grouped", label: "Grouped" },
          ]}
          value={view}
          onChange={(v) => setView(v as "stream" | "grouped")}
        />
        <SearchInput
          value={search}
          onChange={setSearch}
          placeholder="Search message, action, field or trace id…"
          className="min-w-[200px] flex-1"
        />
        <select
          value={workflow}
          onChange={(e) => setWorkflow(e.target.value)}
          aria-label="Workflow"
          className="max-w-[180px] cursor-pointer rounded-control border border-border bg-surface px-2.5 py-[7px] font-mono text-[11.5px] text-foreground-2 outline-none"
        >
          <option value="all">all workflows</option>
          {workflows.map((w) => (
            <option key={w} value={w}>{w}</option>
          ))}
        </select>
        <button
          onClick={() => setDense((d) => !d)}
          title="Row density"
          className="shrink-0 rounded-control border border-border bg-surface px-2.5 py-[7px] text-[11.5px] text-muted-foreground hover:text-foreground"
        >
          {dense ? "Compact" : "Comfortable"}
        </button>
        <button
          onClick={() => setDiagnostics((d) => !d)}
          title="Framework-internal events — the console hides these unless the run is verbose"
          className={`shrink-0 rounded-control border border-border px-2.5 py-[7px] text-[11.5px] ${
            diagnostics ? "bg-accent-a12 text-accent-t" : "bg-surface text-muted-foreground"
          }`}
        >
          Diagnostics {diagnostics ? "on" : "off"}
        </button>
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        <LevelChip label="All" count={levelCounts.all} active={level === "all"} onClick={() => setLevel("all")} />
        {LEVELS.map((l) => (
          <LevelChip
            key={l}
            label={l === "warn" ? "Warn" : l.charAt(0).toUpperCase() + l.slice(1)}
            count={levelCounts[l]}
            dot={LEVEL_STYLE[l].fill}
            active={level === l}
            onClick={() => setLevel((cur) => (cur === l ? "all" : l))}
          />
        ))}
        <span className="flex-1" />
        <span className="font-mono text-[11px] text-muted-2">
          {rows.length.toLocaleString()}/{events.length.toLocaleString()} events
        </span>
      </div>

      <Card className="px-3.5 pb-2.5 pt-3">
        <div className="mb-2.5 flex flex-wrap items-center gap-2.5">
          <span className="text-xs font-medium text-muted-foreground">Event volume</span>
          <span className="font-mono text-[10.5px] text-muted-foreground">{histogram.caption}</span>
          <span className="flex-1" />
          {range && (
            <button
              onClick={() => setRange(null)}
              className="flex items-center gap-1.5 rounded-control border border-accent-a30 bg-accent-a12 px-2.5 py-1 text-[11px] text-accent-t"
            >
              <X className="h-2.5 w-2.5" strokeWidth={2.6} />
              Clear range
            </button>
          )}
        </div>
        <div className="flex h-11 items-end gap-0.5 border-b border-border">
          {histogram.buckets.map((b, i) => (
            <button
              key={i}
              title={b.title}
              onClick={(e) =>
                setRange((cur) =>
                  e.shiftKey && cur
                    ? [Math.min(cur[0], b.from), Math.max(cur[1], b.to)]
                    : [b.from, b.to],
                )
              }
              className="flex h-full min-w-0 flex-1 cursor-pointer flex-col-reverse gap-px rounded-t-sm pb-px hover:bg-hover"
            >
              {b.segments.map((s) => (
                <span
                  key={s.level}
                  className={`block shrink-0 rounded-[1.5px] ${LEVEL_STYLE[s.level].fill}`}
                  style={{ height: s.height }}
                />
              ))}
            </button>
          ))}
        </div>
        <div className="mt-1.5 flex justify-between font-mono text-[9.5px] text-muted-2">
          {histogram.axis.map((label, i) => (
            <span key={i}>{label}</span>
          ))}
        </div>
      </Card>

      {trace && (
        <TracePanel
          invocationId={trace}
          events={scoped.map((r) => r.event)}
          onClose={() => setTrace(null)}
        />
      )}

      {view === "stream" ? (
        <Card>
          <div className="grid grid-cols-[84px_58px_46px_minmax(0,1fr)_58px_18px] gap-2 bg-surface-2 px-3.5 py-2 text-xs font-medium text-muted-foreground">
            <span>Time</span>
            <span>Level</span>
            <span>Code</span>
            <span>Category</span>
            <span className="text-right">Duration</span>
            <span />
          </div>
          {rows.map((e) => (
            <EventRow
              key={e.id}
              event={e}
              dense={dense}
              open={expandedId === e.id}
              cursor={cursorId === e.id}
              copied={copied}
              onToggle={() => {
                setCursorId(e.id)
                setExpandedId((id) => (id === e.id ? null : e.id))
              }}
              onFilterField={(k, v) => setSearch(`${k}=${v}`)}
              onTrace={() => e.invocationId && setTrace(e.invocationId)}
              onCopy={copy}
            />
          ))}
          {rows.length === 0 && (
            <EmptyState
              message={emptyMessage}
              actionLabel={filtersActive ? "Clear filters" : undefined}
              onAction={filtersActive ? clearFilters : undefined}
            />
          )}
        </Card>
      ) : (
        <Card>
          <div className="grid grid-cols-[58px_minmax(0,1fr)_78px_46px] gap-2.5 bg-surface-2 px-3.5 py-2 text-xs font-medium text-muted-foreground">
            <span>Level</span>
            <span>Event code</span>
            <span>Share</span>
            <span className="text-right">Count</span>
          </div>
          {groups.map((g) => (
            <button
              key={g.code}
              onClick={() => { setView("stream"); setSearch(g.code) }}
              title="Show these events in the stream"
              className="grid w-full grid-cols-[58px_minmax(0,1fr)_78px_46px] items-center gap-2.5 border-t border-border-soft px-3.5 py-2.5 text-left hover:bg-hover"
            >
              <LevelTag level={g.level} />
              <span className="min-w-0">
                <span className="block truncate font-mono text-[11.5px] text-foreground-2">
                  {g.code} · {g.eventType}
                </span>
                <span className="mt-0.5 flex gap-2.5 font-mono text-[10.5px] text-muted-foreground">
                  <span className="shrink-0">
                    {g.workflows} workflow{g.workflows === 1 ? "" : "s"}
                  </span>
                  <span className="shrink-0">last {fmtClock(g.last)}</span>
                </span>
              </span>
              <span className="h-[5px] overflow-hidden rounded-pill bg-surface-2">
                <span
                  className={`block h-full rounded-pill ${LEVEL_STYLE[g.level].fill}`}
                  style={{ width: `${rows.length ? (g.count / rows.length) * 100 : 0}%` }}
                />
              </span>
              <span className="text-right font-mono text-xs text-foreground">{g.count.toLocaleString()}</span>
            </button>
          ))}
          {groups.length === 0 && (
            <EmptyState
              message={emptyMessage}
              actionLabel={filtersActive ? "Clear filters" : undefined}
              onAction={filtersActive ? clearFilters : undefined}
            />
          )}
        </Card>
      )}

      <div className="flex flex-wrap items-center gap-3.5 text-[10.5px] text-muted-foreground">
        <span className="flex items-center gap-1"><Kbd>j</Kbd><Kbd>k</Kbd>move</span>
        <span className="flex items-center gap-1"><Kbd>n</Kbd><Kbd>N</Kbd>next/prev problem</span>
        <span className="flex items-center gap-1"><Kbd>↵</Kbd>expand</span>
        <span className="flex items-center gap-1"><Kbd>t</Kbd>trace run</span>
        <span className="flex items-center gap-1"><Kbd>e</Kbd>errors</span>
        <span className="flex items-center gap-1"><Kbd>w</Kbd>warnings</span>
        <span className="flex items-center gap-1"><Kbd>g</Kbd>group</span>
        <span className="flex items-center gap-1"><Kbd>esc</Kbd>back out</span>
        <span className="flex items-center gap-1"><Kbd>⌘K</Kbd>jump</span>
      </div>
    </div>
  )
}

/* ─── Row ───────────────────────────────────────────────────────────────── */

function EventRow({
  event,
  dense,
  open,
  cursor,
  copied,
  onToggle,
  onFilterField,
  onTrace,
  onCopy,
}: {
  event: LogEvent
  dense: boolean
  open: boolean
  cursor: boolean
  copied: string | null
  onToggle: () => void
  onFilterField: (key: string, value: string) => void
  onTrace: () => void
  onCopy: (id: string, text: string) => void
}) {
  const durKey = durationKey(event.data)
  const tokens = tokenLabel(event.data)
  const chips = Object.entries(event.data).filter(
    ([k]) => k !== durKey && !(tokens && (k === "total_tokens" || k === "tokens")),
  )

  return (
    <div
      data-event-row={event.id}
      className={`border-t border-border-soft ${cursor ? "bg-accent-a12" : ""}`}
    >
      <button
        onClick={onToggle}
        className={`block w-full px-3.5 text-left hover:bg-hover ${dense ? "py-1.5" : "py-2.5"}`}
      >
        <span className="grid grid-cols-[84px_58px_46px_minmax(0,1fr)_58px_18px] items-center gap-2">
          <span className="font-mono text-[11px] text-muted-foreground">{fmtClockMs(event.timestamp)}</span>
          <LevelTag level={event.level} />
          <span className="whitespace-nowrap font-mono text-[10.5px] text-muted-foreground">{event.code}</span>
          <span className="min-w-0 truncate font-mono text-[10px] text-muted-foreground">{event.category}</span>
          <span className="text-right font-mono text-[11px] text-muted-foreground">
            {durationLabel(event.data)}
          </span>
          {open ? (
            <ChevronDown className="h-[13px] w-[13px] text-muted-2" strokeWidth={2.2} />
          ) : (
            <ChevronRight className="h-[13px] w-[13px] text-muted-2" strokeWidth={2.2} />
          )}
        </span>
        {/* Real messages run past 400px, so the message gets its own full-width
            line below a fixed metadata grid. It does not go back in the grid. */}
        <span
          title={event.message}
          className="mt-[3px] block overflow-hidden text-xs leading-[1.45] text-foreground-2 [text-wrap:pretty]"
          style={{
            marginLeft: 92,
            display: "-webkit-box",
            WebkitBoxOrient: "vertical",
            WebkitLineClamp: dense ? 1 : 3,
          }}
        >
          {event.message}
        </span>
      </button>

      {open && (
        <div className="flex flex-col gap-2.5 py-0.5 pb-3.5 pl-[106px] pr-3.5">
          {chips.length > 0 && (
            <>
              <div className="font-mono text-xs font-medium text-muted-2">data</div>
              <div className="flex flex-wrap gap-1.5">
                {chips.map(([k, v]) => (
                  <button
                    key={k}
                    onClick={() => onFilterField(k, chipValue(v))}
                    title={`Filter stream to ${k}=${chipValue(v)}`}
                    className="flex items-center gap-1.5 whitespace-nowrap rounded-control border border-border bg-well px-2 py-0.5 font-mono text-[10.5px] hover:border-accent-a30 hover:bg-accent-a12"
                  >
                    <span className="text-muted-2">{k}</span>
                    <span className="max-w-[320px] truncate text-foreground-2">{chipValue(v)}</span>
                  </button>
                ))}
              </div>
            </>
          )}
          <div className="flex flex-wrap items-center gap-4 border-t border-border-soft pt-0.5 font-mono text-[10.5px] text-muted-foreground">
            <span>event_type <span className="text-foreground-3">{event.eventType}</span></span>
            <span>category <span className="text-foreground-3">{event.category || EM_DASH}</span></span>
            <span>workflow_name <span className="text-foreground-3">{event.workflow ?? EM_DASH}</span></span>
            <span className="flex items-center gap-1.5">
              invocation_id
              {event.invocationId ? (
                <span
                  role="button"
                  tabIndex={0}
                  onClick={onTrace}
                  onKeyDown={(e) => { if (e.key === "Enter") onTrace() }}
                  title="Show every event in this run as a waterfall"
                  className="flex cursor-pointer items-center gap-1 border-b border-dashed border-accent-a30 text-accent-t hover:border-accent-t"
                >
                  {event.invocationId}
                  <ArrowRight className="h-2.5 w-2.5" strokeWidth={2.4} />
                </span>
              ) : (
                <span className="text-foreground-3">{EM_DASH}</span>
              )}
            </span>
            <span>correlation_id <span className="text-foreground-3">{event.correlationId ?? EM_DASH}</span></span>
            {tokens && <span>tokens <span className="text-foreground-3">{tokens}</span></span>}
            <span className="flex-1" />
            <button
              onClick={() => onCopy(`${event.id}:link`, `${location.origin}${location.pathname}#ev=${encodeURIComponent(event.id)}`)}
              title="Permalink to this event"
              className="flex items-center gap-1.5 rounded-control border border-border bg-surface px-2 py-0.5 text-[10.5px] text-foreground-3 hover:border-border-2 hover:text-foreground"
            >
              <Link2 className="h-[11px] w-[11px]" strokeWidth={2.2} />
              {copied === `${event.id}:link` ? "Copied" : "Copy link"}
            </button>
            <button
              onClick={() => onCopy(`${event.id}:json`, JSON.stringify(event, null, 2))}
              className="flex items-center gap-1.5 rounded-control border border-border bg-surface px-2 py-0.5 text-[10.5px] text-foreground-3 hover:border-border-2 hover:text-foreground"
            >
              <Copy className="h-[11px] w-[11px]" strokeWidth={2.2} />
              {copied === `${event.id}:json` ? "Copied" : "Copy JSON"}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

function LevelTag({ level }: { level: EventLevel }) {
  const s = LEVEL_STYLE[level]
  return (
    <span className={`rounded-sm py-0.5 text-center font-mono text-[9.5px] font-bold tracking-[0.04em] ${s.bg} ${s.text}`}>
      {s.label}
    </span>
  )
}

function LevelChip({
  label,
  count,
  dot,
  active,
  onClick,
}: {
  label: string
  count: number
  dot?: string
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      aria-pressed={active}
      className={`flex items-center gap-1.5 rounded-pill border border-border px-2.5 py-1 text-[11.5px] ${
        active ? "bg-selected text-foreground" : "bg-surface text-muted-foreground hover:text-foreground"
      }`}
    >
      {dot && <span className={`h-1.5 w-1.5 rounded-pill ${dot}`} />}
      {label}
      <span className="font-mono text-[10px] opacity-75">{count.toLocaleString()}</span>
    </button>
  )
}

function StatCard({
  dot,
  label,
  value,
  valueClass = "text-foreground",
  note,
  mono = false,
}: {
  dot?: string
  label: string
  value: string
  valueClass?: string
  note: string
  mono?: boolean
}) {
  return (
    <div className="rounded-card border border-border bg-surface px-4 py-3.5">
      <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
        {dot && <span className={`h-1.5 w-1.5 rounded-pill ${dot}`} />}
        {label}
      </div>
      <div className={`mt-1.5 font-mono text-[26px] font-semibold leading-tight ${valueClass}`}>{value}</div>
      <div
        className={`mt-0.5 break-words text-[11px] leading-[1.45] text-muted-foreground ${mono ? "font-mono" : ""}`}
      >
        {note}
      </div>
    </div>
  )
}

/* ─── Run trace waterfall ───────────────────────────────────────────────── */

/**
 * An event's timestamp is its *emit* time, so a class that reports work done
 * spans [timestamp − duration, timestamp]. Everything else is an instant marker.
 */
function TracePanel({
  invocationId,
  events,
  onClose,
}: {
  invocationId: string
  events: LogEvent[]
  onClose: () => void
}) {
  const spans = useMemo(() => {
    const inRun = events
      .filter((e) => e.invocationId === invocationId)
      .map((e) => {
        const end = Date.parse(e.timestamp)
        const ms = durationMs(e.data)
        return { event: e, start: end - ms, end, ms }
      })
      .filter((s) => !isNaN(s.end))
      .sort((a, b) => a.start - b.start)
    if (inRun.length === 0) return null
    const t0 = Math.min(...inRun.map((s) => s.start))
    const t1 = Math.max(...inRun.map((s) => s.end))
    const span = Math.max(1, t1 - t0)
    return { rows: inRun, t0, t1, span }
  }, [events, invocationId])

  if (!spans) {
    return (
      <Card accent>
        <div className="flex items-center gap-3 bg-surface-2 px-3.5 py-2.5">
          <span className="text-xs font-medium text-muted-foreground">Run trace</span>
          <span className="font-mono text-xs text-accent-t">{invocationId}</span>
          <span className="font-mono text-[11px] text-muted-foreground">
            no events for this run in the loaded window
          </span>
          <span className="flex-1" />
          <CloseTrace onClose={onClose} />
        </div>
      </Card>
    )
  }

  const { rows, t0, span } = spans
  const errors = rows.filter((s) => s.event.level === "error").length
  // A trace often spans milliseconds, so the axis takes the same resolution as
  // the duration column rather than rounding every tick to 0.0s.
  const ticks = Array.from({ length: 5 }, (_, i) => ({
    left: `${(i / 4) * 100}%`,
    label: fmtSeconds((span * i) / 4 / 1000),
  }))

  return (
    <Card accent>
      <div className="flex flex-wrap items-center gap-3 border-b border-border bg-surface-2 px-3.5 py-2.5">
        <span className="text-xs font-medium text-muted-foreground">Run trace</span>
        <span className="font-mono text-xs text-accent-t">{invocationId}</span>
        <span className="font-mono text-[11px] text-muted-foreground">
          {rows[0].event.workflow ?? "unscoped"} · {rows.length} events · {fmtSeconds(span / 1000)}
        </span>
        {errors > 0 && (
          <span className="rounded-sm bg-danger-a12 px-1.5 py-0.5 font-mono text-[10px] font-bold text-danger-t">
            {errors} ERROR
          </span>
        )}
        <span className="flex-1" />
        <CloseTrace onClose={onClose} />
      </div>
      <div className="px-3.5 pb-3.5 pt-2.5">
        <div className="grid grid-cols-[minmax(0,200px)_minmax(0,1fr)_62px] gap-2.5 pb-1.5">
          <span />
          <div className="relative h-3.5">
            {ticks.map((t, i) => (
              <span
                key={i}
                className="absolute -translate-x-1/2 whitespace-nowrap font-mono text-[9.5px] text-muted-2"
                style={{ left: t.left }}
              >
                {t.label}
              </span>
            ))}
          </div>
          <span />
        </div>
        {rows.map((s) => (
          <div
            key={s.event.id}
            className="grid grid-cols-[minmax(0,200px)_minmax(0,1fr)_62px] items-center gap-2.5 border-t border-border-soft py-1"
          >
            <span className="flex min-w-0 items-center gap-1.5">
              <span
                className={`shrink-0 rounded-[3px] px-1 py-px font-mono text-[9px] font-bold ${
                  LEVEL_STYLE[s.event.level].bg
                } ${LEVEL_STYLE[s.event.level].text}`}
              >
                {s.event.code}
              </span>
              <span className="truncate font-mono text-[11px] text-foreground-2">
                {String(s.event.data.action_name ?? s.event.eventType)}
              </span>
            </span>
            <div className="relative h-4 rounded-[3px] bg-well">
              <div
                title={`+${fmtSeconds((s.start - t0) / 1000)} · ${s.ms ? fmtSeconds(s.ms / 1000) : "instant"}`}
                className={`absolute bottom-[3px] top-[3px] rounded-sm ${LEVEL_STYLE[s.event.level].fill}`}
                style={{
                  left: `${((s.start - t0) / span) * 100}%`,
                  width: `${Math.max(0.8, (s.ms / span) * 100)}%`,
                }}
              />
            </div>
            <span className="text-right font-mono text-[10.5px] text-muted-foreground">
              {s.ms ? fmtSeconds(s.ms / 1000) : EM_DASH}
            </span>
          </div>
        ))}
      </div>
    </Card>
  )
}

function CloseTrace({ onClose }: { onClose: () => void }) {
  return (
    <button
      onClick={onClose}
      className="flex items-center gap-1.5 rounded-control border border-border bg-surface px-2.5 py-1 text-[11.5px] text-foreground-2 hover:bg-hover"
    >
      <X className="h-[11px] w-[11px]" strokeWidth={2.4} />
      Close trace
    </button>
  )
}

/* ─── Histogram ─────────────────────────────────────────────────────────── */

interface Bucket {
  from: number
  to: number
  title: string
  segments: { level: EventLevel; height: string }[]
}

function useHistogram(scoped: { event: LogEvent; time: number }[]) {
  return useMemo(() => {
    const times = scoped.map((r) => r.time).filter((t) => !isNaN(t))
    if (times.length === 0) {
      return { buckets: [] as Bucket[], axis: [] as string[], caption: "no events in window" }
    }
    const min = Math.min(...times)
    const max = Math.max(...times)
    const span = Math.max(1, max - min)
    const width = span / HISTOGRAM_BUCKETS

    const counts: Record<EventLevel, number>[] = Array.from({ length: HISTOGRAM_BUCKETS }, () => ({
      error: 0, warn: 0, info: 0, debug: 0,
    }))
    for (const { event, time } of scoped) {
      if (isNaN(time)) continue
      const idx = Math.min(HISTOGRAM_BUCKETS - 1, Math.floor((time - min) / width))
      counts[idx][event.level]++
    }
    const peak = Math.max(1, ...counts.map((c) => c.error + c.warn + c.info + c.debug))

    const buckets: Bucket[] = counts.map((c, i) => {
      const from = min + i * width
      const to = from + width
      const total = c.error + c.warn + c.info + c.debug
      return {
        from,
        to,
        title: `${new Date(from).toTimeString().slice(0, 8)} — ${total} event${total === 1 ? "" : "s"}`,
        segments: LEVELS.filter((l) => c[l] > 0).map((l) => ({
          level: l,
          height: `${(c[l] / peak) * 100}%`,
        })),
      }
    })

    const axis = [0, 1, 2, 3].map((i) =>
      new Date(min + (span * i) / 3).toTimeString().slice(0, 8),
    )
    return {
      buckets,
      axis,
      caption: `${fmtSeconds(span / 1000)} · ${scoped.length.toLocaleString()} events`,
    }
  }, [scoped])
}
