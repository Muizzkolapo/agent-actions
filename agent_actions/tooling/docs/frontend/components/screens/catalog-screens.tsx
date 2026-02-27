"use client"

import React from "react"
import { useState } from "react"

import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { useCatalogData } from "@/lib/catalog-context"
import type { Prompt, ToolFunction, Schema } from "@/lib/mock-data"
import { MessageSquare, FileCode, Wrench, Code2, Search as SearchIcon, ArrowLeft, Variable, Zap } from "lucide-react"

/* ------------------------------------------------------------------ */
/*  Prompt template analysis helpers                                   */
/* ------------------------------------------------------------------ */
function extractPromptAnalysis(content: string) {
  // Jinja2 variables: {{ var }}, {{ var.path }}, {{ var.path.deep }}
  const varRegex = /\{\{\s*([^}%]+?)\s*\}\}/g
  const rawVars: string[] = []
  let m: RegExpExecArray | null
  while ((m = varRegex.exec(content)) !== null) {
    rawVars.push(m[1].trim())
  }

  // Dispatch calls: dispatch_task('name') or dispatch_task("name")
  const dispatchRegex = /dispatch_task\s*\(\s*['"]([^'"]+)['"]\s*\)/g
  const dispatches: string[] = []
  while ((m = dispatchRegex.exec(content)) !== null) {
    dispatches.push(m[1])
  }

  // Jinja control blocks: {% if %}, {% for %}, {% set %}
  const blockRegex = /\{%[-\s]*(if|for|set|elif)\s+([^%]*?)\s*[-]?%\}/g
  const blocks: { type: string; expr: string }[] = []
  while ((m = blockRegex.exec(content)) !== null) {
    blocks.push({ type: m[1], expr: m[2].trim() })
  }

  // Clean variables: remove filters (|safe, |trim etc), function calls, dispatch expressions
  const variables = [...new Set(
    rawVars
      .map((v) => v.split("|")[0].trim()) // strip Jinja filters
      .filter((v) => !v.startsWith("dispatch_task") && !v.includes("(")) // exclude dispatch/function calls
      .filter((v) => v.length > 0)
  )]

  // Group by root (seed.x.y → seed)
  const roots = [...new Set(variables.map((v) => v.split(".")[0].split("[")[0]))]

  return { variables, roots, dispatches: [...new Set(dispatches)], blocks }
}

