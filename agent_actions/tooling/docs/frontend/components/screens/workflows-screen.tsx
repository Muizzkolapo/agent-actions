"use client"

import { useState, useMemo } from "react"
import { Search, ArrowLeft, ArrowRight, Circle } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs"
import { ScrollArea } from "@/components/ui/scroll-area"
import { useCatalogData } from "@/lib/catalog-context"
import { WorkflowDAGView } from "@/components/workflow-dag"
import type { Workflow, WorkflowStatus, Action } from "@/lib/mock-data"

export function WorkflowsScreen() {
  const { workflows, actions } = useCatalogData()
  const [search, setSearch] = useState("")
  const [selected, setSelected] = useState<Workflow | null>(null)

  const filtered = workflows.filter(
    (w) =>
      w.name.toLowerCase().includes(search.toLowerCase()) ||
      w.description.toLowerCase().includes(search.toLowerCase()),
  )

  if (selected) {
    return <WorkflowDetail workflow={selected} actions={actions} onBack={() => setSelected(null)} />
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">Workflows</h1>
        <p className="text-sm text-muted-foreground mt-1">{workflows.length} registered workflows</p>
      </div>

      <div className="flex items-center gap-3">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Filter by name..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9 h-9 bg-secondary border-0 text-sm placeholder:text-muted-foreground"
          />
        </div>
      </div>

      <div className="grid grid-cols-1 gap-3">
        {filtered.map((wf) => (
          <button
            key={wf.id}
            className="group relative overflow-hidden rounded-xl border border-border bg-card p-5 text-left hover:border-[hsl(var(--primary))]/25 transition-all"
            onClick={() => setSelected(wf)}
          >
            <div
              className="absolute top-0 left-0 right-0 h-px"
              style={{
                backgroundColor:
                  wf.manifestStatus === "running" ? "hsl(var(--primary))"
                  : wf.manifestStatus === "completed" ? "hsl(var(--success))"
                  : wf.manifestStatus === "failed" ? "hsl(var(--destructive))"
                  : "hsl(var(--border))",
                opacity: 0.6,
              }}
            />
            <div className="flex items-start justify-between">
              <div className="flex items-center gap-2.5">
                <StatusIcon status={wf.manifestStatus} />
                <h3 className="text-sm font-mono font-medium text-foreground">{wf.name}</h3>
                <StatusBadge status={wf.manifestStatus} />
                <Badge variant="outline" className="text-[10px] font-normal rounded-md border-border text-muted-foreground">
                  v{wf.version}
                </Badge>
              </div>
              <ArrowRight className="h-4 w-4 text-muted-foreground opacity-0 -translate-x-1 group-hover:opacity-100 group-hover:translate-x-0 transition-all" />
            </div>
            <p className="text-xs text-muted-foreground mt-2.5 leading-relaxed">{wf.description}</p>

            {/* Stats row */}
            <div className="flex items-center gap-4 mt-4 pt-3 border-t border-border/50">
              <div className="flex items-center gap-1.5">
                <div className="h-1 w-1 rounded-full bg-muted-foreground" />
                <span className="text-xs text-muted-foreground tabular-nums">{wf.actionCount} actions</span>
              </div>
              <div className="flex items-center gap-1.5">
                <div className="h-1 w-1 rounded-full bg-purple-400" />
                <span className="text-xs text-muted-foreground tabular-nums">{wf.llmCount} llm</span>
              </div>
              <div className="flex items-center gap-1.5">
                <div className="h-1 w-1 rounded-full bg-emerald-400" />
                <span className="text-xs text-muted-foreground tabular-nums">{wf.toolCount} tool</span>
              </div>
              <div className="flex items-center gap-1.5">
                <div className="h-1 w-1 rounded-full bg-muted-foreground" />
                <span className="text-xs text-muted-foreground tabular-nums">{wf.levels.length} levels</span>
              </div>
              {wf.defaults.model_name && (
                <span className="ml-auto text-xs font-mono text-[hsl(var(--primary))]">
                  {wf.defaults.model_name}
                </span>
              )}
              {wf.defaults.run_mode && (
                <span className="text-xs font-mono text-muted-foreground">
                  {wf.defaults.run_mode}
                </span>
              )}
            </div>
          </button>
        ))}
      </div>
    </div>
  )
}

