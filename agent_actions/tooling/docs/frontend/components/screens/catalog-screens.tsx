"use client"

import { useMemo, useState } from "react"
import { Check, Copy } from "lucide-react"
import { useCatalogData } from "@/lib/catalog-context"
import { PageTitle, SearchInput, EmptyState, fieldTypeToken } from "@/components/graphite"
import type { Prompt, Schema, ToolFunction } from "@/lib/mock-data"

const PANE =
  "grid gap-4 md:grid-cols-[minmax(190px,248px)_minmax(0,1fr)] md:h-[clamp(420px,calc(100vh-15rem),860px)]"
const LIST = "flex min-h-0 flex-col overflow-hidden rounded-card border border-border bg-surface"
const DETAIL = "min-h-0 overflow-y-auto rounded-card border border-border bg-surface p-5"

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <button
      onClick={() => {
        navigator.clipboard.writeText(text).then(
          () => { setCopied(true); setTimeout(() => setCopied(false), 1500) },
          () => { /* clipboard unavailable */ },
        )
      }}
      title="Copy to clipboard"
      aria-label="Copy to clipboard"
      className="flex h-6 w-6 items-center justify-center rounded-control text-muted-foreground hover:bg-hover hover:text-foreground"
    >
      {copied ? <Check className="h-3.5 w-3.5 text-success-t" /> : <Copy className="h-3.5 w-3.5" />}
    </button>
  )
}

function UsedBy({ refs }: { refs: { workflow: string; action: string }[] }) {
  if (refs.length === 0) {
    return (
      <p className="m-0 text-[11.5px] text-muted-foreground">
        Not referenced by any action in the loaded configs.
      </p>
    )
  }
  return (
    <div className="flex flex-wrap gap-1.5">
      {refs.map((r, i) => (
        <span
          key={`${r.workflow}/${r.action}-${i}`}
          className="whitespace-nowrap rounded-control border border-border bg-surface-2 px-2 py-1 font-mono text-[10.5px] text-foreground-2"
        >
          {r.action}
          <span className="text-muted-foreground"> in {r.workflow}</span>
        </span>
      ))}
    </div>
  )
}

/* ================================================================== */
/*  Schemas                                                           */
/* ================================================================== */

export function SchemasScreen() {
  const { schemas } = useCatalogData()
  const [search, setSearch] = useState("")
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return schemas
    return schemas.filter((s) => {
      const fields = Array.isArray(s.fields) ? s.fields.join(" ") : ""
      return `${s.id} ${fields} ${s.types.join(" ")} ${s.source}`.toLowerCase().includes(q)
    })
  }, [schemas, search])

  const selected = filtered.find((s) => s.id === selectedId) ?? filtered[0] ?? null

  return (
    <div className="flex animate-view-in flex-col gap-3.5">
      <PageTitle title="Schemas" subtitle={`${schemas.length} schemas · showing ${filtered.length}`} />
      <div className={PANE}>
        <div className={LIST}>
          <div className="border-b border-border p-3">
            <SearchInput value={search} onChange={setSearch} placeholder="Search schemas…" />
          </div>
          <div className="flex-1 overflow-y-auto">
            {filtered.map((s) => (
              <SchemaRow
                key={s.id}
                schema={s}
                active={selected?.id === s.id}
                onClick={() => setSelectedId(s.id)}
              />
            ))}
            {filtered.length === 0 && <EmptyState message="No schemas match this search" />}
          </div>
        </div>
        <div className={DETAIL}>
          {selected ? <SchemaDetail schema={selected} /> : <EmptyState message="No schemas in this catalog." />}
        </div>
      </div>
    </div>
  )
}

function typeDistribution(types: string[]) {
  const counts = new Map<string, number>()
  for (const t of types) counts.set(t, (counts.get(t) ?? 0) + 1)
  return [...counts.entries()].sort((a, b) => b[1] - a[1])
}