/* ------------------------------------------------------------------ */
/*  PromptDetail — full-page view for a single prompt                 */
/* ------------------------------------------------------------------ */
function PromptDetail({ prompt, onBack }: { prompt: Prompt; onBack: () => void }) {
  const text = prompt.content || prompt.preview
  const analysis = React.useMemo(() => extractPromptAnalysis(text), [text])
  const hasAnalysis = analysis.variables.length > 0 || analysis.dispatches.length > 0

  return (
    <div className="flex flex-col gap-4">
      {/* Back button */}
      <button
        onClick={onBack}
        className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors w-fit"
      >
        <ArrowLeft className="h-3.5 w-3.5" />
        Back to Prompts
      </button>

      {/* Header + metadata */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-foreground font-mono">{prompt.name}</h1>
          <p className="text-xs text-muted-foreground mt-0.5">
            {prompt.source} &middot; {prompt.length}
            {prompt.usedBy.length > 0 && (
              <> &middot; used by {prompt.usedBy.length} action{prompt.usedBy.length !== 1 ? "s" : ""}</>
            )}
            {analysis.variables.length > 0 && (
              <> &middot; {analysis.variables.length} variable{analysis.variables.length !== 1 ? "s" : ""}</>
            )}
            {analysis.dispatches.length > 0 && (
              <> &middot; {analysis.dispatches.length} dispatch{analysis.dispatches.length !== 1 ? "es" : ""}</>
            )}
          </p>
        </div>
        {prompt.usedBy.length > 0 && (
          <div className="flex gap-1.5 flex-wrap justify-end shrink-0">
            {prompt.usedBy.map((action) => (
              <Badge
                key={action}
                variant="outline"
                className="rounded-md bg-[hsl(var(--primary))]/10 text-[hsl(var(--primary))] border-[hsl(var(--primary))]/20 px-2 py-0.5 text-[10px] font-mono"
              >
                {action}
              </Badge>
            ))}
          </div>
        )}
      </div>

      {/* Two-column: template + analysis sidebar */}
      <div className={`grid grid-cols-1 gap-4 ${hasAnalysis ? "lg:grid-cols-[1fr_280px]" : ""}`}>
        {/* Full prompt content */}
        <div className="rounded-lg border border-border bg-card overflow-hidden">
          <div className="flex items-center justify-between border-b border-border px-4 py-2">
            <span className="text-xs font-semibold text-foreground">Prompt Template</span>
            <span className="text-[10px] text-muted-foreground tabular-nums">{text.length.toLocaleString()} chars</span>
          </div>
          <pre className="p-4 font-mono text-xs text-foreground/85 leading-relaxed whitespace-pre-wrap overflow-auto max-h-[600px]">
            {text}
          </pre>
        </div>

        {/* Analysis sidebar */}
        {hasAnalysis && (
          <div className="flex flex-col gap-3">
            {/* Variables */}
            {analysis.variables.length > 0 && (
              <div className="rounded-lg border border-border bg-card overflow-hidden">
                <div className="flex items-center gap-2 border-b border-border px-3 py-2">
                  <Variable className="h-3.5 w-3.5 text-[hsl(var(--primary))]" />
                  <span className="text-xs font-semibold text-foreground">Variables</span>
                  <span className="text-[10px] text-muted-foreground ml-auto tabular-nums">{analysis.variables.length}</span>
                </div>
                <div className="divide-y divide-border/50 max-h-[320px] overflow-y-auto">
                  {analysis.roots.map((root) => {
                    const paths = analysis.variables.filter((v) => v.split(".")[0].split("[")[0] === root)
                    return (
                      <div key={root} className="px-3 py-2">
                        <span className="text-[10px] uppercase tracking-wider font-semibold text-muted-foreground">{root}</span>
                        <div className="mt-1 flex flex-col gap-0.5">
                          {paths.map((p) => (
                            <span key={p} className="text-[11px] font-mono text-[hsl(var(--primary))] truncate" title={p}>
                              {p}
                            </span>
                          ))}
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            )}

            {/* Dispatch calls */}
            {analysis.dispatches.length > 0 && (
              <div className="rounded-lg border border-border bg-card overflow-hidden">
                <div className="flex items-center gap-2 border-b border-border px-3 py-2">
                  <Zap className="h-3.5 w-3.5 text-[hsl(var(--warning))]" />
                  <span className="text-xs font-semibold text-foreground">Dispatch Calls</span>
                  <span className="text-[10px] text-muted-foreground ml-auto tabular-nums">{analysis.dispatches.length}</span>
                </div>
                <div className="divide-y divide-border/50">
                  {analysis.dispatches.map((d) => (
                    <div key={d} className="px-3 py-2">
                      <span className="text-[11px] font-mono text-[hsl(var(--warning))]">dispatch_task</span>
                      <span className="text-[11px] font-mono text-muted-foreground">(</span>
                      <span className="text-[11px] font-mono text-foreground">&apos;{d}&apos;</span>
                      <span className="text-[11px] font-mono text-muted-foreground">)</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Control flow blocks */}
            {analysis.blocks.length > 0 && (
              <div className="rounded-lg border border-border bg-card overflow-hidden">
                <div className="flex items-center gap-2 border-b border-border px-3 py-2">
                  <Code2 className="h-3.5 w-3.5 text-[hsl(var(--chart-2))]" />
                  <span className="text-xs font-semibold text-foreground">Control Flow</span>
                  <span className="text-[10px] text-muted-foreground ml-auto tabular-nums">{analysis.blocks.length}</span>
                </div>
                <div className="divide-y divide-border/50 max-h-[200px] overflow-y-auto">
                  {analysis.blocks.map((b, i) => (
                    <div key={i} className="px-3 py-2 flex items-baseline gap-2">
                      <Badge variant="secondary" className="text-[10px] font-mono rounded px-1.5 py-0 shrink-0">
                        {b.type}
                      </Badge>
                      <span className="text-[11px] font-mono text-muted-foreground truncate" title={b.expr}>
                        {b.expr}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  SchemaDetail — full-page view for a single schema                 */
/* ------------------------------------------------------------------ */
function SchemaDetail({ schema, onBack }: { schema: Schema; onBack: () => void }) {
  const fieldCount = Array.isArray(schema.fields) ? schema.fields.length : schema.fields
  const uniqueTypes = [...new Set(schema.types)]

  return (
    <div className="flex flex-col gap-4">
      {/* Back button */}
      <button
        onClick={onBack}
        className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors w-fit"
      >
        <ArrowLeft className="h-3.5 w-3.5" />
        Back to Schemas
      </button>

      {/* Two-column layout */}
      <div className="grid grid-cols-1 lg:grid-cols-[55%_45%] gap-4">
        {/* Left column */}
        <div className="flex flex-col gap-4">
          {/* Heading */}
          <div>
            <h1 className="text-xl font-semibold tracking-tight text-foreground font-mono">{schema.id}</h1>
            <p className="text-xs text-muted-foreground mt-0.5">{fieldCount} field{fieldCount !== 1 ? "s" : ""}</p>
          </div>

          {/* Fields table */}
          <div>
            <h2 className="text-[10px] uppercase tracking-wider font-semibold text-muted-foreground mb-2">Fields</h2>
            {Array.isArray(schema.fields) ? (
              <div className="rounded-lg border border-border overflow-hidden">
                <table className="w-full text-xs font-mono">
                  <thead>
                    <tr className="border-b border-border bg-secondary/50">
                      <th className="text-left px-3 py-2 text-[10px] uppercase tracking-wider text-muted-foreground font-semibold w-10">#</th>
                      <th className="text-left px-3 py-2 text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">Field</th>
                      <th className="text-left px-3 py-2 text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">Type</th>
                    </tr>
                  </thead>
                  <tbody>
                    {schema.fields.map((field, i) => (
                      <tr key={i} className={`hover:bg-accent/20 transition-colors ${i % 2 === 1 ? "bg-secondary/20" : ""}`}>
                        <td className="px-3 py-1.5 text-muted-foreground text-[10px]">{i + 1}</td>
                        <td className="px-3 py-1.5 text-foreground">{field}</td>
                        <td className="px-3 py-1.5 text-muted-foreground">{schema.types[i]}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="rounded-lg border border-border overflow-hidden">
                <table className="w-full text-xs font-mono">
                  <thead>
                    <tr className="border-b border-border bg-secondary/50">
                      <th className="text-left px-3 py-2 text-[10px] uppercase tracking-wider text-muted-foreground font-semibold w-10">#</th>
                      <th className="text-left px-3 py-2 text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">Type</th>
                    </tr>
                  </thead>
                  <tbody>
                    {schema.types.map((t, i) => (
                      <tr key={i} className={`hover:bg-accent/20 transition-colors ${i % 2 === 1 ? "bg-secondary/20" : ""}`}>
                        <td className="px-3 py-1.5 text-muted-foreground text-[10px]">{i + 1}</td>
                        <td className="px-3 py-1.5 text-foreground">{t}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>

        {/* Right column */}
        <div className="flex flex-col gap-4">
          {/* Summary card */}
          <div className="rounded-lg border border-border bg-card p-4">
            <h2 className="text-[10px] uppercase tracking-wider font-semibold text-muted-foreground mb-3">Summary</h2>
            <div className="rounded-lg border border-border divide-y divide-border text-sm font-mono">
              <div className="flex justify-between px-3 py-2">
                <span className="text-[10px] uppercase tracking-wider font-semibold text-muted-foreground">total fields</span>
                <span className="text-foreground text-xs">{fieldCount}</span>
              </div>
              <div className="flex justify-between px-3 py-2">
                <span className="text-[10px] uppercase tracking-wider font-semibold text-muted-foreground">unique types</span>
                <span className="text-foreground text-xs">{uniqueTypes.length}</span>
              </div>
            </div>
            {/* Types breakdown */}
            <div className="mt-3">
              <h3 className="text-[10px] uppercase tracking-wider font-semibold text-muted-foreground mb-2">Types Breakdown</h3>
              <div className="flex gap-1.5 flex-wrap">
                {uniqueTypes.map((t) => {
                  const count = schema.types.filter((st) => st === t).length
                  return (
                    <span
                      key={t}
                      className="rounded-md bg-secondary px-2 py-0.5 text-[10px] font-mono text-muted-foreground"
                    >
                      {t} <span className="text-foreground">&times;{count}</span>
                    </span>
                  )
                })}
              </div>
            </div>
          </div>

          {/* Numeric-only info */}
          {!Array.isArray(schema.fields) && (
            <div className="rounded-lg border border-border bg-card p-4">
              <h2 className="text-[10px] uppercase tracking-wider font-semibold text-muted-foreground mb-3">Note</h2>
              <p className="text-xs text-muted-foreground leading-relaxed">
                This schema has <span className="text-foreground font-mono">{fieldCount}</span> fields (numeric count only; field names are not available).
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  ToolDetail — full-page view for a single tool function            */
/* ------------------------------------------------------------------ */
function ToolDetail({ tool, onBack }: { tool: ToolFunction; onBack: () => void }) {
  return (
    <div className="flex flex-col gap-4">
      {/* Back button */}
      <button
        onClick={onBack}
        className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors w-fit"
      >
        <ArrowLeft className="h-3.5 w-3.5" />
        Back to Tool Functions
      </button>

      {/* Two-column layout */}
      <div className="grid grid-cols-1 lg:grid-cols-[55%_45%] gap-4">
        {/* Left column */}
        <div className="flex flex-col gap-4">
          {/* Heading + badges */}
          <div className="flex items-center gap-2 flex-wrap">
            <h1 className="text-xl font-semibold tracking-tight text-foreground font-mono">{tool.name}</h1>
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

          {/* Signature */}
          <div>
            <h2 className="text-[10px] uppercase tracking-wider font-semibold text-muted-foreground mb-2">Signature</h2>
            <pre className="bg-secondary/50 rounded-lg border border-border p-4 font-mono text-xs text-muted-foreground leading-relaxed overflow-auto whitespace-pre-wrap">
              {tool.sig}
            </pre>
          </div>
        </div>

        {/* Right column */}
        <div className="flex flex-col gap-4">
          {/* Details card */}
          <div className="rounded-lg border border-border bg-card p-4">
            <h2 className="text-[10px] uppercase tracking-wider font-semibold text-muted-foreground mb-3">Details</h2>
            <div className="rounded-lg border border-border divide-y divide-border text-sm font-mono">
              <div className="flex justify-between px-3 py-2">
                <span className="text-[10px] uppercase tracking-wider font-semibold text-muted-foreground">name</span>
                <span className="text-foreground text-xs">{tool.name}</span>
              </div>
              <div className="flex justify-between px-3 py-2">
                <span className="text-[10px] uppercase tracking-wider font-semibold text-muted-foreground">udf</span>
                <span className={`text-xs ${tool.udf ? "text-emerald-400" : "text-muted-foreground"}`}>
                  {tool.udf ? "Yes" : "No"}
                </span>
              </div>
              <div className="flex justify-between px-3 py-2">
                <span className="text-[10px] uppercase tracking-wider font-semibold text-muted-foreground">found</span>
                <span className={`text-xs ${tool.found ? "text-emerald-400" : "text-[hsl(var(--destructive))]"}`}>
                  {tool.found ? "Yes" : "No"}
                </span>
              </div>
              <div className="flex justify-between px-3 py-2 gap-3">
                <span className="text-[10px] uppercase tracking-wider font-semibold text-muted-foreground shrink-0">file</span>
                <span className="text-foreground text-xs break-all text-right">{tool.file}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

/* ================================================================== */
/*  PromptsScreen                                                     */
/* ================================================================== */
export function PromptsScreen() {
  const { prompts, stats } = useCatalogData()
  const [selected, setSelected] = useState<Prompt | null>(null)

  if (selected) {
    return <PromptDetail prompt={selected} onBack={() => setSelected(null)} />
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">Prompts</h1>
        <p className="text-sm text-muted-foreground mt-1">
          {prompts.length} shown / {stats.total_prompts} total prompts
        </p>
      </div>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        {prompts.map((prompt) => (
          <button
            key={prompt.id}
            onClick={() => setSelected(prompt)}
            className="group relative overflow-hidden rounded-xl border border-border bg-card p-5 text-left hover:border-[hsl(var(--primary))]/20 transition-all"
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
    </div>
  )
}

/* ================================================================== */
/*  SchemasScreen                                                     */
/* ================================================================== */
export function SchemasScreen() {
  const { schemas } = useCatalogData()
  const [selected, setSelected] = useState<Schema | null>(null)

  if (selected) {
    return <SchemaDetail schema={selected} onBack={() => setSelected(null)} />
  }

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
            <button
              key={schema.id}
              onClick={() => setSelected(schema)}
              className="group relative overflow-hidden rounded-xl border border-border bg-card p-5 text-left hover:border-[hsl(var(--primary))]/20 transition-all"
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
            </button>
          )
        })}
      </div>
    </div>
  )
}

/* ================================================================== */
/*  ToolsScreen                                                       */
/* ================================================================== */
export function ToolsScreen() {
  const { toolFunctions, stats } = useCatalogData()
  const [search, setSearch] = useState("")
  const [filter, setFilter] = useState<"all" | "udf" | "helper">("all")
  const [selected, setSelected] = useState<ToolFunction | null>(null)

  const filtered = toolFunctions.filter((t) => {
    if (filter === "udf" && !t.udf) return false
    if (filter === "helper" && t.udf) return false
    return t.name.includes(search) || t.sig.includes(search)
  })

  if (selected) {
    return <ToolDetail tool={selected} onBack={() => setSelected(null)} />
  }

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
          <button
            key={tool.name}
            onClick={() => setSelected(tool)}
            className="w-full p-5 text-left hover:bg-accent/20 transition-colors"
          >
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
          </button>
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

