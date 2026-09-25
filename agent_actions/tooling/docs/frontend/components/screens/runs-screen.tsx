"use client"

import { useMemo, useState } from "react"
import { ChevronDown } from "lucide-react"
import { useCatalogData } from "@/lib/catalog-context"
import { EM_DASH, fmtDuration, fmtTimestamp, fmtTimestampShort, pct, pctNumber } from "@/lib/format"
import {
  BackButton,
  Card,
  EmptyState,
  PageTitle,
  SearchInput,
  Segmented,
  StatusBadge,
  TypeTag,
  type Tone,
} from "@/components/graphite"
import type { Run, RunStatus } from "@/lib/mock-data"

const RUN_TONE: Record<RunStatus, Tone> = {
  running: "running",
  SUCCESS: "passed",
  FAILED: "failed",
  PAUSED: "neutral",
}

const RUN_LABEL: Record<RunStatus, string> = {
  running: "Running",
  SUCCESS: "Passed",
  FAILED: "Failed",
  PAUSED: "Paused",
}

export function RunsScreen() {
  const { runs } = useCatalogData()
  const [search, setSearch] = useState("")
  const [status, setStatus] = useState("all")
  const [selected, setSelected] = useState<Run | null>(null)

  const counts = useMemo(() => {
    const c: Record<string, number> = { all: runs.length, running: 0, SUCCESS: 0, FAILED: 0, PAUSED: 0 }
    for (const r of runs) c[r.status]++
    return c
  }, [runs])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    return runs
      .filter((r) => status === "all" || r.status === status)
      .filter((r) => !q || `${r.id} ${r.wf}`.toLowerCase().includes(q))
      .sort((a, b) => b.started.localeCompare(a.started))
  }, [runs, search, status])

  if (selected) return <RunDetail run={selected} onBack={() => setSelected(null)} />

  const statusTabs = [
    { value: "all", label: "All", count: counts.all },
    ...(["running", "SUCCESS", "FAILED", "PAUSED"] as RunStatus[])
      .filter((s) => counts[s] > 0)
      .map((s) => ({ value: s, label: RUN_LABEL[s], count: counts[s] })),
  ]

  return (
    <div className="flex max-w-[1180px] animate-view-in flex-col gap-4">
      <PageTitle
        title="Runs"
        subtitle={`${runs.length} total runs · ${counts.FAILED} failed · ${counts.PAUSED} paused`}
      />

      <div className="flex flex-wrap items-center gap-2.5">
        <SearchInput
          value={search}
          onChange={setSearch}
          placeholder="Filter by workflow or run id…"
          className="min-w-[220px] max-w-[420px] flex-1"
        />
        <Segmented options={statusTabs} value={status} onChange={setStatus} />
      </div>

      <Card>
        <div className="grid grid-cols-[100px_minmax(0,1.4fr)_minmax(0,1fr)_minmax(0,1.4fr)_80px_20px] gap-2.5 bg-hover px-[17px] py-2.5 text-xs font-medium text-muted-foreground">
          <span>Status</span>
          <span>Run</span>
          <span>Workflow</span>
          <span>Progress</span>
          <span className="text-right">Duration</span>
          <span />
        </div>
        {filtered.map((run) => {
          const tracked = Object.keys(run.actions).length
          const done = run.success + run.failed + run.skipped
          const inFlight = run.status === "running" ? Math.max(0, run.total - done) : 0
          return (
            <button
              key={run.id}
              onClick={() => setSelected(run)}
              className="grid w-full grid-cols-[100px_minmax(0,1.4fr)_minmax(0,1fr)_minmax(0,1.4fr)_80px_20px] items-center gap-2.5 border-t border-border-soft px-[17px] py-2.5 text-left hover:bg-hover"
            >
              <span className="justify-self-start">
                <StatusBadge tone={RUN_TONE[run.status]} label={RUN_LABEL[run.status]} />
              </span>
              <span className="min-w-0">
                <span className="block truncate font-mono text-[12.5px] text-accent-bright">{run.id}</span>
                <span className="mt-0.5 block text-[10.5px] text-muted-foreground">
                  {fmtTimestampShort(run.started)} · {tracked} action{tracked === 1 ? "" : "s"} tracked
                </span>
              </span>
              <span className="truncate text-xs text-foreground-2">{run.wf}</span>
              <span className="flex items-center gap-2">
                <span className="flex h-[5px] flex-1 gap-px overflow-hidden rounded-[3px] bg-surface-2">
                  <span className="h-full bg-success" style={{ width: pct(run.success, run.total) }} />
                  <span className="h-full bg-danger" style={{ width: pct(run.failed, run.total) }} />
                  <span className="h-full bg-muted-2" style={{ width: pct(run.skipped, run.total) }} />
                  <span className="h-full bg-primary" style={{ width: pct(inFlight, run.total) }} />
                </span>
                <span className="shrink-0 font-mono text-[10.5px] text-muted-foreground">
                  {done}/{run.total}
                </span>
              </span>
              <span className="text-right font-mono text-xs">{fmtDuration(run.duration)}</span>
              <span className="text-right text-muted-foreground">→</span>
            </button>
          )
        })}
        {filtered.length === 0 && (
          <EmptyState
            message={runs.length === 0 ? "No runs recorded yet." : "No runs match these filters"}
            actionLabel={runs.length === 0 ? undefined : "Clear filters"}
            onAction={runs.length === 0 ? undefined : () => { setSearch(""); setStatus("all") }}
          />
        )}
      </Card>
    </div>
  )
}

