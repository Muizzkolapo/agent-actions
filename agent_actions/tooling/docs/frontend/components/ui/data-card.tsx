"use client"

import React, { useState, useCallback, useEffect } from "react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { ChevronRight, Copy, Check } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import {
  METADATA_KEYS,
  classifyRecord,
  humanizeKey,
  isInlineArray,
  isLongFormField,
  isShortValue,
  isSourceQuoteField,
  getValueType,
  formatValue,
  type ClassifiedField,
} from "@/lib/data-card-utils"
import type { PromptTrace } from "@/lib/catalog-client"

function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? "" : "s"}`
}

// ── Shared value renderer (used by both DataCard and table CellValue) ──────

export function CellValue({ value }: { value: unknown }) {
  if (value === null || value === undefined) {
    return <span className="text-[10px] italic text-muted-foreground/50">null</span>
  }
  if (typeof value === "boolean") {
    return (
      <Badge
        variant="outline"
        className={`text-[10px] font-normal rounded-md ${
          value
            ? "bg-[hsl(var(--success))]/10 text-[hsl(var(--success))] border-[hsl(var(--success))]/20"
            : "bg-[hsl(var(--destructive))]/10 text-[hsl(var(--destructive))] border-[hsl(var(--destructive))]/20"
        }`}
      >
        {String(value)}
      </Badge>
    )
  }
  if (typeof value === "number") {
    return <span className="font-mono tabular-nums text-foreground">{value.toLocaleString()}</span>
  }
  if (typeof value === "object") {
    return (
      <span className="font-mono text-muted-foreground break-all">{formatValue(value, 80)}</span>
    )
  }
  const str = String(value)
  return (
    <span className="font-mono text-foreground break-all">{str}</span>
  )
}

// ── Copy button ────────────────────────────────────────────────────────────

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)

  const handleCopy = useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation()
      navigator.clipboard.writeText(text).then(() => {
        setCopied(true)
        setTimeout(() => setCopied(false), 1500)
      })
    },
    [text],
  )

  return (
    <button
      onClick={handleCopy}
      className={`dc-copy-btn ${copied ? "copied" : ""}`}
      title="Copy to clipboard"
    >
      {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
    </button>
  )
}

// ── Markdown prose renderer ────────────────────────────────────────────────

function MarkdownProse({ text }: { text: string }) {
  return (
    <article className="dc-prose">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
    </article>
  )
}

// ── JSON syntax highlighter ────────────────────────────────────────────────

function highlightJsonLine(line: string): React.ReactNode[] {
  const tokens: React.ReactNode[] = []
  let i = 0

  while (i < line.length) {
    // Whitespace
    if (/\s/.test(line[i])) {
      let ws = ""
      while (i < line.length && /\s/.test(line[i])) ws += line[i++]
      tokens.push(ws)
      continue
    }
    // Braces / brackets / colon / comma
    if ("{[}]:,".includes(line[i])) {
      tokens.push(
        <span key={`b${i}`} className="dc-json-brace">
          {line[i]}
        </span>,
      )
      i++
      continue
    }
    // String
    if (line[i] === '"') {
      let str = '"'
      i++
      while (i < line.length && line[i] !== '"') {
        if (line[i] === "\\") {
          str += line[i++]
        }
        if (i < line.length) str += line[i++]
      }
      if (i < line.length) str += line[i++]

      // Determine if this is a key (followed by :) or a value
      let j = i
      while (j < line.length && /\s/.test(line[j])) j++
      const isKey = j < line.length && line[j] === ":"
      tokens.push(
        <span key={`s${i}`} className={isKey ? "dc-json-key" : "dc-json-string"}>
          {str}
        </span>,
      )
      continue
    }
    // Number / boolean / null
    const rest = line.slice(i)
    const numMatch = rest.match(/^-?\d+(\.\d+)?([eE][+-]?\d+)?/)
    if (numMatch) {
      tokens.push(
        <span key={`n${i}`} className="dc-json-number">
          {numMatch[0]}
        </span>,
      )
      i += numMatch[0].length
      continue
    }
    const kwMatch = rest.match(/^(true|false)/)
    if (kwMatch) {
      tokens.push(
        <span key={`k${i}`} className="dc-json-bool">
          {kwMatch[0]}
        </span>,
      )
      i += kwMatch[0].length
      continue
    }
    const nullMatch = rest.match(/^null/)
    if (nullMatch) {
      tokens.push(
        <span key={`x${i}`} className="dc-json-null">
          null
        </span>,
      )
      i += 4
      continue
    }
    // Fallback
    tokens.push(line[i])
    i++
  }
  return tokens
}

function JsonHighlighter({ text }: { text: string }) {
  let formatted: string
  try {
    formatted = JSON.stringify(JSON.parse(text), null, 2)
  } catch {
    // Not valid JSON — render as plain monospace
    return (
      <pre className="dc-json px-3 py-2 whitespace-pre-wrap break-all">
        {text}
      </pre>
    )
  }

  const lines = formatted.split("\n")

  return (
    <div className="dc-json">
      {lines.map((line, i) => (
        <div key={i} className="dc-json-line">
          <span className="dc-json-gutter">{i + 1}</span>
          <span className="dc-json-code">{highlightJsonLine(line)}</span>
        </div>
      ))}
    </div>
  )
}

// ── Collapsible section ────────────────────────────────────────────────────

function CollapsibleSection({
  label,
  accentClass,
  badge,
  hint,
  open,
  onToggle,
  copyText,
  children,
}: {
  label: string
  badge?: React.ReactNode
  hint?: string
  open: boolean
  onToggle: () => void
  copyText?: string
  children: React.ReactNode
}) {
  return (
    <div>
      <button onClick={onToggle} className="dc-section-header">
        <ChevronRight
          className={`h-3.5 w-3.5 shrink-0 text-muted-foreground/50 transition-transform ${open ? "rotate-90" : ""}`}
        />
        <span className="text-[0.85em] font-semibold text-foreground/90">{label}</span>
        {badge}
        {hint && <span className="text-[0.75em] text-muted-foreground/50 ml-auto">{hint}</span>}
        {copyText && <CopyButton text={copyText} />}
      </button>
      <div className="data-card-drawer" data-open={open}>
        <div>{children}</div>
      </div>
    </div>
  )
}

// ── Field renderers ────────────────────────────────────────────────────────

function InlinePills({ items }: { items: (string | number)[] }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((item, i) => (
        <span key={i} className="data-card-pill">
          {String(item)}
        </span>
      ))}
    </div>
  )
}

function isArrayOfObjects(value: unknown): value is Record<string, unknown>[] {
  if (!Array.isArray(value) || value.length === 0) return false
  return value.every((v) => typeof v === "object" && v !== null && !Array.isArray(v))
}

function FieldValue({ fieldKey, value }: { fieldKey: string; value: unknown }) {
  if (isInlineArray(value)) {
    return <InlinePills items={value as (string | number)[]} />
  }
  if (getValueType(value) === "object" && !isArrayOfObjects(value)) {
    return <JsonHighlighter text={JSON.stringify(value, null, 2)} />
  }
  // Source quote — blockquote treatment
  if (isSourceQuoteField(fieldKey) && typeof value === "string") {
    return <div className="dc-source-quote">{value}</div>
  }
  // Long text — Notion prose block
  if (typeof value === "string" && value.length > 80) {
    return <div className="dc-tree-prose">{value}</div>
  }
  return <CellValue value={value} />
}

// ── Tree components ────────────────────────────────────────────────────────

const TREE_MAX_DEPTH = 5

function TreeField({ fieldKey, value, defaultOpen = true, depth = 0 }: { fieldKey: string; value: unknown; defaultOpen?: boolean; depth?: number }) {
  const [open, setOpen] = useState(defaultOpen)

  if (typeof value === "object" && value !== null && !Array.isArray(value) && depth < TREE_MAX_DEPTH) {
    const entries = Object.entries(value as Record<string, unknown>)
    return (
      <TreeNode label={fieldKey} badge={`${entries.length} fields`} defaultOpen={defaultOpen}>
        {entries.map(([k, v]) => (
          <TreeField key={k} fieldKey={k} value={v} defaultOpen={false} depth={depth + 1} />
        ))}
      </TreeNode>
    )
  }

  if (isArrayOfObjects(value) && depth < TREE_MAX_DEPTH) {
    const items = value as Record<string, unknown>[]
    return (
      <TreeNode label={fieldKey} badge={`array[${items.length}]`} defaultOpen={defaultOpen}>
        {items.slice(0, 20).map((item, i) => (
          <ArrayItemNode key={i} item={item} index={i} defaultOpen={i === 0} depth={depth + 1} />
        ))}
        {items.length > 20 && (
          <span className="text-[0.75em] text-muted-foreground/50 pl-4 py-1 block italic">
            + {items.length - 20} more items
          </span>
        )}
      </TreeNode>
    )
  }

  const valStr = typeof value === "string" ? value : typeof value === "object" ? JSON.stringify(value) : String(value ?? "")
  const preview = valStr.length > 60 ? valStr.slice(0, 60) + "\u2026" : valStr

  return (
    <div className="py-0.5">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2 min-w-0 w-full text-left hover:bg-accent/10 rounded-sm py-0.5 pl-4 pr-2 transition-colors"
      >
        <ChevronRight
          className={`h-2.5 w-2.5 shrink-0 text-muted-foreground/40 transition-transform ${open ? "rotate-90" : ""}`}
        />
        <span className="text-[0.85em] font-mono text-[#7dd3fc] shrink-0">{fieldKey}</span>
        {!open && (
          <span className="text-[0.8em] font-mono text-muted-foreground/40 truncate">{preview}</span>
        )}
      </button>
      <div className="data-card-drawer" data-open={open}>
        <div className="pl-12 pr-2 pb-1">
          <FieldValue fieldKey={fieldKey} value={value} />
        </div>
      </div>
    </div>
  )
}

function TreeNode({
  label,
  badge,
  defaultOpen = false,
  children,
}: {
  label: string
  badge?: string
  defaultOpen?: boolean
  children: React.ReactNode
}) {
  const [open, setOpen] = useState(defaultOpen)

  return (
    <div>
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1.5 py-1.5 px-4 w-full text-left hover:bg-accent/20 transition-colors rounded-sm"
      >
        <ChevronRight
          className={`h-3 w-3 shrink-0 text-muted-foreground/60 transition-transform ${open ? "rotate-90" : ""}`}
        />
        <span className="text-[0.9em] font-mono font-semibold text-[#c084fc]">{label}</span>
        {badge && <span className="text-[0.75em] font-mono text-[#6ee7b7]">{badge}</span>}
      </button>
      <div className="data-card-drawer" data-open={open}>
        <div className="pl-4">{children}</div>
      </div>
    </div>
  )
}

function ArrayItemNode({
  item,
  index,
  defaultOpen = false,
  depth = 0,
}: {
  item: Record<string, unknown>
  index: number
  defaultOpen?: boolean
  depth?: number
}) {
  const [open, setOpen] = useState(defaultOpen)

  const previewField = Object.entries(item).find(
    ([, v]) => typeof v === "string" && (v as string).length > 10,
  )
  const preview = previewField
    ? (previewField[1] as string).slice(0, 80) +
      ((previewField[1] as string).length > 80 ? "\u2026" : "")
    : plural(Object.keys(item).length, "field")

  return (
    <div>
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1.5 py-1 px-4 w-full text-left hover:bg-accent/20 transition-colors rounded-sm"
      >
        <ChevronRight
          className={`h-3 w-3 shrink-0 text-muted-foreground/60 transition-transform ${open ? "rotate-90" : ""}`}
        />
        <span className="text-[0.85em] font-mono text-[#7dd3fc]">[{index}]</span>
        <span className="text-[0.75em] font-mono text-[#6ee7b7]">object</span>
        {!open && (
          <span className="text-[0.8em] text-muted-foreground/50 truncate ml-1 italic">
            {preview}
          </span>
        )}
      </button>
      <div className="data-card-drawer" data-open={open}>
        <div className="pl-4">
          {Object.entries(item).map(([k, v]) => (
            <TreeField key={k} fieldKey={k} value={v} depth={depth} />
          ))}
        </div>
      </div>
    </div>
  )
}

// ── Section state persistence ──────────────────────────────────────────────

const DEFAULT_SECTION_STATE = {
  promptTrace: false,
  inputData: false,
  rawResponse: false,
  actionOutput: true,
  metadata: false,
}

let _cachedNodeKey: string | null = null
let _cachedState: typeof DEFAULT_SECTION_STATE | null = null

function useSectionState(nodeKey: string) {
  const [state, setState] = useState(() => {
    if (_cachedNodeKey === nodeKey && _cachedState) return _cachedState
    return { ...DEFAULT_SECTION_STATE }
  })

  useEffect(() => {
    if (_cachedNodeKey !== nodeKey) {
      _cachedNodeKey = nodeKey
      _cachedState = { ...DEFAULT_SECTION_STATE }
      setState({ ...DEFAULT_SECTION_STATE })
    }
  }, [nodeKey])

  const toggle = useCallback((key: keyof typeof DEFAULT_SECTION_STATE) => {
    setState((prev) => {
      const next = { ...prev, [key]: !prev[key] }
      _cachedState = next
      return next
    })
  }, [])

  return { state, toggle }
}

// ── DataCard ──────────────────────────────────────────────────────────────

export interface ActionInfo {
  name: string
  kind: string
  impl?: string
  intent?: string
  dependencies: string[]
}

export interface DataCardProps {
  record: Record<string, unknown>
  index?: number
  fontSize?: number
  defaultOpen?: boolean
  actionInfo?: ActionInfo
}

export function getDisplayFields(record: Record<string, unknown>): Record<string, unknown> {
  // Scanner already unwraps namespaced content to action-specific fields.
  // This function just extracts the content dict for display.
  const contentVal = record.content
  if (contentVal && typeof contentVal === "object" && !Array.isArray(contentVal)) {
    return contentVal as Record<string, unknown>
  }
  // Fallback: record has no namespaced content dict. Strip framework keys so only
  // user content fields are returned — downstream no longer applies classifyField.
  const result: Record<string, unknown> = {}
  for (const [k, v] of Object.entries(record)) {
    if (!METADATA_KEYS.has(k)) {
      result[k] = v
    }
  }
  return result
}

export function DataCard({ record, index, fontSize, defaultOpen = true, actionInfo }: DataCardProps) {
  const [recordOpen, setRecordOpen] = useState(defaultOpen)
  const displayRecord = getDisplayFields(record)
  const recordMetadata = record.metadata as Record<string, unknown> | undefined
  const tombstoneReason = typeof recordMetadata === "object" && recordMetadata !== null
    ? recordMetadata.reason as string | undefined
    : undefined
  const guardSkipped = tombstoneReason === "guard_skip"
  const upstreamUnprocessed = tombstoneReason === "upstream_unprocessed"
  const { identity, metadata } = classifyRecord(record)

  const outputFields = Object.entries(displayRecord)
    .map(([key, value]) => ({ key, value }))

  const trace =
    record._trace && typeof record._trace === "object" && "compiled_prompt" in record._trace
      ? (record._trace as PromptTrace)
      : null

  // Parse input data from trace's llm_context (JSON string → namespaced object)
  let inputData: Record<string, unknown> | null = null
  if (trace?.llm_context) {
    try {
      const parsed = JSON.parse(trace.llm_context)
      if (typeof parsed === "object" && parsed !== null && !Array.isArray(parsed)) {
        inputData = parsed as Record<string, unknown>
      }
    } catch {
      // Not valid JSON — skip input data section
    }
  }

  // Derive a stable node key for section state persistence
  const nodeKey =
    typeof record._file === "string"
      ? record._file
      : typeof record.node_id === "string"
        ? record.node_id
        : "default"

  const { state: sec, toggle } = useSectionState(nodeKey)

  // Prepare copy text for output section
  const outputJson = JSON.stringify(displayRecord, null, 2)

  return (
    <div className="data-card" style={fontSize ? { fontSize: `${fontSize}px` } : undefined}>
      {/* Identity header — click to expand/collapse record */}
      <button
        onClick={() => setRecordOpen(!recordOpen)}
        className="flex items-center gap-2 flex-wrap px-4 pt-3 pb-1 w-full text-left hover:bg-accent/5 transition-colors"
      >
        <ChevronRight
          className={`h-3.5 w-3.5 shrink-0 text-foreground/60 transition-transform ${recordOpen ? "rotate-90" : ""}`}
        />
        {typeof index === "number" && (
          <span className="text-[11px] font-mono font-medium text-foreground/70 tabular-nums">
            #{index}
          </span>
        )}
        {identity.map((f) => (
          <span
            key={f.key}
            className="text-[10px] font-mono text-foreground/70 truncate"
            title={`${f.key}: ${formatValue(f.value, 0)}`}
          >
            {formatValue(f.value, 32)}
          </span>
        ))}
        {typeof record._file === "string" && (
          <span
            className="text-[10px] font-mono text-foreground/60 truncate"
            title={record._file}
          >
            {record._file}
          </span>
        )}
        {!recordOpen && (
          <span className="text-[10px] text-foreground/50 ml-auto">
            {guardSkipped ? "guard skipped" : upstreamUnprocessed ? "upstream unprocessed" : `${trace ? "trace + " : ""}${plural(outputFields.length, "field")}`}
          </span>
        )}
      </button>

      <div className="data-card-drawer" data-open={recordOpen}>
        <div className="pl-4">

      {/* Action info bar */}
      {actionInfo && (
        <div className="px-4 py-2 flex items-center gap-2 flex-wrap border-t border-border/30">
          <span className="text-[10px] font-mono font-medium px-1.5 py-0.5 rounded bg-secondary text-foreground/70">
            {actionInfo.kind}
          </span>
          {actionInfo.impl && (
            <span className="text-[10px] font-mono text-muted-foreground/60">
              fn: {actionInfo.impl}
            </span>
          )}
          {actionInfo.dependencies.length > 0 && (
            <span className="text-[10px] font-mono text-muted-foreground/50">
              deps: {actionInfo.dependencies.join(", ")}
            </span>
          )}
          {actionInfo.intent && (
            <span className="text-[10px] text-muted-foreground/50 truncate" title={actionInfo.intent}>
              {actionInfo.intent}
            </span>
          )}
        </div>
      )}

      {/* Section 1: Prompt Trace */}
      {trace?.compiled_prompt && (
        <CollapsibleSection
          label="Prompt Trace"

          badge={
            <div className="flex gap-1.5">
              {trace.model_name && (
                <span className="dc-badge dc-badge-model">{trace.model_name}</span>
              )}
              {trace.run_mode && (
                <span className="dc-badge dc-badge-mode">{trace.run_mode}</span>
              )}
            </div>
          }
          hint={trace.prompt_length ? `${trace.prompt_length.toLocaleString()} chars` : undefined}
          open={sec.promptTrace}
          onToggle={() => toggle("promptTrace")}
          copyText={trace.compiled_prompt}
        >
          <div className="px-2 pb-3">
            <MarkdownProse text={trace.compiled_prompt} />
          </div>
        </CollapsibleSection>
      )}

      {/* Section 2: Input Data */}
      {inputData && Object.keys(inputData).length > 0 && (
        <CollapsibleSection
          label="Input Data"

          hint={plural(Object.keys(inputData).length, "namespace")}
          open={sec.inputData}
          onToggle={() => toggle("inputData")}
          copyText={JSON.stringify(inputData, null, 2)}
        >
          <div className="pb-2 pl-4">
            {Object.entries(inputData).map(([nsName, nsData]) => {
              if (typeof nsData !== "object" || nsData === null) {
                return (
                  <TreeField key={nsName} fieldKey={nsName} value={nsData} />
                )
              }
              const fields = nsData as Record<string, unknown>
              return (
                <TreeNode
                  key={nsName}
                  label={nsName}
                  badge={plural(Object.keys(fields).length, "field")}
                  defaultOpen={false}
                >
                  {Object.entries(fields).map(([k, v]) => (
                    <TreeField key={k} fieldKey={k} value={v} />
                  ))}
                </TreeNode>
              )
            })}
          </div>
        </CollapsibleSection>
      )}

      {/* Section 3: Raw Response */}
      {trace?.response_text && (
        <CollapsibleSection
          label="Raw Response"

          hint={
            trace.response_length
              ? `${trace.response_length.toLocaleString()} chars`
              : undefined
          }
          open={sec.rawResponse}
          onToggle={() => toggle("rawResponse")}
          copyText={trace.response_text}
        >
          <div className="px-4 pb-3">
            <JsonHighlighter text={trace.response_text} />
          </div>
        </CollapsibleSection>
      )}

      {/* Section 3: Action Output */}
      {(outputFields.length > 0 || guardSkipped || upstreamUnprocessed) && (
        <CollapsibleSection
          label="Action Output"

          hint={guardSkipped ? "guard skipped" : upstreamUnprocessed ? "upstream unprocessed" : plural(outputFields.length, "field")}
          open={sec.actionOutput}
          onToggle={() => toggle("actionOutput")}
          copyText={guardSkipped || upstreamUnprocessed ? undefined : outputJson}
        >
          <div className="pb-2 pl-4">
            {guardSkipped ? (
              <div className="px-4 pb-3 text-xs text-muted-foreground italic">
                Guard skipped — no output produced
              </div>
            ) : upstreamUnprocessed ? (
              <div className="px-4 pb-3 text-xs text-muted-foreground italic">
                Upstream failure — no output produced
              </div>
            ) : (
              outputFields.map((f) => {
                if (isArrayOfObjects(f.value)) {
                  const items = f.value as Record<string, unknown>[]
                  return (
                    <TreeNode
                      key={f.key}
                      label={f.key}
                      badge={`array[${items.length}]`}
                      defaultOpen={true}
                    >
                      {items.map((item, i) => (
                        <ArrayItemNode
                          key={i}
                          item={item}
                          index={i}
                          defaultOpen={i === 0}
                        />
                      ))}
                    </TreeNode>
                  )
                }
                return <TreeField key={f.key} fieldKey={f.key} value={f.value} />
              })
            )}
          </div>
        </CollapsibleSection>
      )}

      {outputFields.length === 0 && !guardSkipped && !upstreamUnprocessed && (
        <div className="px-4 pb-3 text-xs text-muted-foreground italic">No content fields</div>
      )}

      {/* Section 4: Metadata */}
      {metadata.length > 0 && (
        <CollapsibleSection
          label="Metadata"

          hint={plural(metadata.length, "field")}
          open={sec.metadata}
          onToggle={() => toggle("metadata")}
          copyText={JSON.stringify(
            Object.fromEntries(metadata.map((f) => [f.key, f.value])),
            null,
            2,
          )}
        >
          <div className="px-4 pb-3 flex flex-col gap-1">
            {metadata.map((f) => (
              <div key={f.key} className="flex items-baseline gap-2 min-w-0 py-0.5">
                <span className="text-[0.8em] font-mono text-muted-foreground/50 shrink-0 min-w-[80px]">
                  {f.key}
                </span>
                <span className="text-[0.8em] font-mono text-muted-foreground/70 break-all">
                  {formatValue(f.value, 120)}
                </span>
              </div>
            ))}
          </div>
        </CollapsibleSection>
      )}

        </div>
      </div>
    </div>
  )
}
