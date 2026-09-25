"use client"

import { useMemo } from "react"
import { useCatalogData } from "@/lib/catalog-context"
import { deriveHealth } from "@/lib/health"
import { EM_DASH, fmtDuration, pct, plural } from "@/lib/format"
import {
  Card,
  CardHeader,
  EmptyState,
  PageTitle,
  StatusBadge,
  ViewAllButton,
  type Tone,
} from "@/components/graphite"
import type { LogsIntent } from "@/components/screens/logs-screen"
import type { Run } from "@/lib/mock-data"

interface HomeScreenProps {
  onNavigate: (section: string) => void
  onOpenLogs: (intent: LogsIntent) => void
}

export function HomeScreen({ onNavigate, onOpenLogs }: HomeScreenProps) {
  const data = useCatalogData()
  const { stats, workflows, runs } = data
  const health = useMemo(() => deriveHealth(data), [data])

  const runningWfs = workflows.filter((w) => w.manifestStatus === "running").length
  const inFlight = runs.filter((r) => r.status === "running").length
  const passedRuns = runs.filter((r) => r.status === "SUCCESS").length

  // A partial rate reads as a verdict, so an in-flight run withholds the number.
  const passRate =
    inFlight > 0 || runs.length === 0
      ? EM_DASH
      : `${Math.round((passedRuns / runs.length) * 100)}%`
  const passRateSub =
    inFlight > 0
      ? `Run in progress · ${passedRuns} passed so far`
      : runs.length === 0
        ? "No runs recorded"
        : `${passedRuns} of ${runs.length} passed`

  const recentRuns = useMemo(
    () => [...runs].sort((a, b) => (a.started < b.started ? 1 : -1)).slice(0, 6),
    [runs],
  )

  const healthItems = useMemo(
    () =>
      [
        ...health.errorGroups.map((g) => ({ ...g, tone: "failed" as Tone })),
        ...health.warningGroups.map((g) => ({ ...g, tone: "warning" as Tone })),
      ]
        .sort((a, b) => b.count - a.count)
        .slice(0, 6),
    [health],
  )

  return (
    <div className="flex max-w-[1180px] animate-view-in flex-col gap-3.5">
      <PageTitle title="Home" />

      <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,200px),1fr))] gap-3">
        <StatTile
          label="Workflows"
          value={stats.total_workflows.toLocaleString()}
          badges={runningWfs > 0 ? [{ tone: "running", label: `${runningWfs} running` }] : []}
          onClick={() => onNavigate("workflows")}
        />
        <StatTile
          label="Actions"
          value={stats.total_actions.toLocaleString()}
          sub={`${stats.llm_actions} LLM · ${stats.tool_actions} tool`}
          onClick={() => onNavigate("actions")}
        />
        <StatTile
          label="Pass rate"
          value={passRate}
          sub={passRateSub}
          onClick={() => onNavigate("runs")}
        />
        <StatTile
          label="Health"
          value={health.total.toLocaleString()}
          sub={health.total === 0 ? "No errors or warnings" : undefined}
          badges={[
            ...(health.errors > 0
              ? [{ tone: "failed" as Tone, label: plural(health.errors, "error") }]
              : []),
            ...(health.warnings > 0
              ? [{ tone: "warning" as Tone, label: plural(health.warnings, "warning") }]
              : []),
          ]}
          onClick={() => onNavigate("logs")}
        />
      </div>

      <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,420px),1fr))] gap-3.5">
        <Card>
          <CardHeader
            title="Recent runs"
            count={runs.length}
            action={<ViewAllButton onClick={() => onNavigate("runs")} />}
          />
          {recentRuns.length === 0 ? (
            <EmptyState message="No runs recorded yet — execute a workflow, then regenerate docs." />
          ) : (
            <>
              <div className="grid grid-cols-[96px_minmax(0,1.3fr)_minmax(0,1fr)_minmax(0,1fr)_64px] gap-2 whitespace-nowrap border-b border-border px-[18px] py-[7px] text-xs font-medium text-muted-2">
                <span>Status</span>
                <span>Run ID</span>
                <span>Workflow</span>
                <span>Progress</span>
                <span className="text-right">Duration</span>
              </div>
              {recentRuns.map((run) => (
                <RunRow key={run.id} run={run} onClick={() => onNavigate("runs")} />
              ))}
            </>
          )}
        </Card>

        <Card>
          <CardHeader title="Health" action={<ViewAllButton onClick={() => onNavigate("logs")} />} />
          {healthItems.length === 0 ? (
            <EmptyState message="No validation or runtime issues in the loaded logs." />
          ) : (
            healthItems.map((item) => (
              <button
                key={`${item.tone}-${item.target}`}
                onClick={() => onOpenLogs({ q: item.target, level: item.tone === "failed" ? "error" : "warn" })}
                className="flex w-full items-start gap-2.5 border-t border-border-soft px-[18px] py-2.5 text-left hover:bg-hover"
              >
                <span title={`${item.count.toLocaleString()} occurrences`}>
                  <StatusBadge tone={item.tone} label={`×${item.count.toLocaleString()}`} />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-sm leading-5 text-foreground [text-wrap:pretty]">
                    {item.sample || "No message captured"}
                  </span>
                  <span
                    title={item.target}
                    className="mt-0.5 block truncate font-mono text-xs text-foreground-3"
                  >
                    {item.target}
                  </span>
                </span>
              </button>
            ))
          )}
        </Card>
      </div>
    </div>
  )
}