function SchemaRow({ schema, active, onClick }: { schema: Schema; active: boolean; onClick: () => void }) {
  const count = Array.isArray(schema.fields) ? schema.fields.length : schema.fields
  const segments = typeDistribution(schema.types)
  return (
    <button
      onClick={onClick}
      className={`block w-full border-b border-border-soft px-3.5 py-2.5 text-left hover:bg-hover ${
        active ? "bg-accent-a12" : ""
      }`}
    >
      <div className="flex items-baseline justify-between gap-2">
        <span className={`min-w-0 truncate font-mono text-[12.5px] font-medium ${active ? "text-accent-t" : "text-foreground"}`}>
          {schema.id}
        </span>
        <span className="shrink-0 text-[10px] text-muted-foreground">
          {count} field{count === 1 ? "" : "s"}
        </span>
      </div>
      {segments.length > 0 && (
        <div className="mt-[7px] flex h-[3px] gap-0.5 overflow-hidden rounded-sm">
          {segments.map(([type, n]) => (
            <div key={type} title={`${n} ${type}`} className={`h-full ${fieldTypeToken(type).fill}`} style={{ flex: n }} />
          ))}
        </div>
      )}
    </button>
  )
}

function SchemaDetail({ schema }: { schema: Schema }) {
  const count = Array.isArray(schema.fields) ? schema.fields.length : schema.fields
  const names = Array.isArray(schema.fields) ? schema.fields : null

  return (
    <div className="flex flex-col gap-4">
      <div>
        <div className="font-mono text-base font-semibold">{schema.id}</div>
        <div className="mt-1 text-[11.5px] text-muted-foreground">
          {count} field{count === 1 ? "" : "s"}
          {schema.source ? ` · ${schema.source.split("/").pop()}` : ""}
        </div>
      </div>

      <div className="overflow-hidden rounded-card border border-border">
        <div className="grid grid-cols-[32px_minmax(0,1fr)_auto] gap-3 bg-surface-2 px-4 py-2 text-xs font-medium text-muted-foreground">
          <span>#</span>
          <span>Field</span>
          <span>Type</span>
        </div>
        {(names ?? schema.types).map((value, i) => {
          const type = schema.types[i] ?? "unknown"
          return (
            <div
              key={`${value}-${i}`}
              className="grid grid-cols-[32px_minmax(0,1fr)_auto] items-center gap-3 border-t border-border-soft px-4 py-2.5"
            >
              <span className="font-mono text-[11.5px] text-muted-foreground">{i + 1}</span>
              <span className="truncate font-mono text-[12.5px]">{names ? value : type}</span>
              <span className={`font-mono text-[11px] ${fieldTypeToken(type).text}`}>{type}</span>
            </div>
          )
        })}
        {count === 0 && <EmptyState message="This schema declares no fields." />}
      </div>

      {!names && count > 0 && (
        <p className="m-0 text-[11.5px] leading-relaxed text-muted-foreground">
          The catalog recorded a field count for this schema but not field names.
        </p>
      )}

      <div className="flex flex-col gap-2">
        <div className="text-xs font-medium text-muted-foreground">Used by</div>
        <UsedBy refs={schema.usedBy} />
      </div>
    </div>
  )
}

/* ================================================================== */
/*  Prompts                                                           */
/* ================================================================== */

/**
 * A split on `{{…}}` / `{%…%}` — not a Jinja parser. Real templates go through
 * Jinja2, so filters, nested expressions and {# comments #} need a real tokenizer.
 */
function tokenizeTemplate(text: string) {
  return text
    .split(/(\{\{[^}]*\}\}|\{%[^%]*%\})/g)
    .filter((part) => part.length > 0)
    .map((part, i) => ({
      key: i,
      text: part,
      className: part.startsWith("{{")
        ? "text-accent-bright"
        : part.startsWith("{%")
          ? "text-warning-t"
          : "text-foreground-3",
    }))
}