function WorkflowDetail({ workflow, actions, onBack }: { workflow: Workflow; actions: Record<string, Action>; onBack: () => void }) {
  const [selectedAction, setSelectedAction] = useState<string | null>(null)
  const wfActions = useMemo(
    () => Object.entries(actions).filter(([_, a]) => a.wf === workflow.id),
    [workflow.id],
  )
  const actionDetail = selectedAction ? actions[selectedAction] : null

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
            <StatusIcon status={workflow.manifestStatus} />
            <h1 className="text-xl font-mono font-semibold text-foreground">{workflow.name}</h1>
            <StatusBadge status={workflow.manifestStatus} />
            <Badge variant="outline" className="text-[10px] font-normal rounded-md border-border text-muted-foreground">
              v{workflow.version}
            </Badge>
          </div>
          <p className="text-sm text-muted-foreground mt-1">{workflow.description}</p>
        </div>
        <div className="hidden sm:flex items-center gap-4">
          <div className="flex flex-col items-end">
            <span className="text-lg font-bold tabular-nums text-foreground">{workflow.actionCount}</span>
            <span className="text-[10px] uppercase tracking-wider text-muted-foreground">actions</span>
          </div>
          <div className="h-8 w-px bg-border" />
          <div className="flex flex-col items-end">
            <span className="text-lg font-bold tabular-nums text-foreground">{workflow.levels.length}</span>
            <span className="text-[10px] uppercase tracking-wider text-muted-foreground">levels</span>
          </div>
        </div>
      </div>

      {/* Defaults tags */}
      <div className="flex gap-2 flex-wrap">
        {Object.entries(workflow.defaults)
          .filter(([_, v]) => v !== null)
          .map(([k, v]) => (
            <span
              key={k}
              className="rounded-md bg-secondary px-2 py-0.5 text-[10px] font-mono text-muted-foreground"
            >
              {k}: <span className="text-foreground">{String(v)}</span>
            </span>
          ))}
      </div>

      <Tabs defaultValue="graph" className="w-full">
        <TabsList className="bg-secondary/50 border border-border p-0.5">
          <TabsTrigger value="graph" className="text-xs data-[state=active]:bg-card data-[state=active]:text-foreground data-[state=active]:shadow-sm rounded-md">
            Graph
          </TabsTrigger>
          <TabsTrigger value="lineage" className="text-xs data-[state=active]:bg-card data-[state=active]:text-foreground data-[state=active]:shadow-sm rounded-md">
            Lineage
          </TabsTrigger>
          <TabsTrigger value="actions" className="text-xs data-[state=active]:bg-card data-[state=active]:text-foreground data-[state=active]:shadow-sm rounded-md">
            Actions ({wfActions.length})
          </TabsTrigger>
        </TabsList>

        <TabsContent value="graph" className="mt-4">
          <div className="flex items-center gap-4 mb-3">
            <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">Execution Graph</span>
            <div className="flex items-center gap-1.5">
              <div className="h-2 w-2 rounded-full bg-blue-400" />
              <span className="text-[10px] text-muted-foreground">LLM</span>
            </div>
            <div className="flex items-center gap-1.5">
              <div className="h-2 w-2 rounded-full bg-emerald-400" />
              <span className="text-[10px] text-muted-foreground">Tool</span>
            </div>
          </div>
          <WorkflowDAGView
            actions={actions}
            workflowId={workflow.id}
            mode="dag"
            onNodeClick={(n) => setSelectedAction(n === selectedAction ? null : n)}
          />
        </TabsContent>

        <TabsContent value="lineage" className="mt-4">
          <div className="flex items-center gap-4 mb-3">
            <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">Field-Level Lineage</span>
            <div className="flex items-center gap-1.5">
              <div className="h-2 w-2 rounded-full bg-blue-400" />
              <span className="text-[10px] text-muted-foreground">Input</span>
            </div>
            <div className="flex items-center gap-1.5">
              <div className="h-2 w-2 rounded-full bg-amber-400" />
              <span className="text-[10px] text-muted-foreground">Output</span>
            </div>
            <div className="flex items-center gap-1.5">
              <div className="h-2 w-2 rounded-full bg-emerald-400" />
              <span className="text-[10px] text-muted-foreground">Field Flow</span>
            </div>
          </div>
          <WorkflowDAGView
            actions={actions}
            workflowId={workflow.id}
            mode="lineage"
            onNodeClick={(n) => setSelectedAction(n === selectedAction ? null : n)}
          />
        </TabsContent>

        <TabsContent value="actions" className="mt-4">
          <div className={`grid gap-4 ${actionDetail ? "grid-cols-[1fr_360px]" : "grid-cols-1"}`}>
            <ScrollArea className="h-[500px]">
              <div className="rounded-xl border border-border bg-card overflow-hidden divide-y divide-border">
                {wfActions.map(([name, a]) => (
                  <button
                    key={name}
                    className={`flex w-full items-center gap-3 px-5 py-3 text-left hover:bg-accent/30 transition-colors ${
                      selectedAction === name ? "bg-[hsl(var(--primary))]/5" : ""
                    }`}
                    onClick={() => setSelectedAction(selectedAction === name ? null : name)}
                  >
                    <TypeBadge type={a.type} />
                    <span className="text-sm font-mono font-medium text-foreground flex-1 truncate">{name}</span>
                    {a.guard && (
                      <Badge variant="outline" className="text-[10px] font-normal rounded-md bg-[hsl(var(--warning))]/10 text-[hsl(var(--warning))] border-[hsl(var(--warning))]/20">
                        guard
                      </Badge>
                    )}
                    {a.schema && (
                      <span className="text-[10px] font-mono text-[hsl(var(--primary))]">{a.schema}</span>
                    )}
                    <span className="text-[10px] font-mono text-muted-foreground">{a.deps.length} deps</span>
                    {a.metrics.success_count > 0 && (
                      <span className="text-[10px] font-mono text-[hsl(var(--success))]">{a.metrics.success_count}</span>
                    )}
                  </button>
                ))}
              </div>
            </ScrollArea>

            {actionDetail && selectedAction && (
              <ActionInspector
                name={selectedAction}
                action={actionDetail}
                onClose={() => setSelectedAction(null)}
                onSelectAction={(n) => setSelectedAction(n)}
              />
            )}
          </div>
        </TabsContent>
      </Tabs>
    </div>
  )
}