function StatTile({
  label,
  value,
  sub,
  badges = [],
  onClick,
}: {
  label: string
  value: string
  sub?: string
  badges?: { tone: Tone; label: string }[]
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      className="flex flex-col gap-1 rounded-card border border-border bg-surface px-5 py-4 text-left text-foreground hover:border-border-2"
    >
      <span className="text-xs font-medium leading-4 text-muted-foreground">{label}</span>
      <span className="text-[28px] font-semibold leading-8 tracking-[-0.02em] text-foreground">{value}</span>
      <span className="flex min-h-5 flex-wrap items-center gap-2">
        {badges.map((b) => (
          <StatusBadge key={b.label} tone={b.tone} label={b.label} />
        ))}
        {sub && <span className="text-xs leading-4 text-muted-foreground">{sub}</span>}
      </span>
    </button>
  )
}

function RunRow({ run, onClick }: { run: Run; onClick: () => void }) {
  const done = run.success + run.failed + run.skipped
  const inFlight = run.status === "running" ? Math.max(0, run.total - done) : 0
  const shortId = run.id.length > 22 ? `…${run.id.slice(-20)}` : run.id

  const tone: Tone =
    run.status === "running" ? "running"
      : run.status === "SUCCESS" ? "passed"
        : run.status === "FAILED" ? "failed"
          : "neutral"
  const label =
    run.status === "running" ? "Running"
      : run.status === "SUCCESS" ? "Passed"
        : run.status === "FAILED" ? "Failed"
          : "Paused"

  return (
    <button
      onClick={onClick}
      className="grid w-full grid-cols-[96px_minmax(0,1.3fr)_minmax(0,1fr)_minmax(0,1fr)_64px] items-center gap-2 border-t border-border-soft px-[18px] py-2.5 text-left hover:bg-hover"
    >
      <span className="justify-self-start">
        <StatusBadge tone={tone} label={label} />
      </span>
      <span title={run.id} className="min-w-0 truncate font-mono text-[13px] text-foreground">
        {shortId}
      </span>
      <span className="min-w-0 truncate text-[13px] text-foreground-3">{run.wf}</span>
      <span className="flex min-w-0 items-center gap-1.5">
        <span
          title={`${run.success} passed · ${run.failed} failed · ${run.skipped} skipped`}
          className="flex h-1.5 flex-1 gap-px overflow-hidden rounded-pill bg-track"
        >
          <span className="h-full bg-success" style={{ width: pct(run.success, run.total) }} />
          <span className="h-full bg-danger" style={{ width: pct(run.failed, run.total) }} />
          <span className="h-full bg-muted-2" style={{ width: pct(run.skipped, run.total) }} />
          <span className="h-full bg-primary" style={{ width: pct(inFlight, run.total) }} />
        </span>
        <span className="shrink-0 text-xs text-foreground-3">
          {done}/{run.total}
        </span>
      </span>
      <span className="shrink-0 text-right font-mono text-[13px] text-foreground">
        {fmtDuration(run.duration)}
      </span>
    </button>
  )
}
