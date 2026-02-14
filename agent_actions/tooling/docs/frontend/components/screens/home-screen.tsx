"use client"

import React from "react"

import { Play, AlertTriangle, Clock, ArrowUpRight, CheckCircle2, Circle, GitBranch, Boxes, TrendingUp, Activity, ShieldCheck } from "lucide-react"
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
  const successRate = stats.total_runs > 0 ? Math.round((successRuns / stats.total_runs) * 100) : 0
  const totalIssues = stats.validation_errors + stats.validation_warnings

  return (
    <div className="flex flex-col gap-4">
      {/* ── Dashboard Stats ───────────────────────────────────────────── */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard
          icon={<GitBranch className="h-4 w-4" />}
          label="Workflows"
          value={stats.total_workflows}
          accent="primary"
          sub={runningWfs > 0 ? `${runningWfs} active` : "All idle"}
          subColor={runningWfs > 0 ? "text-[hsl(var(--primary))]" : undefined}
          sparkData={[3, 5, 4, 7, 6, 8, stats.total_workflows]}
          onClick={() => onNavigate("workflows")}
        />
        <StatCard
          icon={<Boxes className="h-4 w-4" />}
          label="Actions"
          value={stats.total_actions}
          accent="primary"
          sub={`${stats.llm_actions} LLM \u00b7 ${stats.tool_actions} tool`}
          sparkData={[2, 4, 3, 5, 6, 5, stats.total_actions]}
          onClick={() => onNavigate("actions")}
        />
        <StatCard
          icon={<Activity className="h-4 w-4" />}
          label="Runs"
          value={stats.total_runs}
          accent={failedRuns > 0 ? "destructive" : "success"}
          sub={`${successRate}% pass rate`}
          subColor={failedRuns > 0 ? "text-[hsl(var(--destructive))]" : "text-[hsl(var(--success))]"}
          sparkData={[1, 3, 2, 5, 4, 6, stats.total_runs]}
          onClick={() => onNavigate("runs")}
        />
        <StatCard
          icon={<ShieldCheck className="h-4 w-4" />}
          label="Health"
          value={totalIssues}
          accent={totalIssues > 0 ? "destructive" : "success"}
          sub={totalIssues === 0 ? "All clear" : `${stats.validation_errors} err \u00b7 ${stats.validation_warnings} warn`}
          subColor={stats.validation_errors > 0 ? "text-[hsl(var(--destructive))]" : totalIssues === 0 ? "text-[hsl(var(--success))]" : undefined}
          sparkData={[5, 4, 6, 3, 4, 2, totalIssues]}
          onClick={() => onNavigate("logs")}
        />
      </div>

      {/* ── Workflow Overview + Health Panel ──────────────────────────── */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-5">
        {/* Workflow Overview (60%) */}
        <div className="lg:col-span-3 rounded-lg border border-border bg-card overflow-hidden">
          <div className="flex items-center justify-between border-b border-border px-4 py-2">
            <span className="text-xs font-semibold text-foreground">
              Workflows
              <span className="ml-1.5 text-muted-foreground font-normal">({workflows.length})</span>
            </span>
            <button
              onClick={() => onNavigate("workflows")}
              className="flex items-center gap-0.5 text-[10px] text-muted-foreground hover:text-foreground transition-colors"
            >
              View all
              <ArrowUpRight className="h-2.5 w-2.5" />
            </button>
          </div>
          <div className="divide-y divide-border">
            {workflows.map((wf) => (
              <button
                key={wf.id}
                className="flex w-full items-center gap-3 px-4 py-2 text-left hover:bg-accent/50 transition-colors"
                onClick={() => onNavigate("workflows")}
              >
                <WorkflowStatusDot status={wf.manifestStatus} />
                <span className="text-xs font-mono font-medium text-foreground truncate min-w-0 flex-1">
                  {wf.name}
                </span>
                <Badge variant="outline" className="text-[10px] font-mono font-normal rounded px-1.5 py-0 h-4 shrink-0">
                  v{wf.version}
                </Badge>
                <span className="text-[10px] text-muted-foreground tabular-nums shrink-0 w-14 text-right">
                  {wf.actionCount} actions
                </span>
                <span className="text-[10px] text-muted-foreground tabular-nums shrink-0 w-20 text-right">
                  {wf.llmCount}L / {wf.toolCount}T
                </span>
                <span className="text-[10px] font-mono text-muted-foreground truncate shrink-0 max-w-[120px] text-right">
                  {wf.defaults.model_name || "\u2014"}
                </span>
              </button>
            ))}
            {workflows.length === 0 && (
              <div className="px-4 py-6 text-center text-xs text-muted-foreground">No workflows found</div>
            )}
          </div>
        </div>

        {/* Health Panel (40%) */}
        <div className="lg:col-span-2 rounded-lg border border-border bg-card overflow-hidden">
          <div className="flex items-center justify-between border-b border-border px-4 py-2">
            <span className="text-xs font-semibold text-foreground">
              Health
              <span className="ml-1.5 font-normal">
                {stats.validation_errors > 0 && (
                  <span className="text-[hsl(var(--destructive))]">{stats.validation_errors} err</span>
                )}
                {stats.validation_errors > 0 && stats.validation_warnings > 0 && (
                  <span className="text-muted-foreground"> / </span>
                )}
                {stats.validation_warnings > 0 && (
                  <span className="text-[hsl(var(--warning))]">{stats.validation_warnings} warn</span>
                )}
                {stats.validation_errors === 0 && stats.validation_warnings === 0 && (
                  <span className="text-[hsl(var(--success))]">clean</span>
                )}
              </span>
            </span>
            <button
              onClick={() => onNavigate("logs")}
              className="flex items-center gap-0.5 text-[10px] text-muted-foreground hover:text-foreground transition-colors"
            >
              View all
              <ArrowUpRight className="h-2.5 w-2.5" />
            </button>
          </div>
          <div className="divide-y divide-border max-h-[280px] overflow-y-auto">
            {validationErrorGroups.map((g) => (
              <button
                key={`err-${g.target}`}
                className="flex w-full items-start gap-2.5 px-4 py-2 text-left hover:bg-accent/50 transition-colors"
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
                className="flex w-full items-start gap-2.5 px-4 py-2 text-left hover:bg-accent/50 transition-colors"
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
            {validationErrorGroups.length === 0 && validationWarningGroups.length === 0 && (
              <div className="px-4 py-6 text-center text-xs text-muted-foreground">No validation issues</div>
            )}
          </div>
        </div>
      </div>

      {/* ── Recent Runs (full width) ─────────────────────────────────── */}
      <div className="rounded-lg border border-border bg-card overflow-hidden">
        <div className="flex items-center justify-between border-b border-border px-4 py-2">
          <span className="text-xs font-semibold text-foreground">
            Recent Runs
            <span className="ml-1.5 text-muted-foreground font-normal">({runs.length})</span>
          </span>
          <button
            onClick={() => onNavigate("runs")}
            className="flex items-center gap-0.5 text-[10px] text-muted-foreground hover:text-foreground transition-colors"
          >
            View all
            <ArrowUpRight className="h-2.5 w-2.5" />
          </button>
        </div>
        {/* Column headers */}
        <div className="grid grid-cols-[20px_1fr_1fr_140px_64px_72px] gap-3 px-4 py-1.5 border-b border-border text-[10px] uppercase tracking-wider text-muted-foreground font-medium">
          <span />
          <span>Run ID</span>
          <span>Workflow</span>
          <span>Progress</span>
          <span className="text-right">Duration</span>
          <span className="text-right">Tokens</span>
        </div>
        <div className="divide-y divide-border">
          {runs.slice(0, 8).map((run) => {
            const pct = run.total > 0 ? (run.success / run.total) * 100 : 0
            return (
              <button
                key={run.id}
                className="grid grid-cols-[20px_1fr_1fr_140px_64px_72px] gap-3 w-full items-center px-4 py-1.5 text-left hover:bg-accent/50 transition-colors"
                onClick={() => onNavigate("runs")}
              >
                <RunStatusIndicator status={run.status} />
                <span className="text-xs font-mono text-foreground truncate">
                  {run.id.length > 30 ? run.id.slice(-20) : run.id}
                </span>
                <span className="text-xs text-muted-foreground truncate">
                  {run.wf}
                </span>
                <div className="flex items-center gap-2">
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
                  <span className="text-[10px] font-mono text-muted-foreground tabular-nums shrink-0 w-8 text-right">
                    {run.success}/{run.total}
                  </span>
                </div>
                <span className="text-xs font-mono text-foreground tabular-nums text-right">{run.duration}s</span>
                <span className="text-xs font-mono text-muted-foreground tabular-nums text-right">
                  {run.tokens > 0 ? run.tokens.toLocaleString() : "\u2014"}
                </span>
              </button>
            )
          })}
          {runs.length === 0 && (
            <div className="px-4 py-6 text-center text-xs text-muted-foreground">No runs recorded</div>
          )}
        </div>
      </div>
    </div>
  )
}

/* -- Sub-components -- */

function StatCard({
  icon,
  label,
  value,
  accent,
  sub,
  subColor,
  sparkData,
  onClick,
}: {
  icon: React.ReactNode
  label: string
  value: number
  accent: "primary" | "success" | "destructive" | "warning"
  sub: string
  subColor?: string
  sparkData: number[]
  onClick?: () => void
}) {
  const accentVar = `var(--${accent})`
  const iconBgMap: Record<string, string> = {
    primary: "bg-[hsl(var(--primary))]/10",
    success: "bg-[hsl(var(--success))]/10",
    destructive: "bg-[hsl(var(--destructive))]/10",
    warning: "bg-[hsl(var(--warning))]/10",
  }
  const iconFgMap: Record<string, string> = {
    primary: "text-[hsl(var(--primary))]",
    success: "text-[hsl(var(--success))]",
    destructive: "text-[hsl(var(--destructive))]",
    warning: "text-[hsl(var(--warning))]",
  }
  return (
    <button
      onClick={onClick}
      className="group relative rounded-lg border border-border bg-card p-4 text-left hover:bg-accent/40 transition-colors overflow-hidden"
    >
      {/* Sparkline background */}
      <div className="absolute bottom-0 right-0 w-24 h-10 opacity-[0.08] group-hover:opacity-[0.14] transition-opacity">
        <MiniSparkline data={sparkData} color={`hsl(${accentVar})`} />
      </div>
      <div className="flex items-center gap-2 mb-2">
        <div className={`flex items-center justify-center h-7 w-7 rounded-md ${iconBgMap[accent]}`}>
          <span className={iconFgMap[accent]}>{icon}</span>
        </div>
        <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-medium">{label}</span>
      </div>
      <div className="flex items-baseline gap-2">
        <span className="text-2xl font-semibold font-mono tabular-nums text-foreground">
          {value.toLocaleString()}
        </span>
      </div>
      <p className={`text-[11px] mt-1 ${subColor || "text-muted-foreground"}`}>{sub}</p>
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

function WorkflowStatusDot({ status }: { status: string }) {
  const colors: Record<string, string> = {
    running: "text-[hsl(var(--primary))] fill-[hsl(var(--primary))]",
    completed: "text-[hsl(var(--success))] fill-[hsl(var(--success))]",
    failed: "text-[hsl(var(--destructive))] fill-[hsl(var(--destructive))]",
    paused: "text-[hsl(var(--warning))] fill-[hsl(var(--warning))]",
  }
  return <Circle className={`h-2 w-2 shrink-0 ${colors[status] || colors.paused}`} />
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
