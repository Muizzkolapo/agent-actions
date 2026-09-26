"use client"

import { useMemo, useState } from "react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import rehypeRaw from "rehype-raw"
import rehypeSanitize, { defaultSchema } from "rehype-sanitize"
import { useCatalogData } from "@/lib/catalog-context"
import { WorkflowDAGView } from "@/components/workflow-dag"
import { EM_DASH, fmtClock } from "@/lib/format"
import {
  BackButton,
  Card,
  EmptyState,
  IssuePill,
  PageTitle,
  SearchInput,
  Segmented,
  StatusBadge,
  TypeTag,
  type Tone,
} from "@/components/graphite"
import type { LogsIntent } from "@/components/screens/logs-screen"
import type { Action, LogEvent, Workflow, WorkflowStatus } from "@/lib/mock-data"

// README content is user-supplied: rehype-raw lets <img> through, rehype-sanitize
// strips everything outside this allowlist.
const sanitizeSchema = {
  ...defaultSchema,
  attributes: {
    ...defaultSchema.attributes,
    img: ["src", "alt", "width", "height"],
    p: [...(defaultSchema.attributes?.p || []), "align"],
  },
}

const STATUS_TONE: Record<WorkflowStatus, Tone> = {
  running: "running",
  completed: "passed",
  failed: "failed",
  paused: "neutral",
}

const STATUS_DOT: Record<WorkflowStatus, string> = {
  running: "bg-info",
  completed: "bg-success",
  failed: "bg-danger",
  paused: "bg-muted-2",
}

const STATUS_RANK: Record<WorkflowStatus, number> = { running: 0, failed: 1, completed: 2, paused: 3 }

type SortKey = "status" | "issues" | "actions" | "name"

/** Error and warning counts per workflow, read off the loaded event window. */
export function useWorkflowIssues(events: LogEvent[]) {
  return useMemo(() => {
    const byWorkflow = new Map<string, { errors: number; warnings: number }>()
    for (const e of events) {
      if (!e.workflow || (e.level !== "error" && e.level !== "warn")) continue
      const entry = byWorkflow.get(e.workflow) ?? { errors: 0, warnings: 0 }
      if (e.level === "error") entry.errors++
      else entry.warnings++
      byWorkflow.set(e.workflow, entry)
    }
    return byWorkflow
  }, [events])
}