/* ─── Detail ────────────────────────────────────────────────────────────── */

function RunDetail({ run, onBack }: { run: Run; onBack: () => void }) {
  const [jsonOpen, setJsonOpen] = useState(false)
  const entries = Object.entries(run.actions)

  // Wall-clock Gantt. Actions that record only a duration fall back to a bar at
  // the origin rather than vanishing from the timeline.
  const timeline = useMemo(() => {
    const t0 = new Date(run.started).getTime()
    const bars = entries.map(([name, a]) => {
      let start = a.started ? new Date(a.started).getTime() - t0 : null
      let end = a.ended ? new Date(a.ended).getTime() - t0 : null
      if (start != null && end == null && a.dur > 0) end = start + a.dur * 1000
      if (end != null && start == null && a.dur > 0) start = end - a.dur * 1000
      return { name, action: a, start, end }
    })
    const timed = bars.filter((b) => b.start != null && b.end != null && !isNaN(b.start!) && !isNaN(b.end!))
    const span = Math.max(
      1000,
      run.duration * 1000,
      ...timed.map((b) => b.end!),
    )
    return { bars, span, hasTiming: timed.length >= 2 }
  }, [entries, run.started, run.duration])

  const ticks = Array.from({ length: 5 }, (_, i) => ({
    left: `${(i / 4) * 100}%`,
    label: fmtDuration((timeline.span * i) / 4 / 1000),
  }))

  const result =
    run.failed > 0 ? `${run.failed} failed`
      : run.success > 0 ? `${run.success} passed`
        : RUN_LABEL[run.status]

  return (
    <div className="flex max-w-[1180px] animate-view-in flex-col gap-3.5">
      <div className="flex items-center gap-3.5">
        <BackButton onClick={onBack} title="Back to runs" />
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2.5">
            <span className="truncate font-mono text-lg font-semibold">{run.id}</span>
            <StatusBadge tone={RUN_TONE[run.status]} label={RUN_LABEL[run.status]} />
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            {run.wf} · {fmtTimestamp(run.started)}
            {run.ended ? ` → ${fmtTimestamp(run.ended)}` : ""}
          </p>
        </div>
      </div>

      {run.error && <ErrorBlock error={run.error} />}

      <div className="grid grid-cols-[repeat(auto-fit,minmax(160px,1fr))] gap-3">
        <StatCard label="Duration" value={fmtDuration(run.duration)} />
        <StatCard label="Actions" value={`${run.success + run.failed + run.skipped} / ${run.total}`} />
        <StatCard label="Tokens" value={run.tokens > 0 ? run.tokens.toLocaleString() : EM_DASH} />
        <StatCard
          label="Result"
          value={result}
          valueClass={run.failed > 0 ? "text-danger-t" : run.success > 0 ? "text-success-t" : "text-foreground"}
        />
      </div>

      {entries.length === 0 ? (
        <Card>
          <EmptyState message="No action execution data recorded for this run." />
        </Card>
      ) : (
        <Card>
          <div className="flex flex-wrap items-center gap-3.5 border-b border-border px-[18px] py-3">
            <span className="text-[13px] font-semibold">Timeline</span>
            <span className="font-mono text-[11px] text-muted-foreground">
              {entries.length} action{entries.length === 1 ? "" : "s"} · {fmtDuration(timeline.span / 1000)}
            </span>
            <span className="flex-1" />
            <span className="flex items-center gap-3 text-[10.5px] text-muted-foreground">
              <span className="flex items-center gap-1.5"><span className="h-1.5 w-2.5 rounded-sm bg-llm" />LLM</span>
              <span className="flex items-center gap-1.5"><span className="h-1.5 w-2.5 rounded-sm bg-tool" />Tool</span>
              <span className="flex items-center gap-1.5"><span className="h-1.5 w-2.5 rounded-sm bg-danger" />Failed</span>
              <span className="flex items-center gap-1.5"><span className="h-1.5 w-2.5 rounded-sm bg-info" />Running</span>
            </span>
          </div>

          <div className="grid grid-cols-[22px_46px_minmax(110px,0.7fr)_minmax(0,1.6fr)_72px] items-end gap-2.5 px-[18px] pb-1.5 pt-2.5">
            <span />
            <span />
            <span className="text-xs font-medium text-muted-foreground">Action</span>
            <div className="relative h-3">
              {ticks.map((t, i) => (
                <span
                  key={i}
                  className="absolute whitespace-nowrap font-mono text-[9.5px] text-muted-2"
                  style={{ left: t.left, transform: i === 0 ? "none" : i === 4 ? "translateX(-100%)" : "translateX(-50%)" }}
                >
                  {t.label}
                </span>
              ))}
            </div>
            <span className="text-right text-xs font-medium text-muted-foreground">Duration</span>
          </div>

          {timeline.bars.map((bar, i) => {
            const a = bar.action
            const failed = a.status?.toLowerCase() === "failed"
            const isRunning = a.status?.toLowerCase() === "running"
            const skipped = a.status?.toLowerCase() === "skipped"
            const fill = failed
              ? "bg-danger"
              : isRunning
                ? "bg-info"
                : skipped
                  ? "bg-muted-2"
                  : a.type === "tool"
                    ? "bg-tool"
                    : "bg-llm"
            const left = bar.start != null ? pctNumber(bar.start, timeline.span) : 0
            const rawWidth =
              bar.start != null && bar.end != null ? bar.end - bar.start : a.dur * 1000
            const width = Math.min(100 - left, pctNumber(rawWidth, timeline.span))
            return (
              <div
                key={bar.name}
                title={`${bar.name} · ${a.status}`}
                className="grid grid-cols-[22px_46px_minmax(110px,0.7fr)_minmax(0,1.6fr)_72px] items-center gap-2.5 border-t border-border-soft px-[18px] py-[5px] hover:bg-hover"
              >
                <span className="font-mono text-[10.5px] text-muted-2">{i + 1}</span>
                <TypeTag type={a.type} />
                <span className={`min-w-0 truncate font-mono text-[11.5px] ${failed ? "text-danger-t" : isRunning ? "text-info-t" : "text-foreground-2"}`}>
                  {bar.name}
                </span>
                <div
                  className="relative h-3.5 overflow-hidden rounded-[3px] bg-well"
                  style={{
                    backgroundImage: "linear-gradient(to right, hsl(var(--grid)) 1px, transparent 1px)",
                    backgroundSize: "25% 100%",
                  }}
                >
                  <div
                    className={`absolute bottom-0.5 top-0.5 rounded-sm ${fill}`}
                    style={{ left: `${left}%`, width: `${Math.max(0.8, width)}%` }}
                  />
                </div>
                <span className={`whitespace-nowrap text-right font-mono text-[11px] ${failed ? "text-danger-t" : "text-muted-foreground"}`}>
                  {a.dur > 0 ? fmtDuration(a.dur) : EM_DASH}
                </span>
              </div>
            )
          })}
        </Card>
      )}

      <Card>
        <button
          onClick={() => setJsonOpen((o) => !o)}
          className="flex w-full items-center justify-between px-[18px] py-3 text-left hover:bg-hover"
        >
          <span className="text-xs font-medium text-foreground">Run summary</span>
          <span className="flex items-center gap-2">
            <span className="font-mono text-[10px] text-muted-foreground">JSON</span>
            <ChevronDown className={`h-3.5 w-3.5 text-muted-foreground ${jsonOpen ? "rotate-180" : ""}`} />
          </span>
        </button>
        {jsonOpen && (
          <div className="border-t border-border px-[18px] pb-[18px]">
            <pre className="mt-3.5 overflow-x-auto font-mono text-xs leading-relaxed text-foreground-2">
              {JSON.stringify(
                {
                  run_id: run.id,
                  workflow: run.wf,
                  status: run.status,
                  started: run.started,
                  ...(run.ended ? { ended: run.ended } : {}),
                  duration: fmtDuration(run.duration),
                  actions_succeeded: run.success,
                  actions_failed: run.failed,
                  actions_skipped: run.skipped,
                  actions_total: run.total,
                  tokens: run.tokens,
                },
                null,
                2,
              )}
            </pre>
          </div>
        )}
      </Card>
    </div>
  )
}

