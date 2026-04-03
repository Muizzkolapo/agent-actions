"use client"

import React from "react"
import { useState } from "react"
import { Search, ArrowRight, ArrowLeft, CheckCircle2, XCircle, Loader2, Pause } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { useCatalogData } from "@/lib/catalog-context"
import type { Run, RunStatus } from "@/lib/mock-data"

/* --- Formatting helpers --- */

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

function formatDuration(seconds: number): string {
  if (!seconds || seconds < 0) return "0s"
  const s = Math.round(seconds)
  if (s < 60) return `${s}s`
  if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`
}

function formatTimestamp(iso: string): string {
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso
  return `${MONTHS[d.getMonth()]} ${d.getDate()}, ${d.getFullYear()} ${d.getHours().toString().padStart(2, "0")}:${d.getMinutes().toString().padStart(2, "0")}:${d.getSeconds().toString().padStart(2, "0")}`
}

function formatTimestampShort(iso: string): string {
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso
  const now = new Date()
  const time = `${d.getHours().toString().padStart(2, "0")}:${d.getMinutes().toString().padStart(2, "0")}`
  if (d.toDateString() === now.toDateString()) return time
  const yesterday = new Date(now)
  yesterday.setDate(yesterday.getDate() - 1)
  if (d.toDateString() === yesterday.toDateString()) return `Yesterday ${time}`
  return `${MONTHS[d.getMonth()]} ${d.getDate()} ${time}`
}

// Keys match RunStatus exactly: "SUCCESS" | "FAILED" | "PAUSED" (uppercase) + "running" (lowercase).
const statusColorVar: Record<string, string> = {
  SUCCESS: "--success",
  FAILED: "--destructive",
  running: "--primary",
  PAUSED: "--warning",
}

export function RunsScreen() {
  const { runs } = useCatalogData()
  const [search, setSearch] = useState("")
  const [selected, setSelected] = useState<Run | null>(null)
  const [statusFilter, setStatusFilter] = useState<string>("all")

  const filtered = runs.filter((r) => {
    const matchSearch =
      r.wf.toLowerCase().includes(search.toLowerCase()) ||
      r.id.toLowerCase().includes(search.toLowerCase())
    const matchStatus = statusFilter === "all" || r.status === statusFilter
    return matchSearch && matchStatus
  })

  if (selected) {
    return <RunDetail run={selected} onBack={() => setSelected(null)} />
  }

  const statusCounts = {
    all: runs.length,
    PAUSED: runs.filter((r) => r.status === "PAUSED").length,
    FAILED: runs.filter((r) => r.status === "FAILED").length,
    SUCCESS: runs.filter((r) => r.status === "SUCCESS").length,
    running: runs.filter((r) => r.status === "running").length,
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">Runs</h1>
        <p className="text-sm text-muted-foreground mt-1">
          {runs.length} total runs &middot; {statusCounts.FAILED} failed &middot; {statusCounts.PAUSED} paused
        </p>
      </div>

      <div className="flex items-center gap-3 flex-wrap">
        <div className="relative flex-1 min-w-[200px]">
          <Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Filter by workflow or run ID..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9 h-9 bg-secondary border-0 text-sm placeholder:text-muted-foreground"
          />
        </div>
        <div className="flex gap-1">
          {(["all", "PAUSED", "FAILED", "SUCCESS"] as const).map((status) => (
            <button
              key={status}
              onClick={() => setStatusFilter(status)}
              className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-all ${
                statusFilter === status
                  ? "bg-[hsl(var(--primary))]/15 text-[hsl(var(--primary))] ring-1 ring-[hsl(var(--primary))]/20"
                  : "text-muted-foreground hover:bg-accent hover:text-foreground"
              }`}
            >
              {status === "all" ? "all" : status.toLowerCase()}
              <span className="text-[10px] tabular-nums opacity-60">{statusCounts[status]}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Runs list */}
      <div className="rounded-xl border border-border bg-card overflow-hidden divide-y divide-border">
        <div className="grid grid-cols-[auto_auto_1fr_1fr_auto_auto_auto] items-center gap-4 px-5 py-2.5 bg-secondary/30">
          <span className="w-8 text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">Status</span>
          <span className="w-14" />
          <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">Run</span>
          <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">Workflow</span>
          <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold w-32">Progress</span>
          <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold w-20 text-right">Duration</span>
          <span className="w-4" />
        </div>

        {filtered.map((run) => {
          const actionCount = Object.keys(run.actions).length
          return (
          <button
            key={run.id}
            className="grid grid-cols-[auto_auto_1fr_1fr_auto_auto_auto] items-center gap-4 px-5 py-3 w-full text-left hover:bg-accent/30 transition-colors"
            onClick={() => setSelected(run)}
          >
            <RunStatusIcon status={run.status} />
            <span className="text-[10px] font-medium w-14" style={{ color: `hsl(var(${statusColorVar[run.status] || "--muted-foreground"}))` }}>
              {run.status.toLowerCase()}
            </span>
            <div className="min-w-0">
              <span className="text-xs font-mono text-[hsl(var(--primary))]">{run.id.replace(/^run_.*?_(\d{8}_\d{6})$/, "#$1").replace(/^run_/, "")}</span>
              <div className="flex items-center gap-1.5 mt-0.5">
                <span className="text-[10px] font-mono text-muted-foreground tabular-nums">
                  {formatTimestampShort(run.started)}
                </span>
                {actionCount > 0 && (
                  <span className="text-[10px] text-muted-foreground">
                    {actionCount} action{actionCount !== 1 ? "s" : ""} tracked
                  </span>
                )}
              </div>
            </div>
            <span className="text-sm font-mono text-foreground truncate">{run.wf}</span>
            <div className="flex items-center gap-2 w-32">
              <div className="flex-1 h-1.5 rounded-full bg-secondary overflow-hidden flex">
                {run.success > 0 && (
                  <div
                    className="h-full transition-all duration-500"
                    style={{
                      width: `${run.total > 0 ? (run.success / run.total) * 100 : 0}%`,
                      backgroundColor: "hsl(var(--success))",
                    }}
                  />
                )}
                {run.failed > 0 && (
                  <div
                    className="h-full transition-all duration-500"
                    style={{
                      width: `${run.total > 0 ? (run.failed / run.total) * 100 : 0}%`,
                      backgroundColor: "hsl(var(--destructive))",
                    }}
                  />
                )}
                {run.skipped > 0 && (
                  <div
                    className="h-full transition-all duration-500"
                    style={{
                      width: `${run.total > 0 ? (run.skipped / run.total) * 100 : 0}%`,
                      backgroundColor: "hsl(var(--muted-foreground))",
                      opacity: 0.35,
                    }}
                  />
                )}
              </div>
              <span className="text-[10px] font-mono text-muted-foreground tabular-nums whitespace-nowrap">
                {run.success + run.failed + run.skipped}/{run.total}
              </span>
            </div>
            <span className="text-xs font-mono text-muted-foreground tabular-nums w-20 text-right">{formatDuration(run.duration)}</span>
            <ArrowRight className="h-3.5 w-3.5 text-muted-foreground/40" />
          </button>
          )
        })}

        {filtered.length === 0 && (
          <div className="flex items-center justify-center py-16 text-sm text-muted-foreground">
            No runs match the current filters
          </div>
        )}
      </div>
    </div>
  )
}

