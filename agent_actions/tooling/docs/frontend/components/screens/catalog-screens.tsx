"use client"

import React from "react"
import { useState } from "react"

import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { useCatalogData } from "@/lib/catalog-context"
import type { Prompt, ToolFunction, Schema } from "@/lib/mock-data"
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from "@/components/ui/collapsible"
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "@/components/ui/select"
import { MessageSquare, FileCode, Wrench, Code2, Search as SearchIcon, ArrowLeft, Variable, Zap, ChevronRight, FolderOpen, Copy, Check } from "lucide-react"

/* ------------------------------------------------------------------ */
/*  Shared copy-to-clipboard button                                    */
/* ------------------------------------------------------------------ */
function CopyButton({ text, className = "" }: { text: string; className?: string }) {
  const [copied, setCopied] = React.useState(false)
  const handleCopy = (e: React.MouseEvent) => {
    e.stopPropagation()
    navigator.clipboard.writeText(text).then(
      () => { setCopied(true); setTimeout(() => setCopied(false), 1500) },
      () => { /* clipboard permission denied or unavailable — silent no-op */ },
    )
  }
  return (
    <span
      role="button"
      tabIndex={0}
      onClick={handleCopy}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); handleCopy(e as unknown as React.MouseEvent) } }}
      className={`inline-flex items-center justify-center rounded-md p-1.5 transition-colors hover:bg-accent/40 cursor-pointer ${className}`}
      title="Copy to clipboard"
    >
      {copied ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5 text-muted-foreground" />}
    </span>
  )
}