/* --- Action Inspector --- */
function ActionInspector({
  name,
  action,
  onClose,
  onSelectAction,
}: {
  name: string
  action: Action
  onClose: () => void
  onSelectAction: (name: string) => void
}) {
  return (
    <div className="rounded-xl border border-[hsl(var(--primary))]/30 bg-card overflow-hidden">
      <div className="flex items-center justify-between border-b border-border px-5 py-3.5">
        <span className="text-sm font-mono font-medium text-foreground truncate">{name}</span>
        <button onClick={onClose} className="text-muted-foreground hover:text-foreground transition-colors text-sm">
          ×
        </button>
      </div>
      <div className="p-5 flex flex-col gap-4 overflow-y-auto max-h-[440px]">
        <div className="flex gap-2 flex-wrap">
          <TypeBadge type={action.type} />
          {action.schema && (
            <Badge variant="outline" className="text-[10px] font-normal rounded-md bg-[hsl(var(--primary))]/10 text-[hsl(var(--primary))] border-[hsl(var(--primary))]/20">
              {action.schema}
            </Badge>
          )}
          {action.guard && (
            <Badge variant="outline" className="text-[10px] font-normal rounded-md bg-[hsl(var(--warning))]/10 text-[hsl(var(--warning))] border-[hsl(var(--warning))]/20">
              guarded
            </Badge>
          )}
        </div>
        <p className="text-xs text-muted-foreground leading-relaxed">{action.intent}</p>

        <div>
          <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold block mb-2">Dependencies</span>
          <div className="flex gap-1.5 flex-wrap">
            {action.deps.length === 0 ? (
              <span className="text-xs font-mono text-muted-foreground">source (root)</span>
            ) : (
              action.deps.map((d) => (
                <button
                  key={d}
                  onClick={() => onSelectAction(d)}
                  className="rounded-md bg-secondary px-2 py-0.5 text-[10px] font-mono text-[hsl(var(--primary))] hover:bg-[hsl(var(--primary))]/10 transition-colors"
                >
                  {d}
                </button>
              ))
            )}
          </div>
        </div>

        {action.guard && (
          <div>
            <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold block mb-2">Guard</span>
            <div className="rounded-lg bg-[hsl(var(--warning))]/5 border border-[hsl(var(--warning))]/15 p-3 font-mono text-xs text-[hsl(var(--warning))] leading-relaxed">
              <div>condition: {action.guard.condition}</div>
              <div>on_false: {action.guard.on_false}</div>
            </div>
          </div>
        )}

        {action.inputs.length > 0 && (
          <div>
            <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold block mb-2">Inputs</span>
            <div className="flex gap-1.5 flex-wrap">
              {action.inputs.map((f) => (
                <span key={f} className="rounded-md bg-blue-500/10 px-2 py-0.5 text-[10px] font-mono text-blue-400">{f}</span>
              ))}
            </div>
          </div>
        )}

        {action.outputs.length > 0 && (
          <div>
            <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold block mb-2">Outputs</span>
            <div className="flex gap-1.5 flex-wrap">
              {action.outputs.map((f) => (
                <span key={f} className="rounded-md bg-emerald-500/10 px-2 py-0.5 text-[10px] font-mono text-emerald-400">{f}</span>
              ))}
            </div>
          </div>
        )}

        {action.prompt && (
          <div>
            <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold block mb-2">Prompt Preview</span>
            <div className="rounded-lg bg-secondary/50 border border-border/50 p-3 font-mono text-xs text-muted-foreground leading-relaxed max-h-24 overflow-auto">
              {action.prompt}
            </div>
          </div>
        )}

        {action.type === "tool" && action.impl && (
          <div>
            <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold block mb-2">Implementation</span>
            <span className="rounded-md bg-[hsl(var(--success))]/10 px-2 py-1 text-xs font-mono text-[hsl(var(--success))]">
              {action.impl}()
            </span>
          </div>
        )}

        <div>
          <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold block mb-2">Metrics</span>
          <div className="rounded-lg border border-border divide-y divide-border text-xs font-mono">
            <MetricRow label="execution_time" value={action.metrics.execution_time ? `${action.metrics.execution_time}s` : "\u2014"} />
            <MetricRow label="success_count" value={String(action.metrics.success_count)} valueColor={action.metrics.success_count > 0 ? "text-[hsl(var(--success))]" : undefined} />
            <MetricRow label="failed_count" value={String(action.metrics.failed_count)} valueColor={action.metrics.failed_count > 0 ? "text-[hsl(var(--destructive))]" : undefined} />
            {action.metrics.tokens?.prompt_tokens != null && (
              <MetricRow label="prompt_tokens" value={action.metrics.tokens.prompt_tokens.toLocaleString()} />
            )}
            {action.metrics.tokens?.completion_tokens != null && (
              <MetricRow label="completion_tokens" value={action.metrics.tokens.completion_tokens.toLocaleString()} />
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

/* --- Helper components --- */

function TypeBadge({ type }: { type: string }) {
  const isLlm = type === "llm"
  return (
    <Badge
      variant="outline"
      className={`w-14 justify-center text-[10px] font-normal rounded-md ${
        isLlm
          ? "bg-purple-500/10 text-purple-400 border-purple-500/20"
          : "bg-emerald-500/10 text-emerald-400 border-emerald-500/20"
      }`}
    >
      {type}
    </Badge>
  )
}

function MetricRow({ label, value, valueColor }: { label: string; value: string; valueColor?: string }) {
  return (
    <div className="flex items-center justify-between px-3 py-2">
      <span className="text-muted-foreground">{label}</span>
      <span className={valueColor || "text-foreground"}>{value}</span>
    </div>
  )
}

function StatusIcon({ status }: { status: WorkflowStatus }) {
  switch (status) {
    case "running":
      return (
        <div className="relative">
          <Circle className="h-3 w-3 fill-[hsl(var(--primary))] text-[hsl(var(--primary))]" />
          <Circle className="h-3 w-3 absolute inset-0 fill-[hsl(var(--primary))] text-[hsl(var(--primary))] animate-ping opacity-40" />
        </div>
      )
    case "completed":
      return <Circle className="h-3 w-3 fill-[hsl(var(--success))] text-[hsl(var(--success))]" />
    case "failed":
      return <Circle className="h-3 w-3 fill-[hsl(var(--destructive))] text-[hsl(var(--destructive))]" />
    default:
      return <Circle className="h-3 w-3 text-muted-foreground" />
  }
}

function StatusBadge({ status }: { status: WorkflowStatus }) {
  const styles: Record<WorkflowStatus, string> = {
    running: "bg-[hsl(var(--primary))]/10 text-[hsl(var(--primary))] border-[hsl(var(--primary))]/20",
    completed: "bg-[hsl(var(--success))]/10 text-[hsl(var(--success))] border-[hsl(var(--success))]/20",
    failed: "bg-[hsl(var(--destructive))]/10 text-[hsl(var(--destructive))] border-[hsl(var(--destructive))]/20",
    paused: "bg-secondary text-muted-foreground border-border",
  }
  return (
    <Badge variant="outline" className={`text-[10px] font-normal rounded-md ${styles[status]}`}>
      {status === "running" && <span className="mr-1 inline-block h-1.5 w-1.5 rounded-full bg-[hsl(var(--primary))] animate-pulse" />}
      {status}
    </Badge>
  )
}