function RunDetail({ run, onBack }: { run: Run; onBack: () => void }) {
  const actionEntries = Object.entries(run.actions)

  return (
    <div className="flex flex-col gap-6">
      {/* Header */}
      <div className="flex items-center gap-4">
        <button
          onClick={onBack}
          className="flex h-8 w-8 items-center justify-center rounded-lg border border-border bg-card text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
        >
          <ArrowLeft className="h-4 w-4" />
        </button>
        <div className="flex-1">
          <div className="flex items-center gap-2.5">
            <h1 className="text-xl font-mono font-semibold text-foreground">{run.id}</h1>
            <RunStatusBadge status={run.status} />
          </div>
          <p className="text-sm text-muted-foreground mt-1">
            {run.wf} &middot; {formatDuration(run.duration)} &middot; {run.success}/{run.total} actions
            {run.failed > 0 && <> &middot; <span className="text-[hsl(var(--destructive))]">{run.failed} failed</span></>}
            {run.skipped > 0 && <> &middot; {run.skipped} skipped</>}
          </p>
        </div>
      </div>

      {/* Run info */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <InfoCard label="Workflow" value={run.wf} />
        <InfoCard label="Started" value={formatTimestamp(run.started)} />
        {run.ended && <InfoCard label="Ended" value={formatTimestamp(run.ended)} />}
        <InfoCard label="Duration" value={formatDuration(run.duration)} />
        <InfoCard label="Tokens" value={run.tokens.toLocaleString()} />
        <InfoCard label="Succeeded" value={`${run.success} / ${run.total}`} />
        {run.failed > 0 && <InfoCard label="Failed" value={String(run.failed)} />}
        {run.skipped > 0 && <InfoCard label="Skipped" value={String(run.skipped)} />}
      </div>

      {/* Error */}
      {run.error && <ErrorBlock error={run.error} />}

      {/* Execution timeline (Gantt) */}
      {actionEntries.length > 0 && <ExecutionTimeline run={run} />}

      {/* Action execution timeline */}
      {actionEntries.length > 0 && (
        <div className="rounded-xl border border-border bg-card p-5">
          <h3 className="text-sm font-medium text-foreground mb-4">Action Execution</h3>
          <div className="flex flex-col gap-0">
            {actionEntries.map(([name, a], i) => {
              const color =
                a.status === "success" ? "hsl(var(--success))"
                : a.status === "running" ? "hsl(var(--primary))"
                : a.status === "failed" ? "hsl(var(--destructive))"
                : "hsl(var(--muted-foreground))"

              return (
                <div key={name} className="flex items-stretch gap-4">
                  <div className="flex flex-col items-center w-8 shrink-0">
                    <div
                      className="flex h-7 w-7 items-center justify-center rounded-full ring-1"
                      style={{
                        backgroundColor: `${color}15`,
                        boxShadow: `0 0 0 1px ${color}25`,
                      }}
                    >
                      <span className="text-[10px] font-mono font-semibold" style={{ color }}>
                        {i + 1}
                      </span>
                    </div>
                    {i < actionEntries.length - 1 && (
                      <div
                        className="flex-1 w-px my-1"
                        style={{
                          backgroundColor: a.status === "success" ? "hsl(var(--success))" : "hsl(var(--border))",
                          opacity: a.status === "success" ? 0.3 : 0.5,
                        }}
                      />
                    )}
                  </div>

                  <div className="flex-1 flex items-center justify-between pb-4 min-h-[40px]">
                    <div className="flex items-center gap-2">
                      <Badge
                        variant="outline"
                        className={`w-14 justify-center text-[10px] font-normal rounded-md ${
                          a.type === "llm"
                            ? "bg-purple-500/10 text-purple-400 border-purple-500/20"
                            : "bg-emerald-500/10 text-emerald-400 border-emerald-500/20"
                        }`}
                      >
                        {a.type}
                      </Badge>
                      <span className="text-sm font-mono text-foreground">{name}</span>
                      <Badge
                        variant="outline"
                        className="text-[10px] font-normal rounded-md"
                        style={{
                          backgroundColor: `${color}10`,
                          color,
                          borderColor: `${color}25`,
                        }}
                      >
                        {a.status === "running" && <span className="mr-1 inline-block h-1.5 w-1.5 rounded-full animate-pulse" style={{ backgroundColor: color }} />}
                        {a.status}
                      </Badge>
                    </div>
                    <div className="flex items-center gap-3">
                      {a.vendor && (
                        <span className="text-[10px] font-mono text-muted-foreground/60">{a.vendor}</span>
                      )}
                      {a.model && (
                        <span className="text-[10px] font-mono text-purple-400">{a.model}</span>
                      )}
                      {a.impl && (
                        <span className="text-[10px] font-mono text-emerald-400">{a.impl}()</span>
                      )}
                      {a.started && (
                        <span className="text-[10px] font-mono text-muted-foreground/50 tabular-nums">
                          {a.started.split("T")[1]?.slice(0, 8)}
                        </span>
                      )}
                      <span className="text-xs font-mono text-muted-foreground tabular-nums">
                        {a.dur > 0 ? formatDuration(a.dur) : "\u2014"}
                      </span>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {actionEntries.length === 0 && (
        <div className="rounded-xl border border-border bg-card p-5">
          <p className="text-sm text-muted-foreground text-center py-8">
            No action execution data recorded for this run
          </p>
        </div>
      )}

      {/* Run Summary */}
      <div className="rounded-lg border border-border bg-card overflow-hidden">
        <div className="flex items-center justify-between border-b border-border px-4 py-2">
          <span className="text-xs font-semibold text-foreground">Run Summary</span>
          <span className="text-[10px] font-mono text-muted-foreground">JSON</span>
        </div>
        <div className="p-5">
          <pre className="text-xs font-mono text-foreground/80 leading-relaxed">
{JSON.stringify({
  run_id: run.id,
  workflow: run.wf,
  status: run.status,
  started: run.started,
  ...(run.ended ? { ended: run.ended } : {}),
  duration: formatDuration(run.duration),
  actions_succeeded: run.success,
  actions_failed: run.failed,
  actions_skipped: run.skipped,
  actions_total: run.total,
  tokens: run.tokens,
}, null, 2)}
          </pre>
        </div>
      </div>
    </div>
  )
}

/* --- Error display --- */

function ErrorBlock({ error }: { error: string }) {
  const [expanded, setExpanded] = useState(false)
  const lines = error.trimEnd().split("\n")
  // Heuristic: last non-empty line is typically the root cause in Python tracebacks.
  // For other error formats this still gives a reasonable one-liner.
  const summary = lines.filter((l) => l.trim()).pop() || error.slice(0, 200)
  const hasTraceback = lines.length > 1

  return (
    <div className="rounded-xl border border-[hsl(var(--destructive))]/20 bg-[hsl(var(--destructive))]/5 p-4">
      <span className="text-[10px] uppercase tracking-wider text-[hsl(var(--destructive))] font-semibold block mb-2">Error</span>
      <p className="text-xs font-mono text-[hsl(var(--destructive))] font-medium leading-relaxed">{summary}</p>
      {hasTraceback && (
        <>
          <button
            onClick={() => setExpanded(!expanded)}
            className="text-[10px] text-[hsl(var(--destructive))]/60 hover:text-[hsl(var(--destructive))] mt-2 transition-colors"
          >
            {expanded ? "Hide traceback" : "Show full traceback"}
          </button>
          {expanded && (
            <pre className="text-[10px] font-mono text-[hsl(var(--destructive))]/70 leading-relaxed mt-2 max-h-64 overflow-y-auto overflow-x-auto whitespace-pre-wrap border-t border-[hsl(var(--destructive))]/10 pt-2">
              {error}
            </pre>
          )}
        </>
      )}
    </div>
  )
}

/* --- Status components --- */

function RunStatusIcon({ status }: { status: RunStatus }) {
  const map: Record<string, React.ReactNode> = {
    SUCCESS: (
      <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-[hsl(var(--success))]/15 ring-1 ring-[hsl(var(--success))]/20">
        <CheckCircle2 className="h-3.5 w-3.5 text-[hsl(var(--success))]" />
      </div>
    ),
    FAILED: (
      <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-[hsl(var(--destructive))]/15 ring-1 ring-[hsl(var(--destructive))]/20">
        <XCircle className="h-3.5 w-3.5 text-[hsl(var(--destructive))]" />
      </div>
    ),
    running: (
      <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-[hsl(var(--primary))]/15 ring-1 ring-[hsl(var(--primary))]/20">
        <Loader2 className="h-3.5 w-3.5 text-[hsl(var(--primary))] animate-spin" />
      </div>
    ),
    PAUSED: (
      <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-[hsl(var(--warning))]/15 ring-1 ring-[hsl(var(--warning))]/20">
        <Pause className="h-3.5 w-3.5 text-[hsl(var(--warning))]" />
      </div>
    ),
  }
  return <>{map[status] || map.PAUSED}</>
}

function RunStatusBadge({ status }: { status: RunStatus }) {
  const styles: Record<string, string> = {
    SUCCESS: "bg-[hsl(var(--success))]/10 text-[hsl(var(--success))] border-[hsl(var(--success))]/20",
    FAILED: "bg-[hsl(var(--destructive))]/10 text-[hsl(var(--destructive))] border-[hsl(var(--destructive))]/20",
    running: "bg-[hsl(var(--primary))]/10 text-[hsl(var(--primary))] border-[hsl(var(--primary))]/20",
    PAUSED: "bg-[hsl(var(--warning))]/10 text-[hsl(var(--warning))] border-[hsl(var(--warning))]/20",
  }
  return (
    <Badge variant="outline" className={`text-[10px] font-normal rounded-md ${styles[status] || ""}`}>
      {status === "running" && <span className="mr-1 inline-block h-1.5 w-1.5 rounded-full bg-[hsl(var(--primary))] animate-pulse" />}
      {status.toLowerCase()}
    </Badge>
  )
}

/* --- Execution timeline (Gantt) --- */

function ExecutionTimeline({ run }: { run: Run }) {
  const entries = Object.entries(run.actions)
  const runStart = new Date(run.started).getTime()
  const runEnd = run.ended ? new Date(run.ended).getTime() : runStart + run.duration * 1000

  // Compute absolute start/end for each action in seconds from run start
  const bars = entries.map(([name, a]) => {
    let startSec: number | null = null
    let endSec: number | null = null

    if (a.started) {
      startSec = (new Date(a.started).getTime() - runStart) / 1000
    }
    if (a.ended) {
      endSec = (new Date(a.ended).getTime() - runStart) / 1000
    }

    // Derive missing values from dur
    if (startSec != null && endSec == null && a.dur > 0) {
      endSec = startSec + a.dur
    }
    if (endSec != null && startSec == null && a.dur > 0) {
      startSec = endSec - a.dur
    }

    return { name, action: a, startSec, endSec }
  })

  // Check if we have enough timing data for a real timeline
  const barsWithTiming = bars.filter((b) => b.startSec != null && b.endSec != null)

  // If no bars have timing data, fall back to a sequential layout based on completed_at order
  if (barsWithTiming.length === 0) {
    // Use completion timestamps to build a relative view
    const completionBars = bars
      .filter((b) => b.endSec != null)
      .sort((a, b) => a.endSec! - b.endSec!)

    if (completionBars.length === 0) return null

    const maxEnd = Math.max(...completionBars.map((b) => b.endSec!))
    if (maxEnd <= 0) return null

    return (
      <div className="rounded-xl border border-border bg-card p-5">
        <h3 className="text-sm font-medium text-foreground mb-4">Execution Timeline</h3>
        <div className="flex flex-col gap-1.5">
          {completionBars.map(({ name, action: a, endSec }) => {
            const pctEnd = (endSec! / maxEnd) * 100
            const barWidth = Math.max(pctEnd, 2)
            const color =
              a.status === "success" ? "hsl(var(--success))"
              : a.status === "failed" ? "hsl(var(--destructive))"
              : a.status === "skipped" ? "hsl(var(--muted-foreground))"
              : "hsl(var(--primary))"

            return (
              <div key={name} className="flex items-center gap-3 h-7">
                <span className="text-[10px] font-mono text-muted-foreground w-[140px] truncate text-right shrink-0">
                  {name}
                </span>
                <div className="flex-1 relative h-5">
                  <div
                    className="absolute top-0.5 h-4 rounded-sm transition-all duration-300"
                    style={{
                      left: 0,
                      width: `${barWidth}%`,
                      backgroundColor: color,
                      opacity: a.status === "skipped" ? 0.3 : 0.7,
                    }}
                  />
                </div>
                <span className="text-[10px] font-mono text-muted-foreground/60 tabular-nums w-12 text-right shrink-0">
                  {a.dur > 0 ? formatDuration(a.dur) : "\u2014"}
                </span>
              </div>
            )
          })}
        </div>
        {/* Time axis */}
        <div className="flex items-center gap-3 mt-2">
          <span className="w-[140px] shrink-0" />
          <div className="flex-1 flex justify-between">
            <span className="text-[9px] font-mono text-muted-foreground/40">0s</span>
            <span className="text-[9px] font-mono text-muted-foreground/40">{formatDuration(maxEnd)}</span>
          </div>
          <span className="w-12 shrink-0" />
        </div>
      </div>
    )
  }

  // Full timeline with start/end data
  const maxEnd = Math.max(...barsWithTiming.map((b) => b.endSec!), run.duration)
  if (maxEnd <= 0) return null

  return (
    <div className="rounded-xl border border-border bg-card p-5">
      <h3 className="text-sm font-medium text-foreground mb-4">Execution Timeline</h3>
      <div className="flex flex-col gap-1.5">
        {bars.map(({ name, action: a, startSec, endSec }) => {
          const hasData = startSec != null && endSec != null
          const pctLeft = hasData ? (startSec! / maxEnd) * 100 : 0
          const pctWidth = hasData ? Math.max(((endSec! - startSec!) / maxEnd) * 100, 1) : 0
          const color =
            a.status === "success" ? "hsl(var(--success))"
            : a.status === "failed" ? "hsl(var(--destructive))"
            : a.status === "skipped" ? "hsl(var(--muted-foreground))"
            : "hsl(var(--primary))"

          return (
            <div key={name} className="flex items-center gap-3 h-7">
              <span className="text-[10px] font-mono text-muted-foreground w-[140px] truncate text-right shrink-0">
                {name}
              </span>
              <div className="flex-1 relative h-5">
                {hasData ? (
                  <div
                    className="absolute top-0.5 h-4 rounded-sm transition-all duration-300"
                    style={{
                      left: `${pctLeft}%`,
                      width: `${pctWidth}%`,
                      backgroundColor: color,
                      opacity: a.status === "skipped" ? 0.3 : 0.7,
                    }}
                  />
                ) : (
                  <div
                    className="absolute top-0.5 h-4 rounded-sm"
                    style={{
                      left: 0,
                      width: "100%",
                      backgroundColor: color,
                      opacity: 0.08,
                    }}
                  />
                )}
              </div>
              <span className="text-[10px] font-mono text-muted-foreground/60 tabular-nums w-12 text-right shrink-0">
                {a.dur > 0 ? formatDuration(a.dur) : "\u2014"}
              </span>
            </div>
          )
        })}
      </div>
      {/* Time axis */}
      <div className="flex items-center gap-3 mt-2">
        <span className="w-[140px] shrink-0" />
        <div className="flex-1 flex justify-between">
          <span className="text-[9px] font-mono text-muted-foreground/40">0s</span>
          {maxEnd > 10 && (
            <span className="text-[9px] font-mono text-muted-foreground/40">{formatDuration(maxEnd / 2)}</span>
          )}
          <span className="text-[9px] font-mono text-muted-foreground/40">{formatDuration(maxEnd)}</span>
        </div>
        <span className="w-12 shrink-0" />
      </div>
    </div>
  )
}

function InfoCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">{label}</span>
      <p className="text-sm font-mono text-foreground mt-1 truncate">{value}</p>
    </div>
  )
}