export function WorkflowsScreen({ onOpenLogs }: { onOpenLogs: (intent: LogsIntent) => void }) {
  const { workflows, actions, logEvents } = useCatalogData()
  const [search, setSearch] = useState("")
  const [status, setStatus] = useState("all")
  const [sort, setSort] = useState<SortKey>("status")
  const [selected, setSelected] = useState<Workflow | null>(null)

  const issues = useWorkflowIssues(logEvents)
  const issuesOf = (id: string) => issues.get(id) ?? { errors: 0, warnings: 0 }

  const statusTabs = useMemo(() => {
    const counts: Record<string, number> = { all: workflows.length }
    for (const w of workflows) counts[w.manifestStatus] = (counts[w.manifestStatus] ?? 0) + 1
    return ["all", "running", "completed", "failed", "paused"]
      .filter((k) => k === "all" || counts[k])
      .map((k) => ({ value: k, label: k === "all" ? "All" : k, count: counts[k] }))
  }, [workflows])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    const byIssues = (a: Workflow, b: Workflow) =>
      issuesOf(b.id).errors - issuesOf(a.id).errors ||
      issuesOf(b.id).warnings - issuesOf(a.id).warnings
    return workflows
      .filter((w) => status === "all" || w.manifestStatus === status)
      .filter((w) => !q || `${w.name} ${w.description}`.toLowerCase().includes(q))
      .sort((a, b) => {
        if (sort === "name") return a.name.localeCompare(b.name)
        if (sort === "actions") return b.actionCount - a.actionCount
        if (sort === "issues") return byIssues(a, b) || a.name.localeCompare(b.name)
        return (
          STATUS_RANK[a.manifestStatus] - STATUS_RANK[b.manifestStatus] ||
          byIssues(a, b) ||
          a.name.localeCompare(b.name)
        )
      })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workflows, search, status, sort, issues])

  if (selected) {
    return (
      <WorkflowDetail
        workflow={selected}
        actions={actions}
        events={logEvents}
        issues={issuesOf(selected.id)}
        onBack={() => setSelected(null)}
        onOpenLogs={onOpenLogs}
      />
    )
  }

  const running = workflows.filter((w) => w.manifestStatus === "running").length

  return (
    <div className="flex animate-view-in flex-col gap-4">
      <PageTitle
        title="Workflows"
        subtitle={`${workflows.length} registered · ${running} running`}
      />

      <div className="flex flex-wrap items-center gap-2.5">
        <SearchInput
          value={search}
          onChange={setSearch}
          placeholder="Search name or description…"
          className="min-w-[220px] max-w-[420px] flex-1"
        />
        <Segmented options={statusTabs} value={status} onChange={setStatus} />
        <select
          value={sort}
          onChange={(e) => setSort(e.target.value as SortKey)}
          title="Sort"
          className="cursor-pointer rounded-control border border-border bg-surface px-2 py-1.5 text-[11.5px] text-foreground-2 outline-none"
        >
          <option value="status">Sort: status</option>
          <option value="issues">Sort: issues</option>
          <option value="actions">Sort: size</option>
          <option value="name">Sort: name</option>
        </select>
      </div>

      {filtered.length === 0 ? (
        <EmptyState
          dashed
          message="No workflows match these filters."
          actionLabel="Clear filters"
          onAction={() => { setSearch(""); setStatus("all") }}
        />
      ) : (
        <div className="grid grid-cols-[repeat(auto-fill,minmax(min(100%,340px),1fr))] gap-3">
          {filtered.map((wf) => (
            <WorkflowCard
              key={wf.id}
              workflow={wf}
              issues={issuesOf(wf.id)}
              onClick={() => setSelected(wf)}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function WorkflowCard({
  workflow: wf,
  issues,
  onClick,
}: {
  workflow: Workflow
  issues: { errors: number; warnings: number }
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      className={`flex min-w-0 flex-col gap-3 rounded-card border bg-surface px-[18px] pb-3.5 pt-4 text-left text-foreground hover:border-accent-a30 hover:bg-surface-2 ${
        wf.manifestStatus === "running" ? "border-accent-a30" : "border-border"
      }`}
    >
      <div className="flex w-full min-w-0 items-center gap-2.5">
        <span className={`h-2 w-2 shrink-0 rounded-pill ${STATUS_DOT[wf.manifestStatus]}`} />
        <span className="min-w-0 flex-1 truncate font-mono text-[13.5px] font-medium">{wf.name}</span>
        <StatusBadge tone={STATUS_TONE[wf.manifestStatus]} label={wf.manifestStatus} />
      </div>

      <p className="m-0 line-clamp-2 min-h-[37px] text-[12.5px] leading-[1.5] text-muted-foreground [text-wrap:pretty]">
        {wf.description || "No description in the workflow config."}
      </p>

      <div className="flex w-full flex-col gap-[7px]">
        <div className="flex h-[5px] gap-0.5 overflow-hidden rounded-[3px]" title="LLM vs tool actions">
          <div className="bg-llm" style={{ flex: wf.llmCount || 0 }} />
          <div className="bg-tool" style={{ flex: wf.toolCount || 0 }} />
        </div>
        <div className="flex items-center gap-3 font-mono text-[11px] text-muted-foreground">
          <span className="font-medium text-foreground">{wf.actionCount} actions</span>
          <span className="text-llm-t">{wf.llmCount} llm</span>
          <span className="text-tool-t">{wf.toolCount} tool</span>
          <span className="flex-1" />
          <IssuePill errors={issues.errors} warnings={issues.warnings} />
        </div>
      </div>

      <div className="flex w-full items-center gap-2.5 border-t border-border-soft pt-2.5 font-mono text-[10.5px] text-muted-foreground">
        <span>v{wf.version}</span>
        <span>{wf.levels.length} stages</span>
        <span className="flex-1" />
        <span className="truncate">{wf.defaults.model_name ?? EM_DASH}</span>
      </div>
    </button>
  )
}

/* ─── Detail ────────────────────────────────────────────────────────────── */

function WorkflowDetail({
  workflow,
  actions,
  events,
  issues,
  onBack,
  onOpenLogs,
}: {
  workflow: Workflow
  actions: Record<string, Action>
  events: LogEvent[]
  issues: { errors: number; warnings: number }
  onBack: () => void
  onOpenLogs: (intent: LogsIntent) => void
}) {
  const [tab, setTab] = useState<"graph" | "actions" | "readme">("graph")
  const [selectedKey, setSelectedKey] = useState<string | null>(null)

  const stepOf = useMemo(() => {
    const order = new Map<string, number>()
    let pos = 1
    for (const level of workflow.levels) for (const name of level) order.set(name, pos++)
    return order
  }, [workflow.levels])

  // Catalog order is arbitrary; the step column is only readable in step order.
  const wfActions = useMemo(
    () =>
      Object.entries(actions)
        .filter(([, a]) => a.wf === workflow.id)
        .sort(([ka], [kb]) => {
          const na = ka.split("/").pop() ?? ka
          const nb = kb.split("/").pop() ?? kb
          return (stepOf.get(na) ?? Infinity) - (stepOf.get(nb) ?? Infinity) || na.localeCompare(nb)
        }),
    [workflow.id, actions, stepOf],
  )

  const eventsByAction = useMemo(() => {
    const map = new Map<string, LogEvent[]>()
    for (const e of events) {
      if (e.workflow !== workflow.id || !e.actionName) continue
      const list = map.get(e.actionName)
      if (list) list.push(e)
      else map.set(e.actionName, [e])
    }
    return map
  }, [events, workflow.id])

  const selected = selectedKey ? actions[selectedKey] : null
  const selectedName = selectedKey ? (selectedKey.split("/").pop() ?? selectedKey) : null

  const tabs = [
    { value: "graph", label: "Graph" },
    { value: "actions", label: "Actions", count: wfActions.length },
    ...(workflow.readme ? [{ value: "readme", label: "README" }] : []),
  ]

  return (
    <div className="flex max-w-[1280px] animate-view-in flex-col gap-3.5">
      <div className="flex flex-wrap items-start gap-3.5">
        <BackButton onClick={onBack} title="Back to workflows" />
        <div className="min-w-[260px] flex-1">
          <div className="flex flex-wrap items-center gap-2.5">
            <span className={`h-[9px] w-[9px] rounded-pill ${STATUS_DOT[workflow.manifestStatus]}`} />
            <h1 className="m-0 font-mono text-[19px] font-semibold">{workflow.name}</h1>
            <StatusBadge tone={STATUS_TONE[workflow.manifestStatus]} label={workflow.manifestStatus} />
            <span className="rounded-sm border border-border-2 px-1.5 py-0.5 font-mono text-[10.5px] text-muted-foreground">
              v{workflow.version}
            </span>
          </div>
          <p className="mt-1.5 text-[12.5px] text-muted-foreground [text-wrap:pretty]">{workflow.description}</p>
        </div>
        <button
          onClick={() => onOpenLogs({ q: workflow.id })}
          className="flex items-center gap-2 rounded-control border border-border bg-surface px-3 py-1.5 text-xs text-foreground-2 hover:border-border-2 hover:text-foreground"
        >
          Logs
          <IssuePill errors={issues.errors} warnings={issues.warnings} />
        </button>
      </div>

      <div className="grid grid-cols-[repeat(auto-fit,minmax(120px,1fr))] overflow-hidden rounded-card border border-border bg-surface">
        <StatCell label="Actions" value={String(workflow.actionCount)} />
        <StatCell label="Stages" value={String(workflow.levels.length)} />
        <StatCell label="LLM" value={String(workflow.llmCount)} valueClass="text-llm-t" />
        <StatCell label="Tool" value={String(workflow.toolCount)} valueClass="text-tool-t" last />
      </div>

      <div className="flex flex-wrap gap-1.5">
        {Object.entries(workflow.defaults)
          .filter(([, v]) => v !== null && v !== "")
          .map(([k, v]) => (
            <span key={k} className="rounded-control bg-surface-2 px-2.5 py-1 font-mono text-[10.5px] text-muted-foreground">
              {k} <span className="text-foreground">{String(v)}</span>
            </span>
          ))}
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <Segmented options={tabs} value={tab} onChange={(v) => setTab(v as typeof tab)} />
        <span className="flex-1" />
        <div className="flex items-center gap-3 text-[11px] text-muted-foreground">
          <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm bg-llm" />LLM</span>
          <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm bg-tool" />Tool</span>
          <span className="font-mono text-[10.5px] text-muted-2">click a node to trace</span>
        </div>
      </div>

      <div
        className="grid items-start gap-3.5"
        style={{ gridTemplateColumns: selected ? "minmax(0,1fr) minmax(0,380px)" : "minmax(0,1fr)" }}
      >
        <div className="min-w-0">
          {tab === "graph" && (
            <WorkflowDAGView
              actions={actions}
              workflowId={workflow.id}
              onNodeClick={(n) => setSelectedKey((cur) => (cur === n ? null : n))}
            />
          )}

          {tab === "actions" && (
            <Card>
              <div className="grid grid-cols-[46px_56px_minmax(0,1fr)_minmax(0,140px)_70px] items-center gap-2.5 px-4 py-2 text-xs font-medium text-muted-foreground">
                <span>Step</span>
                <span>Type</span>
                <span>Action</span>
                <span>Schema</span>
                <span className="text-right">Deps</span>
              </div>
              {wfActions.map(([key, a]) => {
                const name = key.split("/").pop() ?? key
                const evs = eventsByAction.get(name) ?? []
                const errs = evs.filter((e) => e.level === "error").length
                const warns = evs.filter((e) => e.level === "warn").length
                return (
                  <button
                    key={key}
                    onClick={() => setSelectedKey((cur) => (cur === key ? null : key))}
                    className={`grid w-full grid-cols-[46px_56px_minmax(0,1fr)_minmax(0,140px)_70px] items-center gap-2.5 border-t border-border-soft px-4 py-2.5 text-left hover:bg-hover ${
                      selectedKey === key ? "bg-accent-a12" : ""
                    }`}
                  >
                    <span className="font-mono text-[11px] text-muted-foreground">{stepOf.get(name) ?? EM_DASH}</span>
                    <TypeTag type={a.type} />
                    <span className="flex min-w-0 items-center gap-2">
                      <span className="truncate font-mono text-[12.5px] font-medium">{name}</span>
                      {a.guard && (
                        <span className="shrink-0 rounded-sm bg-warning-a12 px-1.5 py-px text-[9.5px] text-warning-t">
                          guard
                        </span>
                      )}
                      {errs > 0 && <span className="h-[7px] w-[7px] shrink-0 rounded-pill bg-danger" />}
                      {errs === 0 && warns > 0 && <span className="h-[7px] w-[7px] shrink-0 rounded-pill bg-warning" />}
                    </span>
                    <span className={`min-w-0 truncate font-mono text-[10.5px] ${a.schema ? "text-accent-t" : "text-muted-foreground"}`}>
                      {a.schema ?? "none"}
                    </span>
                    <span className="text-right font-mono text-[10.5px] text-muted-foreground">
                      {a.deps.length === 0 ? "root" : a.deps.length}
                    </span>
                  </button>
                )
              })}
              {wfActions.length === 0 && <EmptyState message="This workflow has no actions in the loaded config." />}
            </Card>
          )}

          {tab === "readme" && workflow.readme && (
            <Card className="p-6">
              <article className="prose prose-sm max-w-none dark:prose-invert prose-headings:font-mono prose-code:rounded-sm prose-code:bg-surface-2 prose-code:px-1 prose-code:py-0.5 prose-code:text-foreground-2 prose-code:before:content-none prose-code:after:content-none prose-pre:border prose-pre:border-border-soft prose-pre:bg-well">
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  rehypePlugins={[rehypeRaw, [rehypeSanitize, sanitizeSchema]]}
                >
                  {workflow.readme}
                </ReactMarkdown>
              </article>
            </Card>
          )}
        </div>

        {selected && selectedName && (
          <div className="sticky top-0 animate-panel-in overflow-hidden rounded-card border border-accent-a30 bg-surface">
            <div className="flex items-center gap-2.5 border-b border-border py-3 pl-4 pr-3">
              <TypeTag type={selected.type} />
              <span className="min-w-0 flex-1 truncate font-mono text-[12.5px] font-medium">{selectedName}</span>
              <button
                onClick={() => setSelectedKey(null)}
                title="Close"
                aria-label="Close"
                className="h-[26px] w-[26px] rounded-control text-base text-muted-foreground hover:bg-hover hover:text-foreground"
              >
                ×
              </button>
            </div>
            <div className="flex max-h-[560px] flex-col gap-4 overflow-y-auto px-4 py-3.5">
              <p className="m-0 text-xs leading-[1.6] text-foreground-2 [text-wrap:pretty]">
                {selected.intent || "No intent declared in the loaded workflow config."}
              </p>

              <div className="grid grid-cols-[auto_1fr] gap-x-3.5 gap-y-1.5 font-mono text-[11px]">
                <span className="text-muted-foreground">step</span>
                <span>{stepOf.get(selectedName) ?? EM_DASH}</span>
                <span className="text-muted-foreground">schema</span>
                <span className={selected.schema ? "text-accent-t" : "text-muted-foreground"}>
                  {selected.schema ?? "none"}
                </span>
                <span className="text-muted-foreground">guard</span>
                <span>{selected.guard ? selected.guard.condition : "none"}</span>
              </div>

              <PanelList
                label="Depends on"
                empty="source input"
                items={selected.deps}
                render={(d) => `← ${d}`}
                onSelect={(d) => setSelectedKey(`${selected.wf}/${d}`)}
              />
              <PanelList
                label="Feeds into"
                empty="workflow output"
                items={dependents(actions, selected.wf, selectedName)}
                render={(d) => `${d} →`}
                onSelect={(d) => setSelectedKey(`${selected.wf}/${d}`)}
              />

              <div className="flex flex-col gap-2">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-medium text-muted-foreground">Recent events</span>
                  <button
                    onClick={() => onOpenLogs({ q: selectedName })}
                    className="border-0 bg-transparent p-0 text-[11px] text-accent-t hover:underline"
                  >
                    Open in Logs →
                  </button>
                </div>
                {(eventsByAction.get(selectedName) ?? []).slice(0, 4).map((e) => (
                  <button
                    key={e.id}
                    onClick={() => onOpenLogs({ q: selectedName })}
                    className="flex w-full flex-col gap-1 rounded-control border border-border-soft px-2.5 py-2 text-left hover:border-border-2"
                  >
                    <span className="flex items-center gap-2 font-mono text-[10px] text-muted-foreground">
                      <span className="text-foreground-3">{e.level.toUpperCase()}</span>
                      <span>{e.code}</span>
                      <span className="flex-1" />
                      <span>{fmtClock(e.timestamp)}</span>
                    </span>
                    <span className="line-clamp-2 text-[11.5px] leading-[1.45] text-foreground-2">{e.message}</span>
                  </button>
                ))}
                {(eventsByAction.get(selectedName) ?? []).length === 0 && (
                  <span className="text-[11.5px] leading-[1.5] text-muted-foreground">
                    No events for this action in the loaded log window.
                  </span>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function dependents(actions: Record<string, Action>, wf: string, name: string): string[] {
  const out: string[] = []
  for (const [key, a] of Object.entries(actions)) {
    if (a.wf !== wf) continue
    if (a.deps.includes(name)) out.push(key.split("/").pop() ?? key)
  }
  return out
}

function PanelList({
  label,
  empty,
  items,
  render,
  onSelect,
}: {
  label: string
  empty: string
  items: string[]
  render: (item: string) => string
  onSelect: (item: string) => void
}) {
  return (
    <div className="flex flex-col gap-2">
      <div className="text-xs font-medium text-muted-foreground">{label}</div>
      <div className="flex flex-wrap gap-1.5">
        {items.length === 0 ? (
          <span className="rounded-control border border-dashed border-border-2 px-2.5 py-1 font-mono text-[10.5px] text-muted-foreground">
            {empty}
          </span>
        ) : (
          items.map((d) => (
            <button
              key={d}
              onClick={() => onSelect(d)}
              className="rounded-control border border-transparent bg-surface-2 px-2.5 py-1 font-mono text-[10.5px] text-accent-t hover:border-accent-a30"
            >
              {render(d)}
            </button>
          ))
        )}
      </div>
    </div>
  )
}

function StatCell({
  label,
  value,
  valueClass = "text-foreground",
  last = false,
}: {
  label: string
  value: string
  valueClass?: string
  last?: boolean
}) {
  return (
    <div className={`px-4 py-2.5 ${last ? "" : "border-r border-border-soft"}`}>
      <div className="text-xs font-medium text-muted-foreground">{label}</div>
      <div className={`mt-1 text-xl font-semibold ${valueClass}`}>{value}</div>
    </div>
  )
}
