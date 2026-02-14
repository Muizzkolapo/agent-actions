"use client"

import { useState, useMemo } from "react"
import { Search, Filter, ArrowRight, X, LayoutGrid, List, Shield, ArrowLeft } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs"
import { useCatalogData } from "@/lib/catalog-context"
import type { Action } from "@/lib/mock-data"

type SortKey = "name" | "type" | "workflow" | "deps"
type SortDir = "asc" | "desc"

export function ActionsScreen() {
  const { actions } = useCatalogData()
  const [search, setSearch] = useState("")
  const [typeFilter, setTypeFilter] = useState<string[]>([])
  const [depFilter, setDepFilter] = useState<string | null>(null)
  const [sortKey, setSortKey] = useState<SortKey>("name")
  const [sortDir, setSortDir] = useState<SortDir>("asc")
  const [view, setView] = useState<"list" | "grid">("list")
  const [showFilters, setShowFilters] = useState(false)
  const [selectedAction, setSelectedAction] = useState<string | null>(null)

  const allActions = useMemo(
    () => Object.entries(actions).map(([name, a]) => ({ name, ...a })),
    [actions],
  )

  const filtered = useMemo(() => {
    let list = allActions.filter((a) => {
      if (search && !a.name.toLowerCase().includes(search.toLowerCase()) && !a.intent.toLowerCase().includes(search.toLowerCase())) return false
      if (typeFilter.length > 0 && !typeFilter.includes(a.type)) return false
      if (depFilter === "has" && a.deps.length === 0) return false
      if (depFilter === "none" && a.deps.length > 0) return false
      return true
    })
    list.sort((a, b) => {
      let cmp = 0
      if (sortKey === "name") cmp = a.name.localeCompare(b.name)
      else if (sortKey === "type") cmp = a.type.localeCompare(b.type)
      else if (sortKey === "deps") cmp = a.deps.length - b.deps.length
      else if (sortKey === "workflow") cmp = a.wf.localeCompare(b.wf)
      return sortDir === "desc" ? -cmp : cmp
    })
    return list
  }, [allActions, search, typeFilter, depFilter, sortKey, sortDir])

  const activeFilterCount = typeFilter.length + (depFilter ? 1 : 0)

  const toggleType = (t: string) =>
    setTypeFilter((prev) => (prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t]))

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) setSortDir((d) => (d === "asc" ? "desc" : "asc"))
    else { setSortKey(key); setSortDir("asc") }
  }

  /* Detail view: full-page layout when an action is selected */
  if (selectedAction && actions[selectedAction]) {
    return (
      <ActionDetail
        name={selectedAction}
        action={actions[selectedAction]}
        onBack={() => setSelectedAction(null)}
        onSelectAction={(name) => setSelectedAction(name)}
      />
    )
  }

  /* List view */
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">All Actions</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Browse all {allActions.length} actions across workflows
        </p>
      </div>

      {/* Toolbar */}
      <div className="flex items-center gap-3 flex-wrap">
        <div className="relative flex-1 min-w-[200px]">
          <Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Search actions by name or intent..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9 h-9 bg-secondary border-0 text-sm placeholder:text-muted-foreground"
          />
        </div>
        <Button
          variant="outline"
          size="sm"
          className="h-9 gap-2 border-border text-muted-foreground bg-transparent"
          onClick={() => setShowFilters(!showFilters)}
        >
          <Filter className="h-3.5 w-3.5" />
          Filters
          {activeFilterCount > 0 && (
            <Badge variant="secondary" className="ml-1 h-5 min-w-5 justify-center rounded-md text-[10px]">
              {activeFilterCount}
            </Badge>
          )}
        </Button>
        <div className="flex gap-1 border border-border rounded-lg p-0.5">
          <button
            onClick={() => setView("list")}
            className={`p-1.5 rounded-md transition-colors ${view === "list" ? "bg-secondary text-foreground" : "text-muted-foreground hover:text-foreground"}`}
          >
            <List className="h-3.5 w-3.5" />
          </button>
          <button
            onClick={() => setView("grid")}
            className={`p-1.5 rounded-md transition-colors ${view === "grid" ? "bg-secondary text-foreground" : "text-muted-foreground hover:text-foreground"}`}
          >
            <LayoutGrid className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      {/* Filter panel */}
      {showFilters && (
        <div className="rounded-xl border border-border bg-card p-4 flex items-center gap-6 flex-wrap">
          <div className="flex items-center gap-2">
            <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">Type</span>
            {["llm", "tool"].map((t) => (
              <button
                key={t}
                onClick={() => toggleType(t)}
                className={`rounded-lg px-2.5 py-1 text-xs font-medium capitalize transition-all ${
                  typeFilter.includes(t)
                    ? t === "llm"
                      ? "bg-purple-500/15 text-purple-400 ring-1 ring-purple-500/20"
                      : "bg-emerald-500/15 text-emerald-400 ring-1 ring-emerald-500/20"
                    : "text-muted-foreground hover:bg-accent"
                }`}
              >
                {t}
              </button>
            ))}
          </div>
          <div className="h-6 w-px bg-border" />
          <div className="flex items-center gap-2">
            <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">Dependencies</span>
            {[
              { label: "All", value: null },
              { label: "Has deps", value: "has" },
              { label: "No deps", value: "none" },
            ].map((opt) => (
              <button
                key={opt.label}
                onClick={() => setDepFilter(opt.value)}
                className={`rounded-lg px-2.5 py-1 text-xs font-medium transition-all ${
                  depFilter === opt.value
                    ? "bg-[hsl(var(--primary))]/15 text-[hsl(var(--primary))] ring-1 ring-[hsl(var(--primary))]/20"
                    : "text-muted-foreground hover:bg-accent"
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>
          <div className="h-6 w-px bg-border" />
          <div className="flex items-center gap-2">
            <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">Sort</span>
            {(["name", "type", "workflow", "deps"] as SortKey[]).map((key) => (
              <button
                key={key}
                onClick={() => toggleSort(key)}
                className={`rounded-lg px-2.5 py-1 text-xs font-medium capitalize transition-all ${
                  sortKey === key
                    ? "bg-[hsl(var(--primary))]/15 text-[hsl(var(--primary))] ring-1 ring-[hsl(var(--primary))]/20"
                    : "text-muted-foreground hover:bg-accent"
                }`}
              >
                {key}
                {sortKey === key && (sortDir === "asc" ? " \u2191" : " \u2193")}
              </button>
            ))}
          </div>
          {activeFilterCount > 0 && (
            <button
              onClick={() => { setTypeFilter([]); setDepFilter(null) }}
              className="ml-auto flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
            >
              <X className="h-3 w-3" />
              Clear
            </button>
          )}
        </div>
      )}

      {/* Action list or grid */}
      {view === "list" ? (
        <div className="rounded-xl border border-border bg-card overflow-hidden divide-y divide-border">
          {/* Table header */}
          <div className="grid grid-cols-[auto_1fr_1fr_auto_auto_auto] items-center gap-4 px-5 py-2.5 bg-secondary/30">
            <span className="w-14 text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">Type</span>
            <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">Name</span>
            <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">Workflow</span>
            <span className="w-16 text-[10px] uppercase tracking-wider text-muted-foreground font-semibold text-center">Deps</span>
            <span className="w-20 text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">Guard</span>
            <span className="w-4" />
          </div>
          {filtered.map((action) => (
            <button
              key={action.name}
              className="grid grid-cols-[auto_1fr_1fr_auto_auto_auto] items-center gap-4 px-5 py-3 w-full text-left hover:bg-accent/30 transition-colors"
              onClick={() => setSelectedAction(action.name)}
            >
              <TypeBadge type={action.type} />
              <div className="min-w-0">
                <span className="text-sm font-mono font-medium text-foreground truncate block">{action.name}</span>
                <span className="text-[11px] text-muted-foreground line-clamp-1">{action.intent}</span>
              </div>
              <span className="text-xs font-mono text-muted-foreground truncate">{action.wf}</span>
              <span className="w-16 text-center text-xs font-mono text-muted-foreground tabular-nums">
                {action.deps.length}
              </span>
              <span className="w-20">
                {action.guard && (
                  <Badge variant="outline" className="text-[10px] font-normal rounded-md bg-[hsl(var(--warning))]/10 text-[hsl(var(--warning))] border-[hsl(var(--warning))]/20">
                    <Shield className="h-3 w-3 mr-1" />
                    guard
                  </Badge>
                )}
              </span>
              <ArrowRight className="h-3.5 w-3.5 text-muted-foreground/40" />
            </button>
          ))}
          {filtered.length === 0 && (
            <div className="flex items-center justify-center py-16 text-sm text-muted-foreground">
              No actions match the current filters
            </div>
          )}
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {filtered.map((action) => (
            <button
              key={action.name}
              className="group relative overflow-hidden rounded-xl border border-border bg-card p-5 text-left hover:border-[hsl(var(--primary))]/25 transition-all"
              onClick={() => setSelectedAction(action.name)}
            >
              <div
                className="absolute top-0 left-0 right-0 h-px"
                style={{
                  backgroundColor: action.type === "llm" ? "hsl(var(--chart-5))" : "hsl(var(--success))",
                  opacity: 0.5,
                }}
              />
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-2.5">
                  <TypeBadge type={action.type} />
                  <h3 className="text-sm font-mono font-medium text-foreground">{action.name}</h3>
                </div>
                {action.guard && (
                  <Badge variant="outline" className="text-[10px] font-normal rounded-md bg-[hsl(var(--warning))]/10 text-[hsl(var(--warning))] border-[hsl(var(--warning))]/20">
                    guard
                  </Badge>
                )}
              </div>
              <p className="text-xs text-muted-foreground mt-2 leading-relaxed line-clamp-2">{action.intent}</p>
              <div className="flex items-center gap-3 mt-3 pt-2.5 border-t border-border/50">
                <span className="text-[10px] font-mono text-muted-foreground">{action.wf}</span>
                <span className="text-[10px] text-muted-foreground">{action.deps.length} deps</span>
                {action.schema && (
                  <span className="text-[10px] font-mono text-[hsl(var(--primary))]">{action.schema}</span>
                )}
                {action.metrics.success_count > 0 && (
                  <span className="ml-auto text-[10px] font-mono text-[hsl(var(--success))]">
                    {action.metrics.success_count} runs
                  </span>
                )}
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

/* --- Full-page Action Detail --- */

function ActionDetail({
  name,
  action,
  onBack,
  onSelectAction,
}: {
  name: string
  action: Action
  onBack: () => void
  onSelectAction: (name: string) => void
}) {
  return (
    <div className="flex flex-col gap-4">
      {/* Header */}
      <div className="flex items-center gap-3">
        <button
          onClick={onBack}
          className="flex h-8 w-8 items-center justify-center rounded-lg border border-border bg-card text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
        >
          <ArrowLeft className="h-4 w-4" />
        </button>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h1 className="text-lg font-mono font-semibold text-foreground truncate">{name}</h1>
            <TypeBadge type={action.type} />
            {action.schema && (
              <Badge variant="outline" className="text-[10px] font-normal rounded-md bg-[hsl(var(--primary))]/10 text-[hsl(var(--primary))] border-[hsl(var(--primary))]/20">
                {action.schema}
              </Badge>
            )}
            {action.guard && (
              <Badge variant="outline" className="text-[10px] font-normal rounded-md bg-[hsl(var(--warning))]/10 text-[hsl(var(--warning))] border-[hsl(var(--warning))]/20">
                <Shield className="h-3 w-3 mr-1" />
                guarded
              </Badge>
            )}
            {action.model && (
              <Badge variant="outline" className="text-[10px] font-normal rounded-md border-border text-muted-foreground">
                {action.model}
              </Badge>
            )}
            {action.provider && (
              <Badge variant="outline" className="text-[10px] font-normal rounded-md border-border text-muted-foreground">
                {action.provider}
              </Badge>
            )}
          </div>
          <p className="text-xs text-muted-foreground mt-0.5 font-mono">{action.wf}</p>
        </div>
      </div>

      {/* Tabs */}
      <Tabs defaultValue="overview">
        <TabsList className="h-8 bg-secondary/50 p-0.5">
          <TabsTrigger value="overview" className="text-xs px-3 py-1 data-[state=active]:bg-card data-[state=active]:shadow-sm">
            Overview
          </TabsTrigger>
          <TabsTrigger value="config" className="text-xs px-3 py-1 data-[state=active]:bg-card data-[state=active]:shadow-sm">
            Config
          </TabsTrigger>
          <TabsTrigger value="metrics" className="text-xs px-3 py-1 data-[state=active]:bg-card data-[state=active]:shadow-sm">
            Metrics
          </TabsTrigger>
        </TabsList>

        {/* Tab: Overview */}
        <TabsContent value="overview" className="mt-3">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Left column */}
            <div className="flex flex-col gap-4">
              {/* Intent */}
              <div>
                <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold block mb-1">
                  Intent
                </span>
                <p className="text-xs text-foreground leading-relaxed">{action.intent}</p>
              </div>

              {/* Dependencies */}
              <div>
                <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold block mb-1.5">
                  Dependencies
                </span>
                <div className="flex gap-1.5 flex-wrap">
                  {action.deps.length === 0 ? (
                    <span className="text-xs text-muted-foreground italic">root action</span>
                  ) : (
                    action.deps.map((d) => (
                      <button
                        key={d}
                        onClick={() => onSelectAction(d)}
                        className="rounded-md bg-secondary px-2 py-0.5 text-xs font-mono text-[hsl(var(--primary))] hover:bg-[hsl(var(--primary))]/10 transition-colors"
                      >
                        {d}
                      </button>
                    ))
                  )}
                </div>
              </div>

              {/* Inputs */}
              {action.inputs.length > 0 && (
                <div>
                  <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold block mb-1.5">
                    Inputs
                  </span>
                  <div className="flex gap-1.5 flex-wrap">
                    {action.inputs.map((f) => (
                      <span key={f} className="rounded-md bg-blue-500/10 px-2 py-0.5 text-xs font-mono text-blue-400">
                        {f}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Outputs */}
              {action.outputs.length > 0 && (
                <div>
                  <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold block mb-1.5">
                    Outputs
                  </span>
                  <div className="flex gap-1.5 flex-wrap">
                    {action.outputs.map((f) => (
                      <span key={f} className="rounded-md bg-emerald-500/10 px-2 py-0.5 text-xs font-mono text-emerald-400">
                        {f}
                      </span>
                    ))}
                  </div>
                  {action.outputFields.length > 0 && (
                    <div className="mt-2 rounded-lg border border-border divide-y divide-border text-xs font-mono">
                      {action.outputFields.map((field) => (
                        <div key={field.name} className="flex items-center justify-between px-2.5 py-1.5">
                          <span className="text-foreground">{field.name}</span>
                          <span className="text-muted-foreground">{String(field.type)}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* Right column */}
            <div className="flex flex-col gap-4">
              {/* Implementation */}
              {action.type === "tool" && action.impl && (
                <div>
                  <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold block mb-1.5">
                    Implementation
                  </span>
                  <div className="rounded-lg border border-border bg-secondary/50 px-3 py-2">
                    <span className="text-xs font-mono text-[hsl(var(--success))]">{action.impl}()</span>
                  </div>
                </div>
              )}

              {/* Guard */}
              {action.guard && (
                <div>
                  <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold block mb-1.5">
                    Guard
                  </span>
                  <div className="rounded-lg bg-[hsl(var(--warning))]/5 border border-[hsl(var(--warning))]/15 px-3 py-2 font-mono text-xs text-[hsl(var(--warning))] leading-relaxed">
                    <div>condition: {action.guard.condition}</div>
                    <div className="mt-0.5">on_false: {action.guard.on_false}</div>
                  </div>
                </div>
              )}

              {/* Prompt preview */}
              {action.prompt && (
                <div>
                  <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold block mb-1.5">
                    Prompt Preview
                  </span>
                  <div className="rounded-lg bg-secondary/50 border border-border/50 px-3 py-2 font-mono text-xs text-muted-foreground leading-relaxed whitespace-pre-wrap max-h-48 overflow-auto">
                    {action.prompt}
                  </div>
                </div>
              )}
            </div>
          </div>
        </TabsContent>

        {/* Tab: Config */}
        <TabsContent value="config" className="mt-3">
          <div className="rounded-lg border border-border divide-y divide-border text-xs font-mono">
            {([
              ["Type", action.type],
              ["Workflow", action.wf],
              ["Schema", action.schema],
              ["Model", action.model],
              ["Provider", action.provider],
              ["Guard condition", action.guard?.condition],
              ["Guard on_false", action.guard?.on_false],
              ["Implementation", action.impl],
            ] as [string, string | null | undefined][])
              .filter(([, v]) => v != null && v !== "")
              .map(([label, value]) => (
                <div key={label} className="flex items-center justify-between px-3 py-2">
                  <span className="text-muted-foreground font-sans">{label}</span>
                  <span className="text-foreground">{value}</span>
                </div>
              ))}
          </div>
        </TabsContent>

        {/* Tab: Metrics */}
        <TabsContent value="metrics" className="mt-3">
          <div className="grid grid-cols-2 gap-3">
            <div className="rounded-lg border border-border bg-card px-3 py-2.5">
              <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold block mb-1">
                Execution Time
              </span>
              <span className="text-sm font-mono text-foreground">
                {action.metrics.execution_time != null ? `${action.metrics.execution_time}s` : "\u2014"}
              </span>
            </div>
            <div className="rounded-lg border border-border bg-card px-3 py-2.5">
              <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold block mb-1">
                Successes
              </span>
              <span className={`text-sm font-mono ${action.metrics.success_count > 0 ? "text-[hsl(var(--success))]" : "text-foreground"}`}>
                {action.metrics.success_count}
              </span>
            </div>
            <div className="rounded-lg border border-border bg-card px-3 py-2.5">
              <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold block mb-1">
                Failures
              </span>
              <span className={`text-sm font-mono ${action.metrics.failed_count > 0 ? "text-[hsl(var(--destructive))]" : "text-foreground"}`}>
                {action.metrics.failed_count}
              </span>
            </div>
            <div className="rounded-lg border border-border bg-card px-3 py-2.5">
              <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold block mb-1">
                Prompt Tokens
              </span>
              <span className="text-sm font-mono text-foreground">
                {action.metrics.tokens?.prompt_tokens != null ? action.metrics.tokens.prompt_tokens.toLocaleString() : "\u2014"}
              </span>
            </div>
            <div className="rounded-lg border border-border bg-card px-3 py-2.5 col-span-2 sm:col-span-1">
              <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold block mb-1">
                Completion Tokens
              </span>
              <span className="text-sm font-mono text-foreground">
                {action.metrics.tokens?.completion_tokens != null ? action.metrics.tokens.completion_tokens.toLocaleString() : "\u2014"}
              </span>
            </div>
          </div>
        </TabsContent>
      </Tabs>
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

function KV({ label, value, valueColor }: { label: string; value: string; valueColor?: string }) {
  return (
    <div className="flex items-center justify-between px-3 py-2">
      <span className="text-muted-foreground">{label}</span>
      <span className={valueColor || "text-foreground"}>{value}</span>
    </div>
  )
}
