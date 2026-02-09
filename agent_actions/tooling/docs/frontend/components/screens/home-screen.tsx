"use client"

import React from "react"

import { GitBranch, Play, Boxes, AlertTriangle, TrendingUp, Clock, Zap, Activity, ArrowUpRight, CheckCircle2, AlertCircle } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { useCatalogData } from "@/lib/catalog-context"

interface HomeScreenProps {
  onNavigate: (section: string) => void
}

export function HomeScreen({ onNavigate }: HomeScreenProps) {
  const { stats, workflows, runs, validationErrorGroups, validationWarningGroups } = useCatalogData()
  const successRuns = runs.filter((r) => r.status === "SUCCESS").length
  const failedRuns = runs.filter((r) => r.status === "FAILED").length
  const pausedRuns = runs.filter((r) => r.status === "PAUSED").length
  const successRate = stats.total_runs > 0 ? (successRuns / stats.total_runs) * 100 : 0

  return (
    <div className="flex flex-col gap-8">
      {/* Hero banner */}
      <div className="relative overflow-hidden rounded-xl border border-border bg-card p-6">
        <div className="absolute inset-0 bg-gradient-to-br from-[hsl(var(--primary))]/5 via-transparent to-[hsl(var(--chart-2))]/5" />
        <div className="relative flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-foreground">Agent Actions</h1>
            <p className="text-sm text-muted-foreground mt-1 max-w-md leading-relaxed">
              QanaLabs workflow documentation &middot; {stats.total_workflows} workflows, {stats.total_actions} actions, {stats.total_runs} runs.
              {stats.validation_errors > 0 && ` ${stats.validation_errors} validation errors need attention.`}
            </p>
          </div>
          <div className="hidden sm:flex items-center gap-3">
            <div className="flex flex-col items-end gap-0.5">
              <span className="text-3xl font-bold tabular-nums text-foreground">{successRate.toFixed(0)}%</span>
              <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-medium">Success rate</span>
            </div>
            <div className="h-10 w-px bg-border" />
            <SuccessRing percentage={successRate} />
          </div>
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label="Workflows"
          value={stats.total_workflows}
          icon={GitBranch}
          accent="hsl(var(--primary))"
          subtitle={`${workflows.filter(w => w.manifestStatus === "running").length} running`}
          subtitleColor="hsl(var(--primary))"
          onClick={() => onNavigate("workflows")}
          sparkData={[1, 2, 2, 3, 3, 3, 3]}
        />
        <StatCard
          label="Total Actions"
          value={stats.total_actions}
          icon={Boxes}
          accent="hsl(var(--chart-2))"
          subtitle={`${stats.llm_actions} LLM \u00b7 ${stats.tool_actions} tool`}
          onClick={() => onNavigate("actions")}
          sparkData={[10, 15, 20, 25, 30, 33, 36]}
        />
        <StatCard
          label="Total Runs"
          value={stats.total_runs}
          icon={TrendingUp}
          accent="hsl(var(--chart-5))"
          subtitle={`${failedRuns} failed \u00b7 ${pausedRuns} paused`}
          subtitleColor={failedRuns > 0 ? "hsl(var(--destructive))" : undefined}
          onClick={() => onNavigate("runs")}
          sparkData={[2, 4, 6, 8, 12, 15, 18]}
        />
        <StatCard
          label="Validation Issues"
          value={stats.validation_errors + stats.validation_warnings}
          icon={AlertTriangle}
          accent="hsl(var(--destructive))"
          subtitle={`${stats.validation_errors} errors \u00b7 ${stats.validation_warnings} warnings`}
          subtitleColor="hsl(var(--destructive))"
          onClick={() => onNavigate("logs")}
          sparkData={[100, 200, 300, 400, 500, 700, 972]}
        />
      </div>

      {/* Activity & Events */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-5">
        {/* Recent Runs */}
        <div className="lg:col-span-3 rounded-xl border border-border bg-card overflow-hidden">
          <div className="flex items-center justify-between border-b border-border px-5 py-3.5">
            <div className="flex items-center gap-2.5">
              <div className="flex h-6 w-6 items-center justify-center rounded-md bg-[hsl(var(--primary))]/10">
                <Activity className="h-3.5 w-3.5 text-[hsl(var(--primary))]" />
              </div>
              <span className="text-sm font-medium text-foreground">Recent Runs</span>
            </div>
            <button
              onClick={() => onNavigate("runs")}
              className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
            >
              View all
              <ArrowUpRight className="h-3 w-3" />
            </button>
          </div>
          <div className="divide-y divide-border">
            {runs.slice(0, 5).map((run) => (
              <button
                key={run.id}
                className="flex w-full items-center gap-4 px-5 py-3 text-left hover:bg-accent/30 transition-colors"
                onClick={() => onNavigate("runs")}
              >
                <RunStatusIndicator status={run.status} />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-mono font-medium text-foreground truncate">
                      {run.id.replace("run_qanalabs_quiz_gen_", "quiz_gen#")}
                    </span>
                    <StatusBadge status={run.status} />
                  </div>
                  <div className="flex items-center gap-3 mt-0.5">
                    <span className="text-[11px] text-muted-foreground">
                      {run.success}/{run.total} actions
                    </span>
                    <span className="text-[11px] text-muted-foreground">
                      {Object.keys(run.actions).length} tracked
                    </span>
                  </div>
                </div>
                <div className="flex flex-col items-end gap-0.5">
                  <span className="text-xs font-mono text-foreground tabular-nums">{run.duration}s</span>
                  <div className="h-1 w-16 rounded-full bg-secondary overflow-hidden">
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
                </div>
              </button>
            ))}
          </div>
        </div>

        {/* Validation Issues */}
        <div className="lg:col-span-2 rounded-xl border border-border bg-card overflow-hidden">
          <div className="flex items-center justify-between border-b border-border px-5 py-3.5">
            <div className="flex items-center gap-2.5">
              <div className="flex h-6 w-6 items-center justify-center rounded-md bg-[hsl(var(--destructive))]/10">
                <AlertCircle className="h-3.5 w-3.5 text-[hsl(var(--destructive))]" />
              </div>
              <span className="text-sm font-medium text-foreground">Validation Issues</span>
            </div>
            <button
              onClick={() => onNavigate("logs")}
              className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
            >
              View all
              <ArrowUpRight className="h-3 w-3" />
            </button>
          </div>
          <div className="divide-y divide-border">
            {validationErrorGroups.map((g) => (
              <button
                key={`err-${g.target}`}
                className="flex w-full items-start gap-3 px-5 py-2.5 text-left hover:bg-accent/30 transition-colors"
                onClick={() => onNavigate("logs")}
              >
                <span className="mt-0.5 shrink-0 rounded-md px-1.5 py-0.5 text-[10px] font-mono uppercase font-semibold bg-[hsl(var(--destructive))]/10 text-[hsl(var(--destructive))]">
                  {g.count}
                </span>
                <div className="flex-1 min-w-0">
                  <p className="text-xs text-foreground/90 leading-relaxed font-mono">{g.target}</p>
                  <p className="text-[10px] text-muted-foreground mt-0.5 line-clamp-1">{g.sample}</p>
                </div>
              </button>
            ))}
            {validationWarningGroups.map((g) => (
              <button
                key={`warn-${g.target}`}
                className="flex w-full items-start gap-3 px-5 py-2.5 text-left hover:bg-accent/30 transition-colors"
                onClick={() => onNavigate("logs")}
              >
                <span className="mt-0.5 shrink-0 rounded-md px-1.5 py-0.5 text-[10px] font-mono uppercase font-semibold bg-[hsl(var(--warning))]/10 text-[hsl(var(--warning))]">
                  {g.count}
                </span>
                <div className="flex-1 min-w-0">
                  <p className="text-xs text-foreground/90 leading-relaxed font-mono">{g.target}</p>
                  <p className="text-[10px] text-muted-foreground mt-0.5 line-clamp-1">{g.sample}</p>
                </div>
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Quick Actions */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[
          { label: "Workflows", icon: GitBranch, section: "workflows", accent: "hsl(var(--primary))" },
          { label: "All Actions", icon: Boxes, section: "actions", accent: "hsl(var(--chart-2))" },
          { label: "View Logs", icon: Zap, section: "logs", accent: "hsl(var(--warning))" },
          { label: "Run History", icon: Play, section: "runs", accent: "hsl(var(--chart-5))" },
        ].map((action) => (
          <button
            key={action.section}
            onClick={() => onNavigate(action.section)}
            className="group relative flex items-center gap-3 rounded-xl border border-border bg-card px-4 py-3.5 text-sm text-muted-foreground hover:text-foreground hover:border-[hsl(var(--primary))]/30 transition-all"
          >
            <div
              className="flex h-8 w-8 items-center justify-center rounded-lg transition-colors"
              style={{ backgroundColor: `${action.accent}10` }}
            >
              <action.icon className="h-4 w-4" style={{ color: action.accent }} />
            </div>
            {action.label}
            <ArrowUpRight className="ml-auto h-3.5 w-3.5 opacity-0 group-hover:opacity-100 transition-opacity" />
          </button>
        ))}
      </div>
    </div>
  )
}

/* -- Sub-components -- */

function StatCard({
  label,
  value,
  icon: Icon,
  accent,
  subtitle,
  subtitleColor,
  onClick,
  sparkData,
}: {
  label: string
  value: number
  icon: React.ElementType
  accent: string
  subtitle: string
  subtitleColor?: string
  onClick: () => void
  sparkData: number[]
}) {
  const max = Math.max(...sparkData)
  const min = Math.min(...sparkData)
  const range = max - min || 1
  const points = sparkData
    .map((v, i) => `${(i / (sparkData.length - 1)) * 64},${24 - ((v - min) / range) * 20}`)
    .join(" ")

  return (
    <button
      onClick={onClick}
      className="group relative overflow-hidden rounded-xl border border-border bg-card p-5 text-left hover:border-border/80 transition-all"
    >
      <div className="absolute top-0 left-0 right-0 h-px" style={{ backgroundColor: accent, opacity: 0.5 }} />
      <div className="flex items-start justify-between">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg" style={{ backgroundColor: `${accent}15` }}>
          <Icon className="h-4 w-4" style={{ color: accent }} />
        </div>
        <svg width="64" height="24" className="text-muted-foreground/30 group-hover:text-muted-foreground/50 transition-colors">
          <polyline
            fill="none"
            stroke={accent}
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
            points={points}
            opacity="0.6"
          />
        </svg>
      </div>
      <div className="mt-3">
        <div className="text-3xl font-bold tabular-nums text-foreground">{value.toLocaleString()}</div>
        <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-medium mt-1">{label}</p>
      </div>
      <p className="text-xs mt-2" style={{ color: subtitleColor || "hsl(var(--muted-foreground))" }}>
        {subtitle}
      </p>
    </button>
  )
}

function SuccessRing({ percentage }: { percentage: number }) {
  const radius = 18
  const circumference = 2 * Math.PI * radius
  const offset = circumference - (percentage / 100) * circumference
  return (
    <svg width="48" height="48" className="-rotate-90">
      <circle cx="24" cy="24" r={radius} fill="none" stroke="hsl(var(--border))" strokeWidth="3" />
      <circle
        cx="24"
        cy="24"
        r={radius}
        fill="none"
        stroke="hsl(var(--success))"
        strokeWidth="3"
        strokeLinecap="round"
        strokeDasharray={circumference}
        strokeDashoffset={offset}
      />
    </svg>
  )
}

function RunStatusIndicator({ status }: { status: string }) {
  const map: Record<string, { bg: string; ring: string; icon?: React.ReactNode }> = {
    SUCCESS: {
      bg: "bg-[hsl(var(--success))]/15",
      ring: "ring-[hsl(var(--success))]/30",
      icon: <CheckCircle2 className="h-3.5 w-3.5 text-[hsl(var(--success))]" />,
    },
    FAILED: {
      bg: "bg-[hsl(var(--destructive))]/15",
      ring: "ring-[hsl(var(--destructive))]/30",
      icon: <AlertTriangle className="h-3.5 w-3.5 text-[hsl(var(--destructive))]" />,
    },
    running: {
      bg: "bg-[hsl(var(--primary))]/15",
      ring: "ring-[hsl(var(--primary))]/30",
      icon: <Play className="h-3 w-3 text-[hsl(var(--primary))] fill-[hsl(var(--primary))]" />,
    },
    PAUSED: {
      bg: "bg-[hsl(var(--warning))]/15",
      ring: "ring-[hsl(var(--warning))]/30",
      icon: <Clock className="h-3.5 w-3.5 text-[hsl(var(--warning))]" />,
    },
  }
  const s = map[status] || map.PAUSED
  return (
    <div className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ring-1 ${s.bg} ${s.ring}`}>
      {s.icon}
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