function analyzeTemplate(content: string) {
  const variables = new Set<string>()
  const dispatches = new Set<string>()
  const blocks: { type: string; expr: string }[] = []

  const varRegex = /\{\{\s*([^}%]+?)\s*\}\}/g
  let m: RegExpExecArray | null
  while ((m = varRegex.exec(content)) !== null) {
    const raw = m[1].split("|")[0].trim()
    if (raw && !raw.startsWith("dispatch_task") && !raw.includes("(")) variables.add(raw)
  }

  const dispatchRegex = /dispatch_task\s*\(\s*['"]([^'"]+)['"]\s*\)/g
  while ((m = dispatchRegex.exec(content)) !== null) dispatches.add(m[1])

  const blockRegex = /\{%[-\s]*(if|for|set|elif)\s+([^%]*?)\s*[-]?%\}/g
  while ((m = blockRegex.exec(content)) !== null) blocks.push({ type: m[1], expr: m[2].trim() })

  return { variables: [...variables], dispatches: [...dispatches], blocks }
}

export function PromptsScreen() {
  const { prompts } = useCatalogData()
  const [search, setSearch] = useState("")
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return prompts
    return prompts.filter((p) => `${p.name} ${p.source} ${p.preview}`.toLowerCase().includes(q))
  }, [prompts, search])

  const selected = filtered.find((p) => p.id === selectedId) ?? filtered[0] ?? null

  return (
    <div className="flex animate-view-in flex-col gap-3.5">
      <PageTitle title="Prompts" subtitle={`${prompts.length} prompts · showing ${filtered.length}`} />
      <div className={PANE}>
        <div className={LIST}>
          <div className="border-b border-border p-3">
            <SearchInput value={search} onChange={setSearch} placeholder="Search prompts…" />
          </div>
          <div className="flex-1 overflow-y-auto">
            {filtered.map((p) => {
              const vars = analyzeTemplate(p.content || p.preview).variables.length
              const active = selected?.id === p.id
              return (
                <button
                  key={p.id}
                  onClick={() => setSelectedId(p.id)}
                  className={`block w-full border-b border-border-soft px-3.5 py-2.5 text-left hover:bg-hover ${
                    active ? "bg-accent-a12" : ""
                  }`}
                >
                  <div className={`truncate font-mono text-[12.5px] font-medium ${active ? "text-accent-t" : "text-foreground"}`}>
                    {p.name}
                  </div>
                  <div className="mt-[3px] truncate text-[10.5px] text-muted-foreground">
                    {p.source} · {vars} var{vars === 1 ? "" : "s"}
                  </div>
                </button>
              )
            })}
            {filtered.length === 0 && <EmptyState message="No prompts match this search" />}
          </div>
        </div>
        <div className={DETAIL}>
          {selected ? <PromptDetail prompt={selected} /> : <EmptyState message="No prompts in this catalog." />}
        </div>
      </div>
    </div>
  )
}

