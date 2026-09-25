"use client"

import { useMemo, useState } from "react"
import { useCatalogData } from "@/lib/catalog-context"
import { EM_DASH, fmtClock, fmtSeconds } from "@/lib/format"
import {
  Card,
  EmptyState,
  Kbd,
  PageTitle,
  SearchInput,
  Segmented,
  TypeTag,
} from "@/components/graphite"
import type { LogsIntent } from "@/components/screens/logs-screen"
import type { Action, LogEvent, Run } from "@/lib/mock-data"

type SortKey = "issues" | "dur" | "wf" | "name"

const PLACEMENTS_SHOWN = 8

interface Member {
  key: string
  name: string
  wf: string
  sec: number | null
  running: boolean
}

interface ActionEntry {
  name: string
  type: "llm" | "tool" | null
  wfs: string[]
  schema: string | null
  deps: number | null
  guard: boolean
  intent: string
  impl?: string
  promptName: string | null
  members: Member[]
  events: LogEvent[]
  errors: number
  warnings: number
  running: boolean
  sec: number | null
  source: string
  sample: Action
}

/** Fan-out placements (extract_1..3) collapse onto their base definition. */
const baseName = (name: string) => name.replace(/_\d+$/, "")

function buildCatalog(
  actions: Record<string, Action>,
  events: LogEvent[],
  runs: Run[],
): ActionEntry[] {
  const running = new Set<string>()
  for (const run of runs) {
    if (run.status !== "running") continue
    for (const [name, a] of Object.entries(run.actions)) {
      if (a.status === "running") running.add(name)
    }
  }

  const byBase = new Map<string, ActionEntry>()
  for (const [key, a] of Object.entries(actions)) {
    const name = key.split("/").pop() ?? key
    const base = baseName(name)
    let entry = byBase.get(base)
    if (!entry) {
      entry = {
        name: base,
        type: a.type,
        wfs: [],
        schema: a.schema,
        deps: a.deps.length,
        guard: Boolean(a.guard),
        intent: a.intent,
        impl: a.impl,
        promptName: a.promptName,
        members: [],
        events: [],
        errors: 0,
        warnings: 0,
        running: false,
        sec: null,
        source: "",
        sample: a,
      }
      byBase.set(base, entry)
    }
    if (!entry.schema) entry.schema = a.schema
    if (!entry.intent) entry.intent = a.intent
    if (!entry.impl) entry.impl = a.impl
    if (!entry.promptName) entry.promptName = a.promptName
    entry.guard = entry.guard || Boolean(a.guard)
    if (!entry.wfs.includes(a.wf)) entry.wfs.push(a.wf)
    entry.members.push({
      key,
      name,
      wf: a.wf,
      sec: a.metrics.execution_time,
      running: running.has(name),
    })
  }

  for (const e of events) {
    if (!e.actionName) continue
    const entry = byBase.get(baseName(e.actionName))
    if (entry) entry.events.push(e)
  }

  for (const entry of byBase.values()) {
    entry.events.sort((a, b) => b.timestamp.localeCompare(a.timestamp))
    entry.errors = entry.events.filter((e) => e.level === "error").length
    entry.warnings = entry.events.filter((e) => e.level === "warn").length
    entry.running = entry.members.some((m) => m.running)
    const timed = entry.members.map((m) => m.sec).filter((s): s is number => s != null && s > 0)
    entry.sec = timed.length ? Math.max(...timed) : null
    entry.source =
      entry.members.length > 1 ? `wall, ×${entry.members.length} placements` : "last recorded run"
  }

  return [...byBase.values()]
}