/* ------------------------------------------------------------------ */
/*  Schema field-type color mapping                                    */
/* ------------------------------------------------------------------ */
function typeColor(t: unknown): string {
  if (typeof t !== "string") return "bg-secondary text-muted-foreground"
  const lower = t.toLowerCase()
  if (lower === "array") return "bg-blue-500/15 text-blue-300"
  if (lower === "number" || lower === "integer" || lower === "float") return "bg-amber-500/15 text-amber-300"
  if (lower === "object" || lower === "dict") return "bg-purple-500/15 text-purple-300"
  if (lower === "boolean" || lower === "bool") return "bg-rose-500/15 text-rose-300"
  return "bg-secondary text-muted-foreground" // string and everything else
}

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
            <div className="flex items-center gap-2">
              <span className="text-[10px] text-muted-foreground tabular-nums">{text.length.toLocaleString()} chars</span>
              <CopyButton text={text} />
            </div>
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
                        <td className="px-3 py-1.5"><span className={`rounded px-1 py-0.5 text-[10px] ${typeColor(schema.types[i])}`}>{schema.types[i]}</span></td>
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
                        <td className="px-3 py-1.5"><span className={`rounded px-1 py-0.5 ${typeColor(t)}`}>{t}</span></td>
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
              {schema.source && (
                <div className="flex justify-between px-3 py-2">
                  <span className="text-[10px] uppercase tracking-wider font-semibold text-muted-foreground">source</span>
                  <span className="text-foreground text-xs font-mono truncate ml-4" title={schema.source}>{schema.source.split("/").pop()}</span>
                </div>
              )}
              {schema.usedBy.length > 0 && (
                <div className="flex justify-between px-3 py-2">
                  <span className="text-[10px] uppercase tracking-wider font-semibold text-muted-foreground">used by</span>
                  <span className="text-foreground text-xs">{schema.usedBy.length} action{schema.usedBy.length !== 1 ? "s" : ""}</span>
                </div>
              )}
            </div>
            {/* Types breakdown — hide when only 1 unique type (redundant) */}
            {uniqueTypes.length > 1 && (
              <div className="mt-3">
                <h3 className="text-[10px] uppercase tracking-wider font-semibold text-muted-foreground mb-2">Types Breakdown</h3>
                <div className="flex gap-1.5 flex-wrap">
                  {uniqueTypes.map((t) => {
                    const count = schema.types.filter((st) => st === t).length
                    return (
                      <span
                        key={t}
                        className={`rounded-md px-2 py-0.5 text-[10px] font-mono ${typeColor(t)}`}
                      >
                        {t} <span className="text-foreground">&times;{count}</span>
                      </span>
                    )
                  })}
                </div>
              </div>
            )}
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

          {/* Used-by actions */}
          {schema.usedBy.length > 0 && (
            <div className="rounded-lg border border-border bg-card p-4">
              <h2 className="text-[10px] uppercase tracking-wider font-semibold text-muted-foreground mb-3">Used By</h2>
              <div className="space-y-1.5">
                {schema.usedBy.map((ref, i) => (
                  <div key={i} className="flex items-center gap-2 text-xs font-mono">
                    <Zap className="h-3 w-3 text-muted-foreground shrink-0" />
                    <span className="text-foreground">{ref.action}</span>
                    <span className="text-muted-foreground">in {ref.workflow}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Tool signature parser                                              */
/* ------------------------------------------------------------------ */
const sigSizeClass = { xs: "text-xs", sm: "text-sm" } as const

// Regex does not handle signatures with literal ")" inside parameter types
// (e.g. Callable[..., str] or default values containing ")"). Falls back to raw string.
function ParsedSignature({ sig, size = "xs" }: { sig: string; size?: "xs" | "sm" }) {
  const match = sig.match(/^def\s+(\w+)\(([^)]*)\)\s*(?:→|->)\s*(.+?):?\s*$/)
  if (!match) return <span className={`${sigSizeClass[size]} font-mono text-muted-foreground`}>{sig}</span>
  const [, name, params, ret] = match
  return (
    <span className={`${sigSizeClass[size]} font-mono leading-relaxed`}>
      <span className="text-muted-foreground/70">def </span>
      <span className="text-foreground font-medium">{name}</span>
      <span className="text-muted-foreground/70">(</span>
      <span className="text-muted-foreground">{params}</span>
      <span className="text-muted-foreground/70">)</span>
      <span className="text-muted-foreground/70"> &rarr; </span>
      <span className="text-[hsl(var(--primary))]">{ret.replace(/:$/, "")}</span>
    </span>
  )
}

/* ------------------------------------------------------------------ */
/*  ToolFunctionCard — single function in the grouped list             */
/* ------------------------------------------------------------------ */
function ToolFunctionCard({ tool, onSelect }: { tool: ToolFunction; onSelect: () => void }) {
  const borderColor = !tool.found
    ? "border-l-[hsl(var(--destructive))]"
    : "border-l-emerald-400"

  return (
    <button
      onClick={onSelect}
      className={`group relative w-full rounded-lg border border-border bg-card p-4 text-left
        border-l-[3px] ${borderColor}
        hover:bg-accent/30 hover:shadow-sm hover:translate-x-px
        transition-all duration-150`}
    >
      <div className="flex items-center gap-2 mb-1.5">
        <span className="text-sm font-mono font-semibold text-foreground group-hover:text-[hsl(var(--primary))] transition-colors truncate">
          {tool.name}
        </span>
        {!tool.found && (
          <Badge variant="outline" className="text-[10px] rounded-md bg-[hsl(var(--destructive))]/10 text-[hsl(var(--destructive))] border-[hsl(var(--destructive))]/20 px-1.5 py-0 shrink-0">
            NOT FOUND
          </Badge>
        )}
      </div>
      <div className="pr-6">
        <ParsedSignature sig={tool.sig} />
      </div>
      <ChevronRight className="absolute right-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground/30 group-hover:text-muted-foreground/60 transition-colors" />
    </button>
  )
}

/* ------------------------------------------------------------------ */
/*  Python syntax highlighting (zero-dependency tokenizer)             */
/* ------------------------------------------------------------------ */
type TokenType = "keyword" | "builtin" | "string" | "comment" | "decorator" | "number" | "defname" | "plain"

const PY_KEYWORDS = new Set([
  "False","None","True","and","as","assert","async","await","break","class",
  "continue","def","del","elif","else","except","finally","for","from","global",
  "if","import","in","is","lambda","nonlocal","not","or","pass","raise",
  "return","try","while","with","yield",
])
const PY_BUILTINS = new Set([
  "print","len","range","int","str","float","list","dict","set","tuple",
  "bool","type","isinstance","issubclass","hasattr","getattr","setattr",
  "enumerate","zip","map","filter","sorted","reversed","any","all","min","max",
  "sum","abs","round","open","super","property","staticmethod","classmethod",
  "ValueError","TypeError","KeyError","IndexError","AttributeError","RuntimeError",
  "Exception","StopIteration","NotImplementedError","OSError","IOError",
])

interface Token { type: TokenType; text: string }

function tokenizePythonLine(line: string, prevTriple: false | '"""' | "'''"): { tokens: Token[]; inTriple: false | '"""' | "'''" } {
  const tokens: Token[] = []
  let i = 0
  let tripleState = prevTriple

  const push = (type: TokenType, text: string) => { if (text) tokens.push({ type, text }) }

  // Continue a multi-line triple-quoted string
  if (tripleState) {
    const end = line.indexOf(tripleState)
    if (end === -1) { push("string", line); return { tokens, inTriple: tripleState } }
    push("string", line.slice(0, end + 3))
    i = end + 3
    tripleState = false
  }

  while (i < line.length) {
    const rest = line.slice(i)

    // String prefix literals (f"...", r"...", b"...", rb"...", etc.)
    const prefixMatch = rest.match(/^([fFrRbBuU]{1,2})(['"])/)
    if (prefixMatch) {
      const prefix = prefixMatch[1]
      const quote = prefixMatch[2]
      // Check if this is a triple-quoted prefixed string
      const afterPrefix = rest.slice(prefix.length)
      if (afterPrefix.startsWith('"""') || afterPrefix.startsWith("'''")) {
        const q = afterPrefix.startsWith('"""') ? '"""' : "'''" as const
        const end = line.indexOf(q, i + prefix.length + 3)
        if (end === -1) { push("string", line.slice(i)); return { tokens, inTriple: q } }
        push("string", line.slice(i, end + 3)); i = end + 3; continue
      }
      // Single-line prefixed string
      let j = i + prefix.length + 1
      while (j < line.length && line[j] !== quote) { if (line[j] === "\\") j++; j++ }
      push("string", line.slice(i, j + 1)); i = j + 1; continue
    }

    // Triple-quoted strings — check before single quotes to avoid partial match
    if (rest.startsWith('"""') || rest.startsWith("'''")) {
      const q = rest.startsWith('"""') ? '"""' : "'''" as const
      const end = line.indexOf(q, i + 3)
      if (end === -1) { push("string", line.slice(i)); return { tokens, inTriple: q } }
      push("string", line.slice(i, end + 3)); i = end + 3; continue
    }
    // Single/double quoted strings
    if (rest[0] === '"' || rest[0] === "'") {
      const quote = rest[0]; let j = i + 1
      while (j < line.length && line[j] !== quote) { if (line[j] === "\\") j++; j++ }
      push("string", line.slice(i, j + 1)); i = j + 1; continue
    }
    // Comments
    if (rest[0] === "#") { push("comment", line.slice(i)); break }
    // Decorators
    if (rest[0] === "@" && (i === 0 || /^\s*$/.test(line.slice(0, i)))) {
      push("decorator", line.slice(i)); break
    }
    // Numbers
    const numMatch = rest.match(/^(0[xX][\da-fA-F_]+|0[oO][0-7_]+|0[bB][01_]+|\d[\d_]*\.?\d*(?:e[+-]?\d+)?)/)
    if (numMatch && (i === 0 || /[\s([\{,:=<>!+\-*/]/.test(line[i - 1]))) {
      push("number", numMatch[0]); i += numMatch[0].length; continue
    }
    // Words (keywords, builtins, def names)
    const wordMatch = rest.match(/^[A-Za-z_]\w*/)
    if (wordMatch) {
      const w = wordMatch[0]
      if (PY_KEYWORDS.has(w)) {
        push("keyword", w)
        // Capture the name after def/class
        if ((w === "def" || w === "class") && i + w.length < line.length) {
          const after = line.slice(i + w.length).match(/^(\s+)([A-Za-z_]\w*)/)
          if (after) {
            push("plain", after[1]); push("defname", after[2]); i += w.length + after[0].length; continue
          }
        }
      } else if (PY_BUILTINS.has(w)) { push("builtin", w) }
      else { push("plain", w) }
      i += w.length; continue
    }
    // Whitespace and operators
    const wsMatch = rest.match(/^[^A-Za-z_'"#@\d]+/)
    if (wsMatch) { push("plain", wsMatch[0]); i += wsMatch[0].length; continue }
    push("plain", rest[0]); i++
  }
  return { tokens, inTriple: tripleState }
}

/* Editor-dark palette — always dark regardless of app theme */
const editorTokenColors: Record<TokenType, string> = {
  keyword: "text-[#c678dd] font-semibold",        /* soft purple */
  builtin: "text-[#61afef]",                       /* sky blue */
  string: "text-[#98c379]",                        /* muted green */
  comment: "text-[#5c6370] italic",                /* grey, italic */
  decorator: "text-[#e5c07b]",                     /* warm gold */
  number: "text-[#d19a66]",                        /* burnt orange */
  defname: "text-[#61afef] font-semibold",         /* blue, bold */
  plain: "text-[#abb2bf]",                         /* soft grey */
}

function HighlightedLine({ tokens }: { tokens: Token[] }) {
  return (
    <pre className="font-mono text-[13px] h-[22px] leading-[22px] whitespace-pre">
      {tokens.map((t, i) => (
        <span key={i} className={editorTokenColors[t.type]}>{t.text}</span>
      ))}
      {tokens.length === 0 && " "}
    </pre>
  )
}

/* ------------------------------------------------------------------ */
/*  ToolDetail — full-page view for a single tool function            */
/* ------------------------------------------------------------------ */
function SourceCodeBlock({ code, file }: { code: string; file: string }) {
  const highlighted = React.useMemo(() => {
    const rawLines = code.split("\n")
    let tripleState: false | '"""' | "'''" = false
    return rawLines.map((line) => {
      const result = tokenizePythonLine(line, tripleState)
      tripleState = result.inTriple
      return result.tokens
    })
  }, [code])

  const lineCount = highlighted.length
  const gutterWidth = lineCount >= 100 ? "w-12" : "w-10"

  return (
    <div className="rounded-xl border border-[#1e1e1e] overflow-hidden shadow-lg flex-1 flex flex-col min-h-0">
      {/* Title bar — mimics editor tab */}
      <div className="flex items-center justify-between px-4 py-2.5 bg-[#21252b] border-b border-[#181a1f]">
        <div className="flex items-center gap-2.5">
          <span className="text-[11px] font-mono font-medium text-[#9da5b4]">{file.split("/").pop()}</span>
          <span className="text-[10px] font-mono rounded bg-[#2c313a] px-1.5 py-0.5 text-[#636d83]">Python</span>
        </div>
        <span className="text-[10px] font-mono text-[#636d83] hidden sm:block">{file}</span>
      </div>
      {/* Code area — gutter is outside the horizontal scroll region */}
      <div className="flex max-h-[calc(100vh-12rem)] overflow-y-auto bg-[#282c34]">
        {/* Fixed gutter */}
        <div className={`shrink-0 ${gutterWidth} border-r border-[#2c313a] bg-[#282c34] select-none`}>
          {highlighted.map((_, i) => (
            <div key={i} className="px-3 text-right text-[13px] font-mono tabular-nums text-[#495162] h-[22px] leading-[22px]">
              {i + 1}
            </div>
          ))}
        </div>
        {/* Scrollable code */}
        <div className="flex-1 overflow-x-auto min-w-0">
          {highlighted.map((tokens, i) => (
            <div key={i} className="px-5 hover:bg-[#2c313a] transition-colors duration-75">
              <HighlightedLine tokens={tokens} />
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function ToolDetail({ tool, onBack }: { tool: ToolFunction; onBack: () => void }) {
  return (
    <div className="flex flex-col gap-4 min-h-[calc(100vh-7rem)]">
      <button
        onClick={onBack}
        className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors w-fit"
      >
        <ArrowLeft className="h-3.5 w-3.5" />
        Back to Tools
      </button>

      {/* Header */}
      <div>
        <div className="flex items-center gap-2 flex-wrap">
          <h1 className="text-xl font-semibold tracking-tight text-foreground font-mono">{tool.name}</h1>
          {!tool.found && (
            <Badge variant="outline" className="text-[10px] font-normal rounded-md bg-[hsl(var(--destructive))]/10 text-[hsl(var(--destructive))] border-[hsl(var(--destructive))]/20">
              NOT FOUND
            </Badge>
          )}
        </div>
        <p className="text-xs text-muted-foreground mt-0.5 font-mono">{tool.file}</p>
      </div>

      {/* Source code with line numbers — docstring is visible inside the source */}
      {tool.sourceCode ? (
        <SourceCodeBlock code={tool.sourceCode} file={tool.file} />
      ) : (
        <div className="rounded-lg border border-border bg-card p-4">
          <p className="text-xs text-muted-foreground mb-3">Source code not available</p>
          <div className="bg-secondary/50 rounded-lg border border-border p-4 overflow-auto whitespace-pre-wrap">
            <ParsedSignature sig={tool.sig} size="sm" />
          </div>
        </div>
      )}
    </div>
  )
}

/* ================================================================== */
/*  PromptsScreen                                                     */
/* ================================================================== */
export function PromptsScreen() {
  const { prompts, stats } = useCatalogData()
  const [selected, setSelected] = useState<Prompt | null>(null)
  const [search, setSearch] = useState("")
  const [sourceFilter, setSourceFilter] = useState<string | null>(null)
  const [lengthFilter, setLengthFilter] = useState<string | null>(null)

  const lowerSearch = search.toLowerCase()

  const sourceFiles = React.useMemo(
    () => [...new Set(prompts.map((p) => p.source))].sort(),
    [prompts],
  )
  const lengthCategories = React.useMemo(
    () => [...new Set(prompts.map((p) => p.length))].sort(),
    [prompts],
  )

  const filtered = React.useMemo(() => {
    return prompts.filter((p) => {
      if (sourceFilter && p.source !== sourceFilter) return false
      if (lengthFilter && p.length !== lengthFilter) return false
      if (!lowerSearch) return true
      return (
        p.name.toLowerCase().includes(lowerSearch) ||
        p.source.toLowerCase().includes(lowerSearch) ||
        p.preview.toLowerCase().includes(lowerSearch)
      )
    })
  }, [prompts, lowerSearch, sourceFilter, lengthFilter])

  if (selected) {
    return <PromptDetail prompt={selected} onBack={() => setSelected(null)} />
  }

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">Prompts</h1>
        <p className="text-sm text-muted-foreground mt-1">
          {lowerSearch || sourceFilter || lengthFilter
            ? `${filtered.length} of ${prompts.length} prompts`
            : `${prompts.length} prompt${prompts.length !== 1 ? "s" : ""}`}
        </p>
      </div>

      {/* Sticky search + filter bar */}
      <div className="sticky top-0 z-10 -mx-6 px-6 py-3 bg-background/80 backdrop-blur-sm">
        <div className="flex items-center gap-3 flex-wrap">
          <div className="relative flex-1 min-w-[200px]">
            <SearchIcon className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Search by name, source, or content..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-9 h-9 bg-secondary border-0 text-sm placeholder:text-muted-foreground"
            />
          </div>
          {/* Source file filter */}
          {sourceFiles.length > 1 && (
            <Select value={sourceFilter ?? "__all__"} onValueChange={(v) => setSourceFilter(v === "__all__" ? null : v)}>
              <SelectTrigger className="h-9 w-auto min-w-[160px] bg-secondary border-0 text-xs font-mono">
                <SelectValue placeholder="All sources" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="__all__">All sources</SelectItem>
                {sourceFiles.map((src) => (
                  <SelectItem key={src} value={src} className="text-xs font-mono">{src}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
          {/* Length category filter */}
          {lengthCategories.length > 1 && (
            <Select value={lengthFilter ?? "__all__"} onValueChange={(v) => setLengthFilter(v === "__all__" ? null : v)}>
              <SelectTrigger className="h-9 w-auto min-w-[120px] bg-secondary border-0 text-xs font-mono">
                <SelectValue placeholder="All lengths" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="__all__">All lengths</SelectItem>
                {lengthCategories.map((len) => (
                  <SelectItem key={len} value={len} className="text-xs font-mono">{len}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        {filtered.map((prompt) => (
          <button
            key={prompt.id}
            onClick={() => setSelected(prompt)}
            className="group relative overflow-hidden rounded-xl border border-border bg-card p-5 text-left hover:border-[hsl(var(--primary))]/20 transition-all flex flex-col"
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
              <CopyButton text={prompt.content || prompt.preview} className="opacity-0 group-hover:opacity-100 shrink-0" />
            </div>
            <p className="text-xs text-muted-foreground mt-3 leading-relaxed line-clamp-2">{prompt.preview}</p>
            {prompt.usedBy.length > 0 && (
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
            )}
            <div className="flex items-center gap-3 mt-auto pt-3 border-t border-border/50">
              <span className="text-[10px] text-muted-foreground">{prompt.length}</span>
              {prompt.usedBy.length > 0 && (
                <span className="text-[10px] text-muted-foreground">{prompt.usedBy.length} action{prompt.usedBy.length !== 1 ? "s" : ""}</span>
              )}
            </div>
          </button>
        ))}
      </div>

      {filtered.length === 0 && (
        <div className="flex flex-col items-center justify-center py-16 text-muted-foreground">
          <SearchIcon className="h-8 w-8 text-muted-foreground/20 mb-3" />
          <p className="text-sm">No prompts match the current filters</p>
          <p className="text-xs text-muted-foreground/60 mt-1">Try adjusting your search or filters</p>
        </div>
      )}
    </div>
  )
}

/* ================================================================== */
/*  SchemasScreen                                                     */
/* ================================================================== */
const SCHEMA_BADGE_LIMIT = 8

export function SchemasScreen() {
  const { schemas } = useCatalogData()
  const [selected, setSelected] = useState<Schema | null>(null)
  const [search, setSearch] = useState("")
  const [sourceFilter, setSourceFilter] = useState<string | null>(null)
  const [typeFilter, setTypeFilter] = useState<string | null>(null)
  const [usageFilter, setUsageFilter] = useState<string | null>(null)

  const lowerSearch = search.toLowerCase()

  const sourceFiles = React.useMemo(
    () => [...new Set(schemas.map((s) => s.source).filter(Boolean))].sort(),
    [schemas],
  )
  const allTypes = React.useMemo(
    () => [...new Set(schemas.flatMap((s) => s.types))].sort(),
    [schemas],
  )
  const allWorkflows = React.useMemo(
    () => [...new Set(schemas.flatMap((s) => s.usedBy.map((r) => r.workflow)).filter(Boolean))].sort(),
    [schemas],
  )

  const filtered = React.useMemo(() => {
    return schemas.filter((s) => {
      if (sourceFilter && s.source !== sourceFilter) return false
      if (typeFilter && !s.types.includes(typeFilter)) return false
      if (usageFilter === "__used__" && s.usedBy.length === 0) return false
      if (usageFilter === "__unused__" && s.usedBy.length > 0) return false
      const isWorkflowFilter = usageFilter && usageFilter !== "__used__" && usageFilter !== "__unused__"
      if (isWorkflowFilter && !s.usedBy.some((r) => r.workflow === usageFilter)) return false
      if (!lowerSearch) return true
      const fieldsStr = Array.isArray(s.fields) ? s.fields.join(" ").toLowerCase() : ""
      return (
        s.id.toLowerCase().includes(lowerSearch) ||
        fieldsStr.includes(lowerSearch) ||
        s.types.join(" ").toLowerCase().includes(lowerSearch)
      )
    })
  }, [schemas, lowerSearch, sourceFilter, typeFilter, usageFilter])

  if (selected) {
    return <SchemaDetail schema={selected} onBack={() => setSelected(null)} />
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">Schemas</h1>
        <p className="text-sm text-muted-foreground mt-1">{schemas.length} registered schemas</p>
      </div>

      {/* Search + filters */}
      <div className="sticky top-0 z-10 -mx-6 px-6 py-3 bg-background/80 backdrop-blur-sm border-b border-border/50">
        <div className="flex items-center gap-2 flex-wrap">
          <div className="relative flex-1 min-w-[200px]">
            <SearchIcon className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
            <Input
              placeholder="Search schemas, fields, types…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-9 h-9 bg-secondary border-0 text-xs"
            />
          </div>
          {sourceFiles.length > 1 && (
            <Select value={sourceFilter ?? "__all__"} onValueChange={(v) => setSourceFilter(v === "__all__" ? null : v)}>
              <SelectTrigger className="h-9 w-auto min-w-[160px] bg-secondary border-0 text-xs font-mono">
                <SelectValue placeholder="All sources" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="__all__">All sources</SelectItem>
                {sourceFiles.map((src) => (
                  <SelectItem key={src} value={src} className="text-xs font-mono">{src}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
          {allTypes.length > 1 && (
            <Select value={typeFilter ?? "__all__"} onValueChange={(v) => setTypeFilter(v === "__all__" ? null : v)}>
              <SelectTrigger className="h-9 w-auto min-w-[130px] bg-secondary border-0 text-xs">
                <SelectValue placeholder="All types" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="__all__">All types</SelectItem>
                {allTypes.map((t) => (
                  <SelectItem key={t} value={t} className="text-xs font-mono">{t}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
          <Select value={usageFilter ?? "__all__"} onValueChange={(v) => setUsageFilter(v === "__all__" ? null : v)}>
            <SelectTrigger className="h-9 w-auto min-w-[130px] bg-secondary border-0 text-xs">
              <SelectValue placeholder="Used by" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__all__">All schemas</SelectItem>
              <SelectItem value="__used__">Used by actions</SelectItem>
              <SelectItem value="__unused__">Unused</SelectItem>
              {allWorkflows.map((wf) => (
                <SelectItem key={wf} value={wf} className="text-xs font-mono">{wf}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        {(search || sourceFilter || typeFilter || usageFilter) && (
          <p className="text-[10px] text-muted-foreground mt-1.5">{filtered.length} of {schemas.length} schemas</p>
        )}
      </div>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
        {filtered.map((schema) => {
          const fieldCount = Array.isArray(schema.fields) ? schema.fields.length : schema.fields
          const badges = Array.isArray(schema.fields) ? schema.fields : []
          const truncated = badges.length > SCHEMA_BADGE_LIMIT
          const visibleBadges = truncated ? badges.slice(0, SCHEMA_BADGE_LIMIT) : badges
          const sourceBase = schema.source ? schema.source.split("/").pop() : null
          return (
            <button
              key={schema.id}
              onClick={() => setSelected(schema)}
              className="group relative overflow-hidden rounded-xl border border-border bg-card p-5 text-left hover:border-[hsl(var(--primary))]/20 transition-all flex flex-col"
            >
              <div className="absolute top-0 left-0 right-0 h-px bg-emerald-400 opacity-40" />
              <div className="flex items-start gap-3">
                <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-emerald-500/10 shrink-0">
                  <FileCode className="h-4 w-4 text-emerald-400" />
                </div>
                <div className="flex-1 min-w-0">
                  <h3 className="text-sm font-mono font-medium text-foreground truncate">{schema.id}</h3>
                  <span className="text-[10px] text-muted-foreground mt-0.5 block">{fieldCount} field{fieldCount !== 1 ? "s" : ""}</span>
                </div>
              </div>
              {visibleBadges.length > 0 && (
                <div className="flex gap-1.5 flex-wrap mt-3">
                  {visibleBadges.map((f, i) => (
                    <span key={i} className={`rounded-md px-1.5 py-0.5 text-[10px] font-mono ${typeColor(schema.types[i])}`}>
                      <span className="text-foreground">{f}</span>
                      <span className="ml-1 opacity-60">{schema.types[i]}</span>
                    </span>
                  ))}
                  {truncated && (
                    <span className="rounded-md bg-secondary px-1.5 py-0.5 text-[10px] font-mono text-muted-foreground">
                      +{badges.length - SCHEMA_BADGE_LIMIT} more
                    </span>
                  )}
                </div>
              )}
              {!Array.isArray(schema.fields) && schema.types.length > 0 && (
                <div className="flex gap-1.5 flex-wrap mt-3">
                  {schema.types.map((t, i) => (
                    <span key={i} className={`rounded-md px-1.5 py-0.5 text-[10px] font-mono ${typeColor(t)}`}>{t}</span>
                  ))}
                </div>
              )}
              {/* Footer — pinned to bottom */}
              <div className="flex items-center gap-3 mt-auto pt-3 border-t border-border/50">
                {sourceBase && <span className="text-[10px] text-muted-foreground font-mono truncate">{sourceBase}</span>}
                {schema.usedBy.length > 0 && (
                  <span className="text-[10px] text-muted-foreground">{schema.usedBy.length} action{schema.usedBy.length !== 1 ? "s" : ""}</span>
                )}
              </div>
            </button>
          )
        })}
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  FileGroupRow — collapsible file group in the tools list            */
/* ------------------------------------------------------------------ */
function FileGroupRow({
  file,
  tools,
  isOpen,
  onToggle,
  onSelectTool,
}: {
  file: string
  tools: ToolFunction[]
  isOpen: boolean
  onToggle: () => void
  onSelectTool: (tool: ToolFunction) => void
}) {
  const fileName = file.split("/").pop() || file

  return (
    <Collapsible open={isOpen} onOpenChange={onToggle}>
      <CollapsibleTrigger className="flex items-center gap-2 w-full rounded-lg px-3 py-2.5 text-left hover:bg-accent/40 transition-colors">
        <ChevronRight
          className={`h-3.5 w-3.5 text-muted-foreground shrink-0 transition-transform duration-200 ${
            isOpen ? "rotate-90" : ""
          }`}
        />
        <FileCode className="h-3.5 w-3.5 text-muted-foreground/60 shrink-0" />
        <span className="text-xs font-mono text-foreground font-medium truncate min-w-0">
          {fileName}
        </span>
        <span className="text-[10px] text-muted-foreground tabular-nums ml-auto shrink-0">
          {tools.length} tool{tools.length !== 1 ? "s" : ""}
        </span>
      </CollapsibleTrigger>
      <CollapsibleContent className="overflow-hidden data-[state=open]:animate-collapsible-down data-[state=closed]:animate-collapsible-up">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-2 pt-1.5 pb-3 pl-8 pr-1">
          {tools.map((tool) => (
            <ToolFunctionCard key={tool.name} tool={tool} onSelect={() => onSelectTool(tool)} />
          ))}
        </div>
      </CollapsibleContent>
    </Collapsible>
  )
}

/* ------------------------------------------------------------------ */
/*  DirectoryCard — card container for all files in a directory        */
/* ------------------------------------------------------------------ */
function DirectoryCard({
  dirPath,
  files,
  openGroups,
  lowerSearch,
  onToggle,
  onSelectTool,
}: {
  dirPath: string
  files: [string, ToolFunction[]][]
  openGroups: Set<string>
  lowerSearch: string
  onToggle: (key: string) => void
  onSelectTool: (tool: ToolFunction) => void
}) {
  const totalFns = files.reduce((sum, [, tools]) => sum + tools.length, 0)

  return (
    <div className="rounded-xl border border-border bg-card overflow-hidden">
      <div className="px-4 py-2.5 border-b border-border/50 bg-secondary/30 flex items-center gap-2">
        <FolderOpen className="h-3.5 w-3.5 text-muted-foreground/60 shrink-0" />
        <span className="text-xs font-mono font-semibold text-foreground truncate">{dirPath}</span>
        <span className="text-[10px] text-muted-foreground tabular-nums ml-auto shrink-0">{totalFns} tool{totalFns !== 1 ? "s" : ""}</span>
      </div>
      <div className="divide-y divide-border/30">
        {files.map(([file, tools]) => (
          <FileGroupRow
            key={file}
            file={file}
            tools={tools}
            isOpen={!!lowerSearch || openGroups.has(file)}
            onToggle={() => onToggle(file)}
            onSelectTool={onSelectTool}
          />
        ))}
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
  const [selected, setSelected] = useState<ToolFunction | null>(null)
  const [openGroups, setOpenGroups] = useState<Set<string>>(new Set())

  const lowerSearch = search.toLowerCase()
  const udfTools = React.useMemo(() => toolFunctions.filter((t) => t.udf), [toolFunctions])
  const filtered = React.useMemo(
    () => {
      if (!lowerSearch) return udfTools
      return udfTools.filter((t) =>
        t.name.toLowerCase().includes(lowerSearch) || t.sig.toLowerCase().includes(lowerSearch) || t.file.toLowerCase().includes(lowerSearch)
      )
    },
    [udfTools, lowerSearch]
  )

  /* Group filtered results by directory → file, sorted alphabetically */
  const dirGroups = React.useMemo(() => {
    const fileMap = new Map<string, ToolFunction[]>()
    for (const t of filtered) {
      const key = t.file || "unknown"
      if (!fileMap.has(key)) fileMap.set(key, [])
      fileMap.get(key)!.push(t)
    }
    const sortedFiles = [...fileMap.entries()].sort(([a], [b]) => a.localeCompare(b))
    const dirs = new Map<string, [string, ToolFunction[]][]>()
    for (const entry of sortedFiles) {
      const dir = entry[0].split("/").slice(0, -1).join("/") || "(top-level)"
      if (!dirs.has(dir)) dirs.set(dir, [])
      dirs.get(dir)!.push(entry)
    }
    return [...dirs.entries()].sort(([a], [b]) => a.localeCompare(b))
  }, [filtered])

  const totalFiles = dirGroups.reduce((sum, [, files]) => sum + files.length, 0)

  const toggleGroup = (key: string) => {
    setOpenGroups((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  if (selected) {
    return <ToolDetail tool={selected} onBack={() => setSelected(null)} />
  }

  return (
    <div className="flex flex-col gap-4">
      {/* Page header */}
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">Tools</h1>
        <p className="text-sm text-muted-foreground mt-1">
          {(() => {
            const total = lowerSearch ? udfTools.length : filtered.length
            const label = lowerSearch ? `${filtered.length} of ${total}` : `${total}`
            return `${label} UDF tool${total !== 1 ? "s" : ""}`
          })()}
          {totalFiles > 0 && <> &middot; {totalFiles} file{totalFiles !== 1 ? "s" : ""}</>}
        </p>
      </div>

      {/* Sticky search + filter bar — -mx-6 px-6 cancels parent px-6 to bleed edge-to-edge */}
      <div className="sticky top-0 z-10 -mx-6 px-6 py-3 bg-background/80 backdrop-blur-sm">
        <div className="flex items-center gap-3 flex-wrap">
          <div className="relative flex-1 min-w-[200px]">
            <SearchIcon className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Search by name, file, or signature..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-9 h-9 bg-secondary border-0 text-sm placeholder:text-muted-foreground"
            />
          </div>
        </div>
      </div>

      {/* Grouped results */}
      <div className="flex flex-col gap-4">
        {dirGroups.map(([dir, files]) => (
          <DirectoryCard
            key={dir}
            dirPath={dir}
            files={files}
            openGroups={openGroups}
            lowerSearch={lowerSearch}
            onToggle={toggleGroup}
            onSelectTool={setSelected}
          />
        ))}

        {filtered.length === 0 && (
          <div className="flex flex-col items-center justify-center py-16 text-muted-foreground">
            <SearchIcon className="h-8 w-8 text-muted-foreground/20 mb-3" />
            <p className="text-sm">No functions match the current filters</p>
            <p className="text-xs text-muted-foreground/60 mt-1">Try adjusting your search or filter</p>
          </div>
        )}
      </div>
    </div>
  )
}