function PromptDetail({ prompt }: { prompt: Prompt }) {
  const text = prompt.content || prompt.preview
  const analysis = useMemo(() => analyzeTemplate(text), [text])
  const tokens = useMemo(() => tokenizeTemplate(text), [text])

  return (
    <div className="flex flex-col gap-3.5">
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="font-mono text-base font-semibold">{prompt.name}</div>
          <div className="mt-1 text-[11.5px] text-muted-foreground">
            {prompt.source} · {prompt.length} · {text.length.toLocaleString()} chars ·{" "}
            {analysis.variables.length} variable{analysis.variables.length === 1 ? "" : "s"}
          </div>
        </div>
        <CopyButton text={text} />
      </div>

      <div className="shrink-0 overflow-x-auto rounded-card border border-border bg-well px-[17px] py-4">
        <div className="whitespace-pre-wrap break-normal font-mono text-xs leading-[1.75]">
          {tokens.map((t) => (
            <span key={t.key} className={t.className}>{t.text}</span>
          ))}
        </div>
      </div>

      <div className="flex shrink-0 flex-wrap gap-3">
        <div className="min-w-[220px] flex-1 rounded-card border border-border bg-surface-2 px-4 py-3">
          <div className="mb-2 text-xs font-medium text-muted-foreground">Variables</div>
          <div className="flex min-w-0 flex-col gap-1.5 overflow-x-auto">
            {analysis.variables.map((v) => (
              <div key={v} className="whitespace-nowrap font-mono text-[11px] text-accent-t">{v}</div>
            ))}
            {analysis.variables.length === 0 && (
              <div className="text-[11px] text-muted-foreground">This template takes no variables.</div>
            )}
          </div>
        </div>

        {analysis.blocks.length > 0 && (
          <div className="min-w-[220px] flex-1 rounded-card border border-border bg-surface-2 px-4 py-3">
            <div className="mb-2 text-xs font-medium text-muted-foreground">Control flow</div>
            <div className="min-w-0 overflow-x-auto">
              {analysis.blocks.map((b, i) => (
                <div key={i} className="flex gap-2 whitespace-nowrap py-1 font-mono text-[11px]">
                  <span className="text-warning-t">{b.type}</span>
                  <span className="text-foreground-3">{b.expr}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {analysis.dispatches.length > 0 && (
          <div className="min-w-[220px] flex-1 rounded-card border border-border bg-surface-2 px-4 py-3">
            <div className="mb-2 text-xs font-medium text-muted-foreground">Dispatch calls</div>
            {analysis.dispatches.map((d) => (
              <div key={d} className="py-1 font-mono text-[11px] text-foreground-2">
                <span className="text-warning-t">dispatch_task</span>
                <span className="text-muted-foreground">(&apos;</span>
                {d}
                <span className="text-muted-foreground">&apos;)</span>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="flex flex-col gap-2">
        <div className="text-xs font-medium text-muted-foreground">Used by</div>
        <UsedBy refs={prompt.usedBy.map((action) => ({ workflow: "", action }))} />
      </div>
    </div>
  )
}

/* ================================================================== */
/*  Tools                                                             */
/* ================================================================== */

export function ToolsScreen() {
  const { toolFunctions } = useCatalogData()
  const [search, setSearch] = useState("")
  const [selectedName, setSelectedName] = useState<string | null>(null)

  const udfTools = useMemo(() => toolFunctions.filter((t) => t.udf), [toolFunctions])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return udfTools
    return udfTools.filter((t) => `${t.name} ${t.sig} ${t.file}`.toLowerCase().includes(q))
  }, [udfTools, search])

  const groups = useMemo(() => {
    const byFile = new Map<string, ToolFunction[]>()
    for (const t of filtered) {
      const dir = t.file.split("/").slice(0, -1).join("/") || "(top-level)"
      const list = byFile.get(dir)
      if (list) list.push(t)
      else byFile.set(dir, [t])
    }
    return [...byFile.entries()].sort(([a], [b]) => a.localeCompare(b))
  }, [filtered])

  const selected = filtered.find((t) => t.name === selectedName) ?? filtered[0] ?? null
  const fileCount = new Set(filtered.map((t) => t.file)).size

  return (
    <div className="flex animate-view-in flex-col gap-3.5">
      <PageTitle
        title="Tools"
        subtitle={`${udfTools.length} UDF tools · ${fileCount} file${fileCount === 1 ? "" : "s"}`}
      />
      <div className={PANE}>
        <div className={LIST}>
          <div className="border-b border-border p-3">
            <SearchInput value={search} onChange={setSearch} placeholder="Search tools…" />
          </div>
          <div className="flex-1 overflow-y-auto">
            {groups.map(([dir, tools]) => (
              <div key={dir}>
                <div className="flex justify-between gap-2 border-t border-border bg-surface-2 px-[15px] py-2.5 font-mono text-[11px] text-muted-foreground">
                  <span className="min-w-0 truncate">{dir}</span>
                  <span className="shrink-0">{tools.length} tool{tools.length === 1 ? "" : "s"}</span>
                </div>
                {tools.map((t) => (
                  <button
                    key={t.name}
                    onClick={() => setSelectedName(t.name)}
                    className={`flex w-full items-center gap-2.5 px-[15px] py-2 text-left hover:bg-hover ${
                      selected?.name === t.name ? "bg-accent-a12" : ""
                    }`}
                  >
                    <span className={`min-w-0 flex-1 truncate font-mono text-[11.5px] ${selected?.name === t.name ? "text-accent-t" : "text-foreground"}`}>
                      {t.name}
                    </span>
                    {!t.found && (
                      <span className="shrink-0 rounded-sm bg-danger-a12 px-1.5 py-px font-mono text-[9.5px] text-danger-t">
                        missing
                      </span>
                    )}
                  </button>
                ))}
              </div>
            ))}
            {filtered.length === 0 && <EmptyState message="No tools match this search" />}
          </div>
        </div>
        <div className={DETAIL}>
          {selected ? <ToolDetail tool={selected} /> : <EmptyState message="No UDF tools in this catalog." />}
        </div>
      </div>
    </div>
  )
}

function ToolDetail({ tool }: { tool: ToolFunction }) {
  return (
    <div className="flex flex-col gap-4">
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-[15px] font-semibold">{tool.name}</span>
          {!tool.found && (
            <span className="rounded-sm bg-danger-a12 px-1.5 py-0.5 font-mono text-[10px] text-danger-t">
              not found on disk
            </span>
          )}
        </div>
        <div className="mt-1 font-mono text-[11px] text-muted-foreground">{tool.file}</div>
      </div>

      <div className="overflow-x-auto rounded-control border border-border bg-well px-4 py-3.5 font-mono text-xs leading-[1.7] text-accent-bright">
        {tool.sig || `${tool.name}()`}
      </div>

      {tool.sourceCode ? (
        <SourceCode code={tool.sourceCode} />
      ) : (
        <p className="m-0 text-[12.5px] leading-relaxed text-muted-foreground">
          Source code was not captured for this tool.
        </p>
      )}
    </div>
  )
}

/* ─── Python source view ────────────────────────────────────────────────── */

type TokenType = "keyword" | "builtin" | "string" | "comment" | "decorator" | "number" | "defname" | "plain"

const PY_KEYWORDS = new Set([
  "False", "None", "True", "and", "as", "assert", "async", "await", "break", "class",
  "continue", "def", "del", "elif", "else", "except", "finally", "for", "from", "global",
  "if", "import", "in", "is", "lambda", "nonlocal", "not", "or", "pass", "raise",
  "return", "try", "while", "with", "yield",
])
const PY_BUILTINS = new Set([
  "print", "len", "range", "int", "str", "float", "list", "dict", "set", "tuple",
  "bool", "type", "isinstance", "issubclass", "hasattr", "getattr", "setattr",
  "enumerate", "zip", "map", "filter", "sorted", "reversed", "any", "all", "min", "max",
  "sum", "abs", "round", "open", "super", "property", "staticmethod", "classmethod",
  "ValueError", "TypeError", "KeyError", "IndexError", "AttributeError", "RuntimeError",
  "Exception", "StopIteration", "NotImplementedError", "OSError", "IOError",
])

const TOKEN_CLASS: Record<TokenType, string> = {
  keyword: "text-llm-t font-medium",
  builtin: "text-tool-t",
  string: "text-success-t",
  comment: "text-muted-2 italic",
  decorator: "text-warning-t",
  number: "text-type-array",
  defname: "text-foreground font-medium",
  plain: "text-foreground-2",
}

interface Token { type: TokenType; text: string }

function tokenizePythonLine(
  line: string,
  prevTriple: false | '"""' | "'''",
): { tokens: Token[]; inTriple: false | '"""' | "'''" } {
  const tokens: Token[] = []
  let i = 0
  let tripleState = prevTriple

  const push = (type: TokenType, text: string) => { if (text) tokens.push({ type, text }) }

  if (tripleState) {
    const end = line.indexOf(tripleState)
    if (end === -1) { push("string", line); return { tokens, inTriple: tripleState } }
    push("string", line.slice(0, end + 3))
    i = end + 3
    tripleState = false
  }

  while (i < line.length) {
    const rest = line.slice(i)

    const prefixMatch = rest.match(/^([fFrRbBuU]{1,2})(['"])/)
    if (prefixMatch) {
      const prefix = prefixMatch[1]
      const quote = prefixMatch[2]
      const afterPrefix = rest.slice(prefix.length)
      if (afterPrefix.startsWith('"""') || afterPrefix.startsWith("'''")) {
        const q = afterPrefix.startsWith('"""') ? '"""' : ("'''" as const)
        const end = line.indexOf(q, i + prefix.length + 3)
        if (end === -1) { push("string", line.slice(i)); return { tokens, inTriple: q } }
        push("string", line.slice(i, end + 3)); i = end + 3; continue
      }
      let j = i + prefix.length + 1
      while (j < line.length && line[j] !== quote) { if (line[j] === "\\") j++; j++ }
      push("string", line.slice(i, j + 1)); i = j + 1; continue
    }

    if (rest.startsWith('"""') || rest.startsWith("'''")) {
      const q = rest.startsWith('"""') ? '"""' : ("'''" as const)
      const end = line.indexOf(q, i + 3)
      if (end === -1) { push("string", line.slice(i)); return { tokens, inTriple: q } }
      push("string", line.slice(i, end + 3)); i = end + 3; continue
    }
    if (rest[0] === '"' || rest[0] === "'") {
      const quote = rest[0]
      let j = i + 1
      while (j < line.length && line[j] !== quote) { if (line[j] === "\\") j++; j++ }
      push("string", line.slice(i, j + 1)); i = j + 1; continue
    }
    if (rest[0] === "#") { push("comment", line.slice(i)); break }
    if (rest[0] === "@" && (i === 0 || /^\s*$/.test(line.slice(0, i)))) {
      push("decorator", line.slice(i)); break
    }
    const numMatch = rest.match(/^(0[xX][\da-fA-F_]+|0[oO][0-7_]+|0[bB][01_]+|\d[\d_]*\.?\d*(?:e[+-]?\d+)?)/)
    if (numMatch && (i === 0 || /[\s([{,:=<>!+\-*/]/.test(line[i - 1]))) {
      push("number", numMatch[0]); i += numMatch[0].length; continue
    }
    const wordMatch = rest.match(/^[A-Za-z_]\w*/)
    if (wordMatch) {
      const w = wordMatch[0]
      if (PY_KEYWORDS.has(w)) {
        push("keyword", w)
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
    const wsMatch = rest.match(/^[^A-Za-z_'"#@\d]+/)
    if (wsMatch) { push("plain", wsMatch[0]); i += wsMatch[0].length; continue }
    push("plain", rest[0]); i++
  }
  return { tokens, inTriple: tripleState }
}

function SourceCode({ code }: { code: string }) {
  const lines = useMemo(() => {
    let tripleState: false | '"""' | "'''" = false
    return code.split("\n").map((line) => {
      const result = tokenizePythonLine(line, tripleState)
      tripleState = result.inTriple
      return result.tokens
    })
  }, [code])

  return (
    <div className="overflow-hidden rounded-card border border-border">
      <div className="flex border-b border-border-soft bg-surface-2 px-4 py-2">
        <span className="font-mono text-[11px] text-muted-foreground">Source</span>
        <span className="flex-1" />
        <span className="font-mono text-[10px] text-muted-2">{lines.length} lines</span>
      </div>
      <div className="flex max-h-[420px] overflow-y-auto bg-well">
        <div className="w-10 shrink-0 select-none border-r border-border-soft">
          {lines.map((_, i) => (
            <div key={i} className="h-[22px] px-2 text-right font-mono text-xs leading-[22px] text-muted-2">
              {i + 1}
            </div>
          ))}
        </div>
        <div className="min-w-0 flex-1 overflow-x-auto">
          {lines.map((tokens, i) => (
            <pre key={i} className="h-[22px] whitespace-pre px-4 font-mono text-xs leading-[22px]">
              {tokens.map((t, j) => (
                <span key={j} className={TOKEN_CLASS[t.type]}>{t.text}</span>
              ))}
              {tokens.length === 0 && " "}
            </pre>
          ))}
        </div>
      </div>
    </div>
  )
}