export function ActionsScreen({ onOpenLogs }: { onOpenLogs: (intent: LogsIntent) => void }) {
  const { actions, logEvents, runs, workflows } = useCatalogData()
  const [search, setSearch] = useState("")
  const [type, setType] = useState("all")
  const [workflow, setWorkflow] = useState("all")
  const [sort, setSort] = useState<SortKey>("issues")
  const [issuesOnly, setIssuesOnly] = useState(false)
  const [selectedName, setSelectedName] = useState<string | null>(null)

  const catalog = useMemo(() => buildCatalog(actions, logEvents, runs), [actions, logEvents, runs])

  const scoped = useMemo(() => {
    const q = search.trim().toLowerCase()
    return catalog.filter((c) => {
      if (workflow !== "all" && !c.wfs.includes(workflow)) return false
      if (issuesOnly && c.errors + c.warnings === 0) return false
      if (!q) return true
      return [c.name, c.intent, c.schema, c.impl, c.wfs.join(" ")].join(" ").toLowerCase().includes(q)
    })
  }, [catalog, search, workflow, issuesOnly])

  const rows = useMemo(() => {
    const list = scoped.filter((c) => type === "all" || c.type === type)
    const sorters: Record<SortKey, (a: ActionEntry, b: ActionEntry) => number> = {
      issues: (a, b) =>
        b.errors - a.errors ||
        b.warnings - a.warnings ||
        Number(b.running) - Number(a.running) ||
        a.name.localeCompare(b.name),
      dur: (a, b) => (b.sec ?? -1) - (a.sec ?? -1),
      wf: (a, b) => b.wfs.length - a.wfs.length || a.name.localeCompare(b.name),
      name: (a, b) => a.name.localeCompare(b.name),
    }
    return [...list].sort(sorters[sort])
  }, [scoped, type, sort])

  const selected = rows.find((c) => c.name === selectedName) ?? rows[0] ?? null
  const maxSec = Math.max(1, ...catalog.map((c) => c.sec ?? 0))
  const placements = Object.keys(actions).length

  const runningNow = catalog.find((c) => c.running) ?? null
  const slowest = [...catalog].filter((c) => !c.running && c.sec != null).sort((a, b) => b.sec! - a.sec!)[0] ?? null
  const withIssues = catalog.filter((c) => c.errors + c.warnings > 0)

  const typeTabs = [
    { value: "all", label: "All", count: scoped.length },
    { value: "llm", label: "LLM", count: scoped.filter((c) => c.type === "llm").length },
    { value: "tool", label: "Tool", count: scoped.filter((c) => c.type === "tool").length },
  ]

  const filtersActive = search !== "" || type !== "all" || workflow !== "all" || issuesOnly

  return (
    <div className="flex max-w-[1280px] animate-view-in flex-col gap-4">
      <PageTitle
        title="All Actions"
        subtitle={`${catalog.length} distinct actions in loaded configs · ${placements} placements across ${workflows.length} workflows`}
      />

      <div className="grid grid-cols-[repeat(auto-fit,minmax(210px,1fr))] gap-2.5">
        <SummaryCard
          label="Running now"
          onClick={() => runningNow && setSelectedName(runningNow.name)}
          value={runningNow ? runningNow.name : "nothing running"}
          valueClass={runningNow ? "text-accent-t" : "text-muted-foreground"}
          dot={runningNow ? "bg-info" : undefined}
          sub={runningNow ? `${runningNow.members.length} placement(s)` : "no in-flight run"}
        />
        <SummaryCard
          label="Slowest recorded"
          onClick={() => slowest && setSelectedName(slowest.name)}
          value={slowest ? slowest.name : EM_DASH}
          sub={slowest ? fmtSeconds(slowest.sec) : "no timings recorded"}
        />
        <SummaryCard
          label="With errors or warnings"
          onClick={() => setIssuesOnly(true)}
          value={withIssues.length ? String(withIssues.length) : "0"}
          valueClass={withIssues.length ? "text-warning-t" : "text-foreground"}
          sub={`${withIssues.reduce((n, c) => n + c.errors, 0)} err · ${withIssues.reduce((n, c) => n + c.warnings, 0)} warn`}
        />
      </div>

      <div className="flex flex-wrap items-center gap-2.5">
        <SearchInput
          value={search}
          onChange={setSearch}
          placeholder="Search name, intent, schema, tool or workflow…"
          className="min-w-[200px] flex-1"
        />
        <Segmented options={typeTabs} value={type} onChange={setType} />
        <select
          value={workflow}
          onChange={(e) => setWorkflow(e.target.value)}
          aria-label="Workflow"
          className="max-w-[180px] cursor-pointer rounded-control border border-border bg-surface px-2.5 py-[7px] font-mono text-[11.5px] text-foreground-2 outline-none"
        >
          <option value="all">all workflows</option>
          {workflows.map((w) => (
            <option key={w.id} value={w.id}>{w.name}</option>
          ))}
        </select>
        <select
          value={sort}
          onChange={(e) => setSort(e.target.value as SortKey)}
          title="Sort"
          className="cursor-pointer rounded-control border border-border bg-surface px-2.5 py-[7px] text-[11.5px] text-foreground-2 outline-none"
        >
          <option value="issues">Sort: issues first</option>
          <option value="dur">Sort: slowest</option>
          <option value="wf">Sort: most reused</option>
          <option value="name">Sort: name</option>
        </select>
        <button
          onClick={() => setIssuesOnly((v) => !v)}
          aria-pressed={issuesOnly}
          className={`shrink-0 rounded-control border border-border px-2.5 py-[7px] text-[11.5px] ${
            issuesOnly ? "bg-accent-a12 text-accent-t" : "bg-surface text-muted-foreground"
          }`}
        >
          Issues only
        </button>
      </div>

      <div className="flex flex-wrap items-start gap-3.5">
        <Card className="min-w-0 flex-[1_1_520px]">
          <div className="grid grid-cols-[44px_minmax(0,1fr)_40px_116px_40px] gap-2.5 bg-surface-2 px-3.5 py-2 text-xs font-medium text-muted-foreground">
            <span>Type</span>
            <span>Action</span>
            <span className="text-right">WFs</span>
            <span>Last run</span>
            <span className="text-right">Issues</span>
          </div>
          {rows.map((c) => (
            <button
              key={c.name}
              onClick={() => setSelectedName(c.name)}
              className={`grid w-full grid-cols-[44px_minmax(0,1fr)_40px_116px_40px] items-center gap-2.5 border-t border-border-soft px-3.5 py-2 text-left hover:bg-hover ${
                selected?.name === c.name ? "bg-accent-a12" : ""
              }`}
            >
              <TypeTag type={c.type ?? ""} />
              <span className="min-w-0">
                <span className="flex min-w-0 items-center gap-1.5">
                  <span className="truncate font-mono text-xs text-foreground">{c.name}</span>
                  {c.members.length > 1 && (
                    <span
                      title="Placements across workflows and fan-outs"
                      className="shrink-0 rounded-sm border border-border-2 px-1 font-mono text-[9.5px] text-foreground-3"
                    >
                      ×{c.members.length}
                    </span>
                  )}
                  {c.guard && (
                    <span
                      title="Has a guard condition"
                      className="shrink-0 rounded-sm border border-border-2 px-1 font-mono text-[9.5px] text-foreground-3"
                    >
                      guard
                    </span>
                  )}
                </span>
                <span className="mt-0.5 block truncate text-[11px] text-muted-foreground">
                  {c.intent || (c.impl ? `${c.impl}()` : "No intent in loaded config")}
                </span>
              </span>
              <span className="text-right font-mono text-[11px] text-foreground-3">{c.wfs.length}</span>
              <span className="flex flex-col gap-1">
                <span className={`font-mono text-[10.5px] ${c.running ? "text-info-t" : c.sec != null ? "text-foreground-3" : "text-muted-2"}`}>
                  {c.running ? `${fmtSeconds(c.sec)}…` : fmtSeconds(c.sec)}
                </span>
                <span className="h-[3px] overflow-hidden rounded-sm bg-surface-2">
                  <span
                    className={`block h-full rounded-sm ${c.running ? "bg-info" : c.type === "tool" ? "bg-tool" : "bg-llm"}`}
                    style={{
                      width: c.sec
                        ? `${Math.max(3, (Math.log1p(c.sec) / Math.log1p(maxSec)) * 100).toFixed(1)}%`
                        : "0%",
                    }}
                  />
                </span>
              </span>
              <span className="flex justify-end">
                {c.errors + c.warnings > 0 ? (
                  <span
                    className={`rounded-sm px-1.5 py-px font-mono text-[10px] font-bold ${
                      c.errors ? "bg-danger-a12 text-danger-t" : "bg-warning-a12 text-warning-t"
                    }`}
                  >
                    {c.errors + c.warnings}
                  </span>
                ) : (
                  <span className="font-mono text-[11px] text-muted-2">{EM_DASH}</span>
                )}
              </span>
            </button>
          ))}
          {rows.length === 0 && (
            <EmptyState
              message="No actions match these filters"
              actionLabel={filtersActive ? "Clear filters" : undefined}
              onAction={
                filtersActive
                  ? () => { setSearch(""); setType("all"); setWorkflow("all"); setIssuesOnly(false) }
                  : undefined
              }
            />
          )}
          <div className="flex items-center gap-3 border-t border-border-soft px-3.5 py-2 text-[10.5px] text-muted-foreground">
            <span className="flex items-center gap-1"><Kbd>j</Kbd><Kbd>k</Kbd>move</span>
            <span className="flex-1" />
            <span className="font-mono">{rows.length.toLocaleString()} shown</span>
          </div>
        </Card>

        {selected && (
          <ActionDetailPanel
            entry={selected}
            workflowCount={workflows.length}
            onOpenLogs={onOpenLogs}
          />
        )}
      </div>
    </div>
  )
}