function StatCard({
  label,
  value,
  valueClass = "text-foreground",
}: {
  label: string
  value: string
  valueClass?: string
}) {
  return (
    <div className="rounded-card border border-border bg-surface px-4 py-3">
      <div className="text-xs font-medium text-muted-foreground">{label}</div>
      <div className={`mt-1.5 font-mono text-[17px] ${valueClass}`}>{value}</div>
    </div>
  )
}

function ErrorBlock({ error }: { error: string }) {
  const [expanded, setExpanded] = useState(false)
  const lines = error.trimEnd().split("\n")
  const summary = lines.filter((l) => l.trim()).pop() || error.slice(0, 200)

  return (
    <div className="rounded-card border border-border bg-danger-a12 px-[18px] py-3.5">
      <p className="m-0 font-mono text-sm font-medium leading-relaxed text-danger-t">{summary}</p>
      {lines.length > 1 && (
        <>
          <button
            onClick={() => setExpanded((e) => !e)}
            className="mt-2 text-[10.5px] text-danger-t hover:underline"
          >
            {expanded ? "Hide traceback" : "Show full traceback"}
          </button>
          {expanded && (
            <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap border-t border-border-soft pt-2 font-mono text-[10.5px] leading-relaxed text-foreground-2">
              {error}
            </pre>
          )}
        </>
      )}
    </div>
  )
}
