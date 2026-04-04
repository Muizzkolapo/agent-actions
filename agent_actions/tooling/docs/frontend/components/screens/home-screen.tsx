"use client"

import React from "react"

import { Play, AlertTriangle, Clock, ArrowRight, CheckCircle2, Circle, GitBranch, Boxes, Activity, ShieldCheck } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { useCatalogData } from "@/lib/catalog-context"

interface HomeScreenProps {
  onNavigate: (section: string) => void
}

export function HomeScreen({ onNavigate }: HomeScreenProps) {
  const { stats, workflows, runs, validationErrorGroups, validationWarningGroups } = useCatalogData()
  const successRuns = runs.filter((r) => r.status === "SUCCESS").length
  const failedRuns = runs.filter((r) => r.status === "FAILED").length
  const runningWfs = workflows.filter((w) => w.manifestStatus === "running").length
  const successRate = runs.length > 0 ? Math.round((successRuns / runs.length) * 100) : 0
  const totalIssues = stats.validation_errors + stats.validation_warnings

  return (
    <div className="flex flex-col gap-4">
      {/* ── Dashboard Stats ───────────────────────────────────────────── */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard
          label="Workflows"
          value={stats.total_workflows}
          accent="primary"
          sub={runningWfs > 0 ? `${runningWfs} active` : "All idle"}
          subColor={runningWfs > 0 ? "text-[hsl(var(--primary))]" : undefined}
          sparkData={[3, 5, 4, 7, 6, 8, stats.total_workflows]}
          onClick={() => onNavigate("workflows")}
          delay={0}
        />
        <StatCard
          label="Actions"
          value={stats.total_actions}
          accent="primary"
          sub={`${stats.llm_actions} LLM \u00b7 ${stats.tool_actions} tool`}
          sparkData={[2, 4, 3, 5, 6, 5, stats.total_actions]}
          onClick={() => onNavigate("actions")}
          delay={60}
        />
        <StatCard
          label="Runs"
          value={runs.length}
          accent={successRate >= 80 ? "success" : successRate >= 50 ? "warning" : "destructive"}
          sub={`${successRate}% pass rate`}
          subColor={successRate >= 80 ? "text-[hsl(var(--success))]" : successRate >= 50 ? "text-[hsl(var(--warning))]" : "text-[hsl(var(--destructive))]"}
          sparkData={[1, 3, 2, 5, 4, 6, runs.length]}
          onClick={() => onNavigate("runs")}
          delay={120}
        />
        <StatCard
          label="Health"
          value={totalIssues}
          accent={totalIssues > 0 ? "destructive" : "success"}
          sub={totalIssues === 0 ? "All clear" : `${stats.validation_errors} err \u00b7 ${stats.validation_warnings} warn`}
          subColor={stats.validation_errors > 0 ? "text-[hsl(var(--destructive))]" : totalIssues === 0 ? "text-[hsl(var(--success))]" : undefined}
          sparkData={[5, 4, 6, 3, 4, 2, totalIssues]}
          onClick={() => onNavigate("logs")}
          delay={180}
        />
      </div>

      {/* ── Workflows (full width) ─────────────────────────────────────── */}
      <div
        className="rounded-lg border border-border/60 bg-card overflow-hidden animate-fade-in-up"
        style={{ animationDelay: "200ms" }}
      >
        <div className="flex items-center justify-between px-5 py-3">
          <span className="text-sm font-semibold text-foreground">
            Workflows
            <span className="ml-1.5 text-muted-foreground font-normal">{workflows.length}</span>
          </span>
          <button
            onClick={() => onNavigate("workflows")}
            className="flex items-center gap-1.5 text-[11px] font-medium text-muted-foreground hover:text-primary transition-colors"
          >
            View all
            <ArrowRight className="h-3 w-3" />
          </button>
        </div>
        <div className="divide-y divide-border">
          {workflows.map((wf, idx) => (
            <button
              key={wf.id}
              className="flex w-full items-center gap-3.5 px-5 py-3 text-left hover:bg-accent/50 transition-colors animate-fade-in-up"
              style={{ animationDelay: `${300 + idx * 50}ms` }}
              onClick={() => onNavigate("workflows")}
            >
              <WorkflowStatusDot status={wf.manifestStatus} />
              <div className="flex flex-col min-w-0 flex-1">
                <span className="text-sm font-mono font-medium text-foreground truncate">
                  {wf.name}
                </span>
                <span className="text-[11px] text-muted-foreground mt-0.5">
                  {wf.actionCount} actions
                </span>
              </div>
              <Badge variant="outline" className="text-[11px] font-mono font-normal rounded px-2 py-0.5 h-5 shrink-0">
                v{wf.version}
              </Badge>
              <span className="text-[11px] text-muted-foreground tabular-nums shrink-0">
                {wf.llmCount}L / {wf.toolCount}T
              </span>
              {wf.defaults.model_name ? (
                <Badge variant="secondary" className="text-[10px] font-mono font-normal rounded px-2 py-0.5 h-5 shrink-0">
                  {wf.defaults.model_name}
                </Badge>
              ) : (
                <span className="text-[11px] text-muted-foreground shrink-0">{"\u2014"}</span>
              )}
              <MiniBarChart values={deriveBarData(wf.llmCount, wf.toolCount, wf.actionCount)} />
            </button>
          ))}
          {workflows.length === 0 && (
            <div className="px-4 py-6 text-center text-xs text-muted-foreground">No workflows found</div>
          )}
        </div>
      </div>

      {/* ── Recent Runs + Health (side by side) ────────────────────────── */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-5">
        {/* Recent Runs (60%) */}
        <div
          className="lg:col-span-3 rounded-lg border border-border/60 bg-card overflow-hidden animate-fade-in-up"
          style={{ animationDelay: "320ms" }}
        >
          <div className="flex items-center justify-between px-5 py-3">
            <span className="text-sm font-semibold text-foreground">
              Recent runs
              <span className="ml-1.5 text-muted-foreground font-normal">{runs.length}</span>
            </span>
            <button
              onClick={() => onNavigate("runs")}
              className="flex items-center gap-1.5 text-[11px] font-medium text-muted-foreground hover:text-primary transition-colors"
            >
              View all
              <ArrowRight className="h-3 w-3" />
            </button>
          </div>
          {/* Column headers */}
          <div className="grid grid-cols-[16px_1fr_1fr_100px_56px_60px] gap-2 px-5 py-1.5 border-y border-border text-[10px] uppercase tracking-wider text-muted-foreground font-medium">
            <span />
            <span>Run ID</span>
            <span>Workflow</span>
            <span>Progress</span>
            <span className="text-right">Duration</span>
            <span className="text-right">Tokens</span>
          </div>
          <div className="divide-y divide-border">
            {runs.slice(0, 8).map((run, idx) => {
              const pct = run.total > 0 ? (run.success / run.total) * 100 : 0
              return (
                <button
                  key={run.id}
                  className="grid grid-cols-[16px_1fr_1fr_100px_56px_60px] gap-2 w-full items-center px-5 py-2 text-left hover:bg-accent/50 transition-colors animate-fade-in-up"
                  style={{ animationDelay: `${400 + idx * 40}ms` }}
                  onClick={() => onNavigate("runs")}
                >
                  <RunStatusIndicator status={run.status} />
                  <span className="text-xs font-mono text-foreground truncate">
                    {run.id.length > 30 ? run.id.slice(-20) : run.id}
                  </span>
                  <span className="text-xs text-muted-foreground truncate">
                    {run.wf}
                  </span>
                  <div className="flex items-center gap-1.5">
                    <div className="h-1 flex-1 rounded-full bg-secondary overflow-hidden">
                      <div
                        className="h-full rounded-full transition-all duration-500"
                        style={{
                          width: `${pct}%`,
                          backgroundColor:
                            run.status === "FAILED" ? "hsl(var(--destructive))"
                            : run.status === "PAUSED" ? "hsl(var(--warning))"
                            : "hsl(var(--success))",
                        }}
                      />
                    </div>
                    <span className="text-[10px] font-mono text-muted-foreground tabular-nums shrink-0">
                      {run.success}/{run.total}
                    </span>
                  </div>
                  <span className="text-xs font-mono text-foreground tabular-nums text-right">{Math.round(run.duration)}s</span>
                  <span className="text-xs font-mono text-muted-foreground tabular-nums text-right">
                    {run.tokens > 0 ? run.tokens.toLocaleString() : "\u2014"}
                  </span>
                </button>
              )
            })}
            {runs.length === 0 && (
              <div className="px-4 py-10 text-center">
                <Activity className="h-8 w-8 mx-auto text-muted-foreground/20 mb-3" />
                <p className="text-xs text-muted-foreground">No runs recorded</p>
                <p className="text-[10px] text-muted-foreground/60 mt-1">Execute a workflow to see results here</p>
              </div>
            )}
          </div>
        </div>

        {/* Health Panel (40%) */}
        <div
          className="lg:col-span-2 rounded-lg border border-border/60 bg-card overflow-hidden animate-fade-in-up"
          style={{ animationDelay: "380ms" }}
        >
          <div className="flex items-center justify-between px-5 py-3">
            <span className="text-sm font-semibold text-foreground">Health</span>
            <button
              onClick={() => onNavigate("logs")}
              className="flex items-center gap-1.5 text-[11px] font-medium text-muted-foreground hover:text-primary transition-colors"
            >
              View all
              <ArrowRight className="h-3 w-3" />
            </button>
          </div>

          {validationErrorGroups.length === 0 && validationWarningGroups.length === 0 ? (
            /* Clean state — checklist */
            <div className="px-5 py-4 space-y-4">
              <Badge className="bg-[hsl(var(--success))]/15 text-[hsl(var(--success))] border-[hsl(var(--success))]/20 hover:bg-[hsl(var(--success))]/15 text-xs font-medium px-3 py-1">
                Clean
              </Badge>
              <div className="space-y-3">
                <HealthCheckItem label="No validation issues" />
                <HealthCheckItem label="All schemas valid" />
                <HealthCheckItem label="Dependencies resolved" />
              </div>
            </div>
          ) : (
            /* Issues state — error/warning list */
            <div className="divide-y divide-border max-h-[280px] overflow-y-auto">
              {validationErrorGroups.map((g) => (
                <button
                  key={`err-${g.target}`}
                  className="flex w-full items-start gap-2.5 px-5 py-2.5 text-left hover:bg-accent/50 transition-colors"
                  onClick={() => onNavigate("logs")}
                >
                  <span className="mt-px shrink-0 rounded px-1.5 py-0 text-[10px] font-mono font-semibold bg-[hsl(var(--destructive))]/10 text-[hsl(var(--destructive))] leading-relaxed">
                    {g.count}
                  </span>
                  <div className="flex-1 min-w-0">
                    <p className="text-xs text-foreground font-mono truncate">{g.target}</p>
                    <p className="text-[10px] text-muted-foreground mt-0.5 line-clamp-1">{g.sample}</p>
                  </div>
                </button>
              ))}
              {validationWarningGroups.map((g) => (
                <button
                  key={`warn-${g.target}`}
                  className="flex w-full items-start gap-2.5 px-5 py-2.5 text-left hover:bg-accent/50 transition-colors"
                  onClick={() => onNavigate("logs")}
                >
                  <span className="mt-px shrink-0 rounded px-1.5 py-0 text-[10px] font-mono font-semibold bg-[hsl(var(--warning))]/10 text-[hsl(var(--warning))] leading-relaxed">
                    {g.count}
                  </span>
                  <div className="flex-1 min-w-0">
                    <p className="text-xs text-foreground font-mono truncate">{g.target}</p>
                    <p className="text-[10px] text-muted-foreground mt-0.5 line-clamp-1">{g.sample}</p>
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

/* -- Sub-components -- */

function StatCard({
  label,
  value,
  accent,
  sub,
  subColor,
  sparkData,
  onClick,
  delay = 0,
}: {
  label: string
  value: number
  accent: "primary" | "success" | "destructive" | "warning"
  sub: string
  subColor?: string
  sparkData: number[]
  onClick?: () => void
  delay?: number
}) {
  const accentVar = `var(--${accent})`
  return (
    <button
      onClick={onClick}
      className="group relative rounded-lg bg-card p-4 text-left animate-fade-in-up overflow-hidden"
      style={{ animationDelay: `${delay}ms` }}
    >
      {/* Gradient glow behind sparkline */}
      <div
        className="absolute inset-y-0 right-0 w-1/2 pointer-events-none"
        style={{ background: `radial-gradient(ellipse at 85% 60%, hsl(${accentVar} / 0.08), transparent 70%)` }}
      />
      {/* Sparkline */}
      <div
        className="absolute bottom-0 right-0 w-32 h-14 opacity-[0.15] group-hover:opacity-[0.25] transition-opacity animate-reveal-right pointer-events-none"
        style={{ animationDelay: `${delay + 300}ms` }}
      >
        <MiniSparkline data={sparkData} color={`hsl(${accentVar})`} />
      </div>
      <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">{label}</span>
      <div className="mt-1">
        <span className="text-3xl font-semibold font-mono tabular-nums text-foreground">
          {value.toLocaleString()}
        </span>
      </div>
      <p className={`text-xs mt-1 ${subColor || "text-muted-foreground"}`}>{sub}</p>
    </button>
  )
}

function MiniSparkline({ data, color }: { data: number[]; color: string }) {
  const max = Math.max(...data, 1)
  const h = 40
  const w = 96
  const step = w / (data.length - 1)
  const points = data.map((v, i) => `${i * step},${h - (v / max) * h * 0.8 - h * 0.1}`).join(" ")
  return (
    <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" className="w-full h-full">
      <polyline fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" points={points} />
    </svg>
  )
}

function MiniBarChart({ values }: { values: number[] }) {
  const max = Math.max(...values, 1)
  return (
    <div className="flex items-end gap-[2px] h-5 shrink-0">
      {values.map((v, i) => (
        <div
          key={i}
          className="w-[3px] rounded-sm bg-muted-foreground/25"
          style={{ height: `${Math.max((v / max) * 100, 8)}%` }}
        />
      ))}
    </div>
  )
}

function deriveBarData(llm: number, tool: number, total: number): number[] {
  const base = Math.max(total, 1)
  return [
    llm * 0.6,
    tool * 0.8,
    base * 0.4,
    llm + tool * 0.3,
    base,
  ].map((v) => Math.max(v, 0.5))
}

function WorkflowStatusDot({ status }: { status: string }) {
  const colors: Record<string, string> = {
    running: "text-[hsl(var(--primary))] fill-[hsl(var(--primary))]",
    completed: "text-[hsl(var(--success))] fill-[hsl(var(--success))]",
    failed: "text-[hsl(var(--destructive))] fill-[hsl(var(--destructive))]",
    paused: "text-[hsl(var(--warning))] fill-[hsl(var(--warning))]",
  }
  return <Circle className={`h-2.5 w-2.5 shrink-0 ${colors[status] || colors.paused}`} />
}

function RunStatusIndicator({ status }: { status: string }) {
  const map: Record<string, React.ReactNode> = {
    SUCCESS: <CheckCircle2 className="h-3.5 w-3.5 text-[hsl(var(--success))]" />,
    FAILED: <AlertTriangle className="h-3.5 w-3.5 text-[hsl(var(--destructive))]" />,
    running: <Play className="h-3 w-3 text-[hsl(var(--primary))] fill-[hsl(var(--primary))]" />,
    PAUSED: <Clock className="h-3.5 w-3.5 text-[hsl(var(--warning))]" />,
  }
  return <div className="flex items-center justify-center">{map[status] || map.PAUSED}</div>
}

function HealthCheckItem({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-2.5">
      <CheckCircle2 className="h-4 w-4 text-[hsl(var(--success))] shrink-0" />
      <span className="text-sm text-muted-foreground">{label}</span>
    </div>
  )
}

function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    SUCCESS: "bg-[hsl(var(--success))]/10 text-[hsl(var(--success))] border-[hsl(var(--success))]/20",
    FAILED: "bg-[hsl(var(--destructive))]/10 text-[hsl(var(--destructive))] border-[hsl(var(--destructive))]/20",
    running: "bg-[hsl(var(--primary))]/10 text-[hsl(var(--primary))] border-[hsl(var(--primary))]/20",
    PAUSED: "bg-[hsl(var(--warning))]/10 text-[hsl(var(--warning))] border-[hsl(var(--warning))]/20",
  }
  return (
    <Badge variant="outline" className={`text-[10px] font-normal rounded-md ${styles[status] || ""}`}>
      {status.toLowerCase()}
    </Badge>
  )
}