function SummaryCard({
  label,
  value,
  valueClass = "text-foreground",
  dot,
  sub,
  onClick,
}: {
  label: string
  value: string
  valueClass?: string
  dot?: string
  sub: string
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      className="rounded-card border border-border bg-surface px-4 py-3 text-left hover:border-border-2"
    >
      <div className="text-xs font-medium text-muted-foreground">{label}</div>
      <div className="mt-2 flex items-center gap-2">
        {dot && <span className={`h-[7px] w-[7px] shrink-0 animate-breathe rounded-pill ${dot}`} />}
        <span className={`truncate font-mono text-[13px] ${valueClass}`}>{value}</span>
      </div>
      <div className="mt-1 font-mono text-[11px] text-muted-foreground">{sub}</div>
    </button>
  )
}

function ActionDetailPanel({
  entry,
  workflowCount,
  onOpenLogs,
}: {
  entry: ActionEntry
  workflowCount: number
  onOpenLogs: (intent: LogsIntent) => void
}) {
  const a = entry.sample
  const status = entry.running
    ? { label: "running", text: "text-info-t", dot: "bg-info" }
    : entry.errors > 0
      ? { label: "errors in window", text: "text-danger-t", dot: "bg-danger" }
      : entry.sec != null
        ? { label: "succeeded last", text: "text-success-t", dot: "bg-success" }
        : { label: "not in loaded runs", text: "text-muted-foreground", dot: "bg-muted-2" }

  const memberMax = Math.max(1, ...entry.members.map((m) => m.sec ?? 0))
  // A widely reused action has dozens of placements; the slow ones are the story.
  const shownMembers = [...entry.members]
    .sort((a, b) => Number(b.running) - Number(a.running) || (b.sec ?? -1) - (a.sec ?? -1))
    .slice(0, PLACEMENTS_SHOWN)

  const known = (v: string | undefined, skip: string[] = []) =>
    v && v !== "unknown" && !skip.includes(v) ? v : null
  const model = known(a.model)
  const provider = known(a.provider, [entry.type ?? ""])

  const config: [string, string][] = [
    ["kind", entry.type ?? EM_DASH],
    ...(model ? ([["model", model]] as [string, string][]) : []),
    ...(provider ? ([["provider", provider]] as [string, string][]) : []),
    ...(entry.impl ? ([["function", `${entry.impl}()`]] as [string, string][]) : []),
    ...(a.guard ? ([["guard on_false", a.guard.on_false]] as [string, string][]) : []),
    ...(a.inputs.length ? ([["inputs", a.inputs.join(", ")]] as [string, string][]) : []),
    ...(a.outputs.length ? ([["outputs", a.outputs.join(", ")]] as [string, string][]) : []),
    ...(a.drops.length ? ([["drops", a.drops.join(", ")]] as [string, string][]) : []),
    ...(a.observe.length ? ([["observe", a.observe.join(", ")]] as [string, string][]) : []),
  ]

  return (
    <div className="sticky top-0 flex min-w-0 max-w-[480px] flex-[1_1_360px] animate-panel-in flex-col rounded-card border border-border bg-surface">
      <div className="flex flex-col gap-2 border-b border-border-soft px-[18px] pb-3.5 pt-4">
        <div className="flex flex-wrap items-center gap-2">
          <TypeTag type={entry.type ?? ""} />
          <span className={`flex items-center gap-1.5 text-[11px] ${status.text}`}>
            <span className={`h-1.5 w-1.5 rounded-pill ${status.dot}`} />
            {status.label}
          </span>
        </div>
        <div className="overflow-x-auto whitespace-nowrap font-mono text-base font-semibold">{entry.name}</div>
        <p className="m-0 text-[12.5px] leading-[1.5] text-foreground-3 [text-wrap:pretty]">
          {entry.intent || "No intent declared in the loaded workflow configs."}
        </p>
      </div>

      <div className="grid grid-cols-3 border-b border-border-soft">
        <PanelStat
          label="Last run"
          value={entry.running ? `${fmtSeconds(entry.sec)}…` : fmtSeconds(entry.sec)}
          sub={entry.sec != null ? entry.source : "no run data"}
        />
        <PanelStat label="Workflows" value={String(entry.wfs.length)} sub={`of ${workflowCount}`} />
        <PanelStat
          label="Issues"
          value={String(entry.errors + entry.warnings)}
          valueClass={entry.errors ? "text-danger-t" : entry.warnings ? "text-warning-t" : "text-foreground"}
          sub={entry.errors + entry.warnings ? `${entry.errors} err · ${entry.warnings} warn` : "in loaded window"}
          last
        />
      </div>

      <div className="flex flex-col gap-4 px-[18px] py-3.5">
        <div className="flex flex-wrap gap-[18px]">
          <div className="flex min-w-0 flex-col gap-1.5">
            <div className="text-xs font-medium text-muted-foreground">
              {entry.type === "llm" ? "Prompt" : "Implementation"}
            </div>
            <span className="whitespace-nowrap font-mono text-[11px] text-accent-t">
              {entry.type === "llm"
                ? (entry.promptName ?? "inline")
                : entry.impl
                  ? `${entry.impl}()`
                  : "not resolved"}
            </span>
          </div>
          <div className="flex min-w-0 flex-col gap-1.5">
            <div className="text-xs font-medium text-muted-foreground">Output schema</div>
            <span className={`font-mono text-[11px] ${entry.schema ? "text-accent-t" : "text-muted-foreground"}`}>
              {entry.schema ?? "none"}
            </span>
          </div>
          <div className="flex flex-col gap-1.5">
            <div className="text-xs font-medium text-muted-foreground">Deps</div>
            <span className="font-mono text-[11px] text-foreground-3">
              {entry.deps === 0 ? "root" : String(entry.deps ?? EM_DASH)}
            </span>
          </div>
        </div>

        {entry.members.length > 1 && (
          <div className="flex flex-col gap-2">
            <div className="flex items-baseline gap-2">
              <span className="text-xs font-medium text-muted-foreground">Placements</span>
              <span className="font-mono text-[10px] text-muted-foreground">
                {entry.members.length} total, slowest first
              </span>
            </div>
            {shownMembers.map((m) => (
              <div key={m.key} className="grid grid-cols-[minmax(0,1fr)_88px_62px] items-center gap-2.5">
                <span
                  title={m.key}
                  className={`truncate font-mono text-[11px] ${m.running ? "text-info-t" : "text-foreground-2"}`}
                >
                  {m.wf}/{m.name}
                </span>
                <span className="h-[5px] overflow-hidden rounded-sm bg-surface-2">
                  <span
                    className={`block h-full rounded-sm ${m.running ? "bg-info" : entry.type === "tool" ? "bg-tool" : "bg-llm"}`}
                    style={{ width: `${Math.max(2, ((m.sec ?? 0) / memberMax) * 100).toFixed(1)}%` }}
                  />
                </span>
                <span className={`text-right font-mono text-[10.5px] ${m.running ? "text-info-t" : "text-muted-foreground"}`}>
                  {m.running ? `${fmtSeconds(m.sec)}…` : fmtSeconds(m.sec)}
                </span>
              </div>
            ))}
            {entry.members.length > shownMembers.length && (
              <span className="font-mono text-[10.5px] text-muted-foreground">
                +{entry.members.length - shownMembers.length} more
              </span>
            )}
          </div>
        )}

        <div className="flex flex-col gap-2">
          <div className="text-xs font-medium text-muted-foreground">Used in</div>
          <div className="flex flex-wrap gap-1.5">
            {entry.wfs.map((w) => (
              <span
                key={w}
                className="flex items-center gap-1.5 whitespace-nowrap rounded-control border border-border bg-surface px-2 py-1 font-mono text-[10.5px] text-foreground-2"
              >
                {w}
              </span>
            ))}
          </div>
        </div>

        <div className="flex flex-col gap-2">
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium text-muted-foreground">Recent events</span>
            <span className="flex-1" />
            {entry.events.length > 0 && (
              <button
                onClick={() => onOpenLogs({ q: entry.name })}
                className="border-0 bg-transparent p-0 text-[11px] text-accent-t hover:underline"
              >
                All in Logs →
              </button>
            )}
          </div>
          {entry.events.slice(0, 4).map((e) => (
            <button
              key={e.id}
              onClick={() => onOpenLogs({ q: entry.name })}
              title="Open in Logs"
              className="flex w-full flex-col gap-1 rounded-control border border-border-soft bg-well px-2.5 py-2 text-left hover:border-border-2"
            >
              <span className="flex items-center gap-2 font-mono text-[10.5px] text-muted-foreground">
                <span className="text-foreground-3">{e.level.toUpperCase()}</span>
                <span>{e.code}</span>
                <span className="flex-1" />
                <span>{fmtClock(e.timestamp)}</span>
              </span>
              <span className="line-clamp-2 text-[11.5px] leading-[1.45] text-foreground-2">{e.message}</span>
            </button>
          ))}
          {entry.events.length === 0 && (
            <span className="text-[11.5px] text-muted-foreground">No events for this action in the loaded window.</span>
          )}
        </div>

        {a.guard && (
          <div className="flex flex-col gap-2">
            <div className="text-xs font-medium text-muted-foreground">Guard</div>
            <div className="rounded-control border border-border-soft bg-well px-2.5 py-2 font-mono text-[11px] leading-[1.5] text-warning-t">
              {a.guard.condition}
            </div>
          </div>
        )}

        <div className="flex flex-col overflow-hidden rounded-control border border-border-soft">
          {config.map(([k, v]) => (
            <div key={k} className="flex justify-between gap-3 border-t border-border-soft px-2.5 py-1.5 text-[11px] first:border-t-0">
              <span className="shrink-0 text-muted-foreground">{k}</span>
              <span className="truncate font-mono text-foreground-3">{v}</span>
            </div>
          ))}
        </div>

        {a.toolFunction?.signature && (
          <div className="flex flex-col gap-2">
            <div className="text-xs font-medium text-muted-foreground">Signature</div>
            <div className="overflow-x-auto rounded-control border border-border-soft bg-well px-2.5 py-2 font-mono text-[11px] text-accent-bright">
              {a.toolFunction.signature}
            </div>
            {a.toolFunction.docstring && (
              <p className="m-0 text-[11.5px] leading-[1.5] text-muted-foreground">{a.toolFunction.docstring}</p>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

function PanelStat({
  label,
  value,
  valueClass = "text-foreground",
  sub,
  last = false,
}: {
  label: string
  value: string
  valueClass?: string
  sub: string
  last?: boolean
}) {
  return (
    <div className={`px-[18px] py-2.5 ${last ? "" : "border-r border-border-soft"}`}>
      <div className="text-xs font-medium text-muted-foreground">{label}</div>
      <div className={`mt-1 font-mono text-[15px] ${valueClass}`}>{value}</div>
      <div className="mt-0.5 truncate font-mono text-[10px] text-muted-foreground">{sub}</div>
    </div>
  )
}
