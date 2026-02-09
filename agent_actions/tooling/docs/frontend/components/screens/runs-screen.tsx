"use client"

import React from "react"
import { useState } from "react"
import { Search, ArrowRight, ArrowLeft, CheckCircle2, XCircle, Loader2, Clock, Pause } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs"
import { useCatalogData } from "@/lib/catalog-context"
import type { Run, RunStatus } from "@/lib/mock-data"

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
        <div className="grid grid-cols-[auto_1fr_1fr_auto_auto_auto] items-center gap-4 px-5 py-2.5 bg-secondary/30">
          <span className="w-8 text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">Status</span>
          <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">Run</span>
          <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">Workflow</span>
          <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold w-32">Progress</span>
          <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold w-20 text-right">Duration</span>
          <span className="w-4" />
        </div>

        {filtered.map((run) => (
          <button
            key={run.id}
            className="grid grid-cols-[auto_1fr_1fr_auto_auto_auto] items-center gap-4 px-5 py-3 w-full text-left hover:bg-accent/30 transition-colors"
            onClick={() => setSelected(run)}
          >
            <RunStatusIcon status={run.status} />
            <div className="min-w-0">
              <span className="text-xs font-mono text-[hsl(var(--primary))]">{run.id.replace("run_qanalabs_quiz_gen_", "quiz_gen#")}</span>
              <div className="flex items-center gap-1.5 mt-0.5">
                <span className="text-[10px] font-mono text-muted-foreground tabular-nums">
                  {run.started.split("T")[1]?.slice(0, 5)}
                </span>
                {Object.keys(run.actions).length > 0 && (
                  <span className="text-[10px] text-muted-foreground">{Object.keys(run.actions).length} tracked</span>
                )}
              </div>
            </div>
            <span className="text-sm font-mono text-foreground truncate">{run.wf}</span>
            <div className="flex items-center gap-2 w-32">
              <div className="flex-1 h-1.5 rounded-full bg-secondary overflow-hidden">
                <div
                  className="h-full rounded-full transition-all duration-500"
                  style={{
                    width: `${run.total > 0 ? (run.success / run.total) * 100 : 0}%`,
                    backgroundColor:
                      run.status === "FAILED" ? "hsl(var(--destructive))"
                      : run.status === "PAUSED" ? "hsl(var(--warning))"
                      : "hsl(var(--success))",
                  }}
                />
              </div>
              <span className="text-[10px] font-mono text-muted-foreground tabular-nums whitespace-nowrap">
                {run.success}/{run.total}
              </span>
            </div>
            <span className="text-xs font-mono text-muted-foreground tabular-nums w-20 text-right">{run.duration}s</span>
            <ArrowRight className="h-3.5 w-3.5 text-muted-foreground/40" />
          </button>
        ))}

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
            {run.wf} &middot; {run.duration}s &middot; {run.success}/{run.total} actions
          </p>
        </div>
      </div>

      {/* Run info */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <InfoCard label="Workflow" value={run.wf} />
        <InfoCard label="Started" value={run.started} />
        <InfoCard label="Duration" value={`${run.duration}s`} />
        <InfoCard label="Tokens" value={String(run.tokens)} />
      </div>

      {/* Error */}
      {run.error && (
        <div className="rounded-xl border border-[hsl(var(--destructive))]/20 bg-[hsl(var(--destructive))]/5 p-4">
          <span className="text-[10px] uppercase tracking-wider text-[hsl(var(--destructive))] font-semibold block mb-1">Error</span>
          <p className="text-xs font-mono text-[hsl(var(--destructive))] leading-relaxed">{run.error}</p>
        </div>
      )}

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
                      {a.model && (
                        <span className="text-[10px] font-mono text-purple-400">{a.model}</span>
                      )}
                      {a.impl && (
                        <span className="text-[10px] font-mono text-emerald-400">{a.impl}()</span>
                      )}
                      <span className="text-xs font-mono text-muted-foreground tabular-nums">
                        {a.dur > 0 ? `${a.dur}s` : "\u2014"}
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

      {/* Artifacts tab */}
      <div className="rounded-xl border border-border bg-card overflow-hidden">
        <div className="flex items-center gap-2 border-b border-border px-4 py-2.5 bg-secondary/30">
          <div className="flex gap-1.5">
            <div className="h-2.5 w-2.5 rounded-full bg-[hsl(var(--destructive))]/60" />
            <div className="h-2.5 w-2.5 rounded-full bg-[hsl(var(--warning))]/60" />
            <div className="h-2.5 w-2.5 rounded-full bg-[hsl(var(--success))]/60" />
          </div>
          <span className="text-[10px] font-mono text-muted-foreground ml-2">run-summary.json</span>
        </div>
        <div className="p-5">
          <pre className="text-xs font-mono text-foreground/80 leading-relaxed">
{`{
  "run_id": "${run.id}",
  "workflow": "${run.wf}",
  "status": "${run.status}",
  "actions_completed": ${run.success},
  "actions_total": ${run.total},
  "duration": "${run.duration}s",
  "tokens": ${run.tokens}
}`}
          </pre>
        </div>
      </div>
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

function InfoCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">{label}</span>
      <p className="text-sm font-mono text-foreground mt-1 truncate">{value}</p>
    </div>
  )
}
