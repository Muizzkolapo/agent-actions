"use client"

import React from "react"
import { useState } from "react"

import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { useCatalogData } from "@/lib/catalog-context"
import type { Prompt, ToolFunction } from "@/lib/mock-data"
import { MessageSquare, FileCode, Wrench, Settings, Globe, Code2, Search as SearchIcon, Cpu, X } from "lucide-react"

/* ========== Prompts ========== */
export function PromptsScreen() {
  const { prompts, stats } = useCatalogData()
  const [selected, setSelected] = useState<Prompt | null>(null)

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">Prompts</h1>
        <p className="text-sm text-muted-foreground mt-1">
          {prompts.length} shown / {stats.total_prompts} total prompts
        </p>
      </div>

      <div className={`grid gap-4 ${selected ? "grid-cols-[1fr_400px]" : "grid-cols-1"}`}>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {prompts.map((prompt) => (
            <button
              key={prompt.id}
              onClick={() => setSelected(selected?.id === prompt.id ? null : prompt)}
              className={`group relative overflow-hidden rounded-xl border bg-card p-5 text-left hover:border-[hsl(var(--primary))]/20 transition-all ${
                selected?.id === prompt.id ? "border-[hsl(var(--primary))]/40" : "border-border"
              }`}
            >
              <div className="absolute top-0 left-0 right-0 h-px bg-purple-400 opacity-40" />
              <div className="flex items-start gap-3">
                <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-purple-500/10 shrink-0">
                  <MessageSquare className="h-4 w-4 text-purple-400" />
                </div>
                <div className="flex-1 min-w-0">
                  <h3 className="text-sm font-mono font-medium text-foreground">{prompt.name}</h3>
                  <span className="text-[10px] font-mono text-muted-foreground mt-0.5 block">{prompt.source}</span>
                </div>
              </div>
              <p className="text-xs text-muted-foreground mt-3 leading-relaxed line-clamp-2">{prompt.preview}</p>
              <div className="flex gap-1.5 mt-3 flex-wrap">
                {prompt.usedBy.map((u) => (
                  <span
                    key={u}
                    className="rounded-md bg-secondary px-1.5 py-0.5 text-[10px] font-mono text-[hsl(var(--primary))]"
                  >
                    {u}
                  </span>
                ))}
              </div>
              <div className="flex items-center gap-3 mt-3 pt-2.5 border-t border-border/50">
                <span className="text-[10px] text-muted-foreground">{prompt.length}</span>
                <span className="text-[10px] text-muted-foreground">{prompt.usedBy.length} actions</span>
              </div>
            </button>
          ))}
        </div>

        {selected && (
          <div className="rounded-xl border border-[hsl(var(--primary))]/30 bg-card overflow-hidden h-fit">
            <div className="flex items-center justify-between border-b border-border px-5 py-3.5">
              <span className="text-sm font-mono font-medium text-foreground">{selected.name}</span>
              <button onClick={() => setSelected(null)} className="text-muted-foreground hover:text-foreground">
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="p-5 flex flex-col gap-4">
              <div className="rounded-lg border border-border divide-y divide-border text-xs font-mono">
                <div className="flex justify-between px-3 py-2">
                  <span className="text-muted-foreground">source</span>
                  <span className="text-foreground">{selected.source}</span>
                </div>
                <div className="flex justify-between px-3 py-2">
                  <span className="text-muted-foreground">length</span>
                  <span className="text-foreground">{selected.length}</span>
                </div>
                <div className="flex justify-between px-3 py-2">
                  <span className="text-muted-foreground">used_by</span>
                  <span className="text-[hsl(var(--primary))]">{selected.usedBy.join(", ")}</span>
                </div>
              </div>
              <div>
                <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold block mb-2">Template Preview</span>
                <div className="rounded-lg bg-secondary/50 border border-border/50 p-3 font-mono text-xs text-muted-foreground leading-relaxed max-h-64 overflow-auto whitespace-pre-wrap">
                  {selected.preview}
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

/* ========== Schemas ========== */
export function SchemasScreen() {
  const { schemas } = useCatalogData()
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">Schemas</h1>
        <p className="text-sm text-muted-foreground mt-1">{schemas.length} registered schemas</p>
      </div>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
        {schemas.map((schema) => {
          const fieldCount = Array.isArray(schema.fields) ? schema.fields.length : schema.fields
          return (
            <div
              key={schema.id}
              className="group relative overflow-hidden rounded-xl border border-border bg-card p-5 hover:border-[hsl(var(--primary))]/20 transition-all"
            >
              <div className="absolute top-0 left-0 right-0 h-px bg-emerald-400 opacity-40" />
              <div className="flex items-start gap-3">
                <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-emerald-500/10 shrink-0">
                  <FileCode className="h-4 w-4 text-emerald-400" />
                </div>
                <div className="flex-1 min-w-0">
                  <h3 className="text-sm font-mono font-medium text-foreground">{schema.id}</h3>
                  <span className="text-[10px] text-muted-foreground mt-0.5 block">{fieldCount} fields</span>
                </div>
              </div>
              {Array.isArray(schema.fields) && (
                <div className="flex gap-1.5 flex-wrap mt-3">
                  {schema.fields.map((f, i) => (
                    <span
                      key={i}
                      className="rounded-md bg-secondary px-1.5 py-0.5 text-[10px] font-mono"
                    >
                      <span className="text-foreground">{f}</span>
                      <span className="text-muted-foreground ml-1">{schema.types[i]}</span>
                    </span>
                  ))}
                </div>
              )}
              {!Array.isArray(schema.fields) && (
                <div className="flex gap-1.5 flex-wrap mt-3">
                  {schema.types.map((t, i) => (
                    <span
                      key={i}
                      className="rounded-md bg-secondary px-1.5 py-0.5 text-[10px] font-mono text-muted-foreground"
                    >
                      {t}
                    </span>
                  ))}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

/* ========== Tools ========== */
export function ToolsScreen() {
  const { toolFunctions, stats } = useCatalogData()
  const [search, setSearch] = useState("")
  const [filter, setFilter] = useState<"all" | "udf" | "helper">("all")

  const filtered = toolFunctions.filter((t) => {
    if (filter === "udf" && !t.udf) return false
    if (filter === "helper" && t.udf) return false
    return t.name.includes(search) || t.sig.includes(search)
  })

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">Tool Functions</h1>
        <p className="text-sm text-muted-foreground mt-1">
          {stats.total_tool_functions} discovered &middot; showing {filtered.length} of {toolFunctions.length} loaded
        </p>
      </div>

      <div className="flex items-center gap-3 flex-wrap">
        <div className="relative flex-1 min-w-[200px]">
          <SearchIcon className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Filter functions..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9 h-9 bg-secondary border-0 text-sm placeholder:text-muted-foreground"
          />
        </div>
        <div className="flex gap-1">
          {(["all", "udf", "helper"] as const).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`rounded-lg px-2.5 py-1.5 text-xs font-medium capitalize transition-all ${
                filter === f
                  ? "bg-[hsl(var(--primary))]/15 text-[hsl(var(--primary))] ring-1 ring-[hsl(var(--primary))]/20"
                  : "text-muted-foreground hover:bg-accent hover:text-foreground"
              }`}
            >
              {f}
            </button>
          ))}
        </div>
      </div>

      <div className="rounded-xl border border-border bg-card overflow-hidden divide-y divide-border">
        {filtered.map((tool) => (
          <div key={tool.name} className="p-5 hover:bg-accent/20 transition-colors">
            <div className="flex items-center gap-2.5 mb-2">
              <span className="text-sm font-mono font-medium text-emerald-400">{tool.name}</span>
              {tool.udf && (
                <Badge variant="outline" className="text-[10px] font-normal rounded-md bg-emerald-500/10 text-emerald-400 border-emerald-500/20">
                  UDF
                </Badge>
              )}
              {!tool.found && (
                <Badge variant="outline" className="text-[10px] font-normal rounded-md bg-[hsl(var(--destructive))]/10 text-[hsl(var(--destructive))] border-[hsl(var(--destructive))]/20">
                  NOT FOUND
                </Badge>
              )}
            </div>
            <p className="text-xs font-mono text-muted-foreground leading-relaxed mb-1">{tool.sig}</p>
            <p className="text-[10px] font-mono text-muted-foreground/60">{tool.file}</p>
          </div>
        ))}
        {filtered.length === 0 && (
          <div className="flex items-center justify-center py-16 text-sm text-muted-foreground">
            No tools match the current filters
          </div>
        )}
      </div>
    </div>
  )
}

/* ========== Settings ========== */
export function SettingsScreen() {
  const { stats, generatedAt, workflows } = useCatalogData()

  // Derive real values from the catalog
  const generatorVersion = "1.1.0"
  const catalogGenerated = generatedAt
    ? new Date(generatedAt).toLocaleString()
    : "—"
  const totalActions = stats.total_actions
  const llmRatio = totalActions > 0
    ? `${stats.llm_actions} LLM / ${stats.tool_actions} tool`
    : "—"
  const defaultVendor = workflows.length > 0 && workflows[0].defaults?.model_vendor
    ? `${workflows[0].defaults.model_vendor}`
    : "—"
  const defaultModel = workflows.length > 0 && workflows[0].defaults?.model_name
    ? `${workflows[0].defaults.model_name}`
    : "—"

  const settings = [
    { label: "Generator Version", value: `v${generatorVersion}`, description: "Catalog generator version", icon: Cpu, accent: "hsl(var(--primary))" },
    { label: "Catalog Generated", value: catalogGenerated, description: "Last catalog build timestamp", icon: Settings, accent: "hsl(var(--chart-2))" },
    { label: "Workflows", value: String(stats.total_workflows), description: "Total registered workflows", icon: Globe, accent: "hsl(var(--success))" },
    { label: "Action Breakdown", value: llmRatio, description: `${totalActions} total actions`, icon: Wrench, accent: "hsl(var(--chart-5))" },
    { label: "Default Vendor", value: defaultVendor, description: "Workflow default LLM provider", icon: Globe, accent: "hsl(var(--warning))" },
    { label: "Default Model", value: defaultModel, description: "Workflow default model name", icon: Code2, accent: "hsl(var(--muted-foreground))" },
  ]

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">Settings</h1>
        <p className="text-sm text-muted-foreground mt-1">Catalog metadata and project configuration</p>
      </div>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        {settings.map((setting) => {
          const Icon = setting.icon
          return (
            <div key={setting.label} className="relative overflow-hidden rounded-xl border border-border bg-card p-5">
              <div className="absolute top-0 left-0 right-0 h-px" style={{ backgroundColor: setting.accent, opacity: 0.3 }} />
              <div className="flex items-start gap-3">
                <div
                  className="flex h-9 w-9 items-center justify-center rounded-lg shrink-0"
                  style={{ backgroundColor: `${setting.accent}15` }}
                >
                  <Icon className="h-4 w-4" style={{ color: setting.accent }} />
                </div>
                <div className="flex-1">
                  <span className="text-[10px] text-muted-foreground uppercase tracking-wider font-semibold">{setting.label}</span>
                  <p className="text-sm font-mono text-foreground mt-1">{setting.value}</p>
                  <p className="text-xs text-muted-foreground mt-0.5">{setting.description}</p>
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
