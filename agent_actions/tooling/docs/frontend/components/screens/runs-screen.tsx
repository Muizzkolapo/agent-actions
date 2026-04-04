"use client"

import React from "react"
import { useState } from "react"
import { Search, ArrowRight, ArrowLeft, CheckCircle2, XCircle, Loader2, Pause, ChevronDown, Clock, Zap, Hash } from "lucide-react"
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
  const [jsonOpen, setJsonOpen] = useState(false)
  const statusColor = `hsl(var(${statusColorVar[run.status] || "--muted-foreground"}))`

  // Compute Gantt data for inline timeline bars
  const runStart = new Date(run.started).getTime()
  const ganttBars = actionEntries.map(([name, a]) => {
    let startSec: number | null = null
    let endSec: number | null = null
    if (a.started) startSec = (new Date(a.started).getTime() - runStart) / 1000
    if (a.ended) endSec = (new Date(a.ended).getTime() - runStart) / 1000
    if (startSec != null && endSec == null && a.dur > 0) endSec = startSec + a.dur
    if (endSec != null && startSec == null && a.dur > 0) startSec = endSec - a.dur
    return { name, startSec, endSec }
  })
  const barsWithTiming = ganttBars.filter((b) => b.startSec != null && b.endSec != null)
  const showGantt = barsWithTiming.length >= 2
  const ganttMax = showGantt ? Math.max(...barsWithTiming.map((b) => b.endSec!), run.duration) : 0
  const ganttMap = new Map(ganttBars.map((b) => [b.name, b]))

  return (
    <div className="flex flex-col gap-5">
      {/* ── Header ─────────────────────────────────────────────────────── */}
      <div className="flex items-start gap-4">
        <button
          onClick={onBack}
          className="flex h-8 w-8 items-center justify-center rounded-lg border border-border bg-card text-muted-foreground hover:text-foreground hover:bg-accent transition-colors mt-0.5"
        >
          <ArrowLeft className="h-4 w-4" />
        </button>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2.5 flex-wrap">
            <h1 className="text-lg font-mono font-semibold text-foreground truncate">{run.id}</h1>
            <RunStatusBadge status={run.status} />
          </div>
          <div className="flex items-center gap-2 mt-1.5 text-xs text-muted-foreground flex-wrap">
            <span className="font-mono">{run.wf}</span>
            <span className="opacity-30">/</span>
            <span className="tabular-nums">{formatTimestamp(run.started)}</span>
            {run.ended && (
              <>
                <span className="opacity-30">&rarr;</span>
                <span className="tabular-nums">{formatTimestamp(run.ended)}</span>
              </>
            )}
          </div>
        </div>
      </div>

      {/* ── Error (if failed — immediately visible) ────────────────────── */}
      {run.error && <ErrorBlock error={run.error} />}

      {/* ── Stats strip ────────────────────────────────────────────────── */}
      <div className="grid grid-cols-4 gap-px rounded-xl overflow-hidden border border-border bg-border">
        <StatCell icon={<Clock className="h-3.5 w-3.5" />} label="Duration" value={formatDuration(run.duration)} />
        <StatCell icon={<Hash className="h-3.5 w-3.5" />} label="Actions" value={`${run.success + run.failed + run.skipped} / ${run.total}`} accent={run.failed > 0 ? "destructive" : undefined} />
        <StatCell icon={<Zap className="h-3.5 w-3.5" />} label="Tokens" value={run.tokens > 0 ? run.tokens.toLocaleString() : "—"} />
        <StatCell
          icon={
            run.status === "FAILED"
              ? <XCircle className="h-3.5 w-3.5" />
              : <CheckCircle2 className="h-3.5 w-3.5" />
          }
          label="Result"
          value={run.failed > 0 ? `${run.failed} failed` : run.success > 0 ? `${run.success} passed` : run.status.toLowerCase()}
          accent={run.failed > 0 ? "destructive" : run.success > 0 ? "success" : undefined}
        />
      </div>

      {/* ── Action Execution (with inline Gantt when 2+ actions) ────── */}
      {actionEntries.length > 0 ? (
        <div className="rounded-xl border border-border bg-card overflow-hidden">
          <div className="flex items-center justify-between px-5 py-3 border-b border-border">
            <h3 className="text-sm font-medium text-foreground">Actions</h3>
            {showGantt && (
              <span className="text-[10px] text-muted-foreground tabular-nums">
                0s — {formatDuration(ganttMax)}
              </span>
            )}
          </div>
          <div className="divide-y divide-border">
            {actionEntries.map(([name, a], i) => {
              const color = actionStatusColor(a.status)
              const gantt = ganttMap.get(name)
              const hasGanttData = showGantt && gantt?.startSec != null && gantt?.endSec != null

              return (
                <div key={name} className="px-5 py-3">
                  {/* Row 1: identity + metadata */}
                  <div className="flex items-center gap-2.5">
                    {/* Step indicator */}
                    <div
                      className="flex h-6 w-6 items-center justify-center rounded-full shrink-0"
                      style={{ backgroundColor: `${color}15`, boxShadow: `0 0 0 1px ${color}25` }}
                    >
                      <span className="text-[9px] font-mono font-bold" style={{ color }}>{i + 1}</span>
                    </div>

                    {/* Type badge */}
                    <Badge
                      variant="outline"
                      className={`w-12 justify-center text-[9px] font-normal rounded-md shrink-0 ${
                        a.type === "llm"
                          ? "bg-purple-500/10 text-purple-400 border-purple-500/20"
                          : "bg-emerald-500/10 text-emerald-400 border-emerald-500/20"
                      }`}
                    >
                      {a.type}
                    </Badge>

                    {/* Name */}
                    <span className="text-sm font-mono text-foreground truncate">{name}</span>

                    {/* Status */}
                    <Badge
                      variant="outline"
                      className="text-[9px] font-normal rounded-md shrink-0"
                      style={{ backgroundColor: `${color}10`, color, borderColor: `${color}25` }}
                    >
                      {a.status === "running" && <span className="mr-1 inline-block h-1.5 w-1.5 rounded-full animate-pulse" style={{ backgroundColor: color }} />}
                      {a.status}
                    </Badge>

                    {/* Spacer */}
                    <div className="flex-1" />

                    {/* Right-side metadata */}
                    <div className="flex items-center gap-2.5 shrink-0">
                      {a.vendor && <span className="text-[10px] font-mono text-muted-foreground/50">{a.vendor}</span>}
                      {a.model && <span className="text-[10px] font-mono text-purple-400/80">{a.model}</span>}
                      {a.impl && <span className="text-[10px] font-mono text-emerald-400/80">{a.impl}()</span>}
                      {a.started && (
                        <span className="text-[10px] font-mono text-muted-foreground/40 tabular-nums">
                          {a.started.split("T")[1]?.slice(0, 8)}
                        </span>
                      )}
                      <span className="text-xs font-mono text-muted-foreground tabular-nums font-medium w-10 text-right">
                        {a.dur > 0 ? formatDuration(a.dur) : "\u2014"}
                      </span>
                    </div>
                  </div>

                  {/* Row 2: inline Gantt bar (only when 2+ actions have timing) */}
                  {showGantt && (
                    <div className="mt-2 ml-[calc(1.5rem+0.625rem)] mr-[2.5rem]">
                      <div className="relative h-2 rounded-full bg-secondary overflow-hidden">
                        {hasGanttData ? (
                          <div
                            className="absolute top-0 h-full rounded-full transition-all duration-500"
                            style={{
                              left: `${(gantt!.startSec! / ganttMax) * 100}%`,
                              width: `${Math.max(((gantt!.endSec! - gantt!.startSec!) / ganttMax) * 100, 1)}%`,
                              backgroundColor: color,
                              opacity: a.status === "skipped" ? 0.3 : 0.65,
                            }}
                          />
                        ) : (
                          <div
                            className="absolute top-0 h-full rounded-full"
                            style={{ left: 0, width: "100%", backgroundColor: color, opacity: 0.06 }}
                          />
                        )}
                      </div>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      ) : (
        <div className="rounded-xl border border-border bg-card p-5">
          <p className="text-sm text-muted-foreground text-center py-6">
            No action execution data recorded for this run
          </p>
        </div>
      )}

      {/* ── Run Summary (collapsed by default) ─────────────────────────── */}
      <div className="rounded-xl border border-border bg-card overflow-hidden">
        <button
          onClick={() => setJsonOpen(!jsonOpen)}
          className="flex items-center justify-between w-full px-5 py-3 text-left hover:bg-accent/30 transition-colors"
        >
          <span className="text-xs font-medium text-foreground">Run Summary</span>
          <div className="flex items-center gap-2">
            <span className="text-[10px] font-mono text-muted-foreground">JSON</span>
            <ChevronDown className={`h-3.5 w-3.5 text-muted-foreground transition-transform ${jsonOpen ? "rotate-180" : ""}`} />
          </div>
        </button>
        {jsonOpen && (
          <div className="px-5 pb-5 border-t border-border">
            <pre className="text-xs font-mono text-foreground/80 leading-relaxed mt-4 overflow-x-auto">
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
        )}
      </div>
    </div>
  )
}

/* --- Stats strip cell --- */

function StatCell({
  icon,
  label,
  value,
  accent,
}: {
  icon: React.ReactNode
  label: string
  value: string
  accent?: "destructive" | "success"
}) {
  const accentColor = accent === "destructive"
    ? "text-[hsl(var(--destructive))]"
    : accent === "success"
      ? "text-[hsl(var(--success))]"
      : "text-foreground"

  return (
    <div className="bg-card px-4 py-3">
      <div className="flex items-center gap-1.5 mb-1">
        <span className="text-muted-foreground">{icon}</span>
        <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-medium">{label}</span>
      </div>
      <p className={`text-sm font-mono font-medium tabular-nums ${accentColor}`}>{value}</p>
    </div>
  )
}

/* --- Error display --- */

function ErrorBlock({ error }: { error: string }) {
  const [expanded, setExpanded] = useState(false)
  const lines = error.trimEnd().split("\n")
  const summary = lines.filter((l) => l.trim()).pop() || error.slice(0, 200)
  const hasTraceback = lines.length > 1

  return (
    <div className="rounded-xl border-l-4 border-[hsl(var(--destructive))] bg-[hsl(var(--destructive))]/5 px-5 py-4">
      <p className="text-sm font-mono text-[hsl(var(--destructive))] font-medium leading-relaxed">{summary}</p>
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

function actionStatusColor(status: string): string {
  if (status === "success") return "hsl(var(--success))"
  if (status === "failed") return "hsl(var(--destructive))"
  if (status === "skipped") return "hsl(var(--muted-foreground))"
  return "hsl(var(--primary))"
}
