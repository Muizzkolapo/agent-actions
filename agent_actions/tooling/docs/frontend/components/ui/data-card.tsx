"use client"

import React, { useState } from "react"
import { ChevronRight } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import {
  classifyField,
  classifyRecord,
  humanizeKey,
  isInlineArray,
  isLongFormField,
  isShortValue,
  getValueType,
  formatValue,
  type ClassifiedField,
} from "@/lib/data-card-utils"
import type { PromptTrace } from "@/lib/catalog-client"

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
    const str = JSON.stringify(value)
    return (
      <span className="font-mono text-muted-foreground truncate block max-w-[300px]" title={str}>
        {str.length > 80 ? str.slice(0, 80) + "\u2026" : str}
      </span>
    )
  }
  const str = String(value)
  return (
    <span className="font-mono text-foreground truncate block max-w-[300px]" title={str}>
      {str.length > 120 ? str.slice(0, 120) + "\u2026" : str}
    </span>
  )
}

// ── Field renderers ────────────────────────────────────────────────────────

function InlinePills({ items }: { items: (string | number)[] }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((item, i) => (
        <span key={i} className="data-card-pill">{String(item)}</span>
      ))}
    </div>
  )
}

function CodeBlock({ value }: { value: unknown }) {
  return (
    <pre className="rounded-md bg-secondary/40 border border-border/30 px-3 py-2 text-[0.8em] font-mono text-foreground/80 leading-relaxed overflow-x-auto whitespace-pre-wrap">
      {JSON.stringify(value, null, 2)}
    </pre>
  )
}

/** Render an array of objects as structured sub-cards instead of raw JSON. */
function ObjectArrayBlock({ items, fieldKey }: { items: Record<string, unknown>[]; fieldKey: string }) {
  const [expanded, setExpanded] = useState(false)
  const visibleCount = expanded ? items.length : 2
  const hasMore = items.length > 2

  return (
    <div className="flex flex-col gap-2">
      {items.slice(0, visibleCount).map((item, i) => (
        <div
          key={i}
          className="rounded-md border border-border/40 bg-secondary/20 px-3 py-2.5 flex flex-col gap-1.5"
        >
          <span className="text-[9px] font-mono text-muted-foreground/40 tabular-nums">
            {humanizeKey(fieldKey)} [{i + 1}/{items.length}]
          </span>
          {Object.entries(item).map(([k, v]) => {
            const valStr = typeof v === "object" && v !== null ? JSON.stringify(v) : String(v ?? "")
            const isLong = valStr.length > 100
            return (
              <div key={k} className={isLong ? "flex flex-col gap-0.5" : "flex items-baseline gap-2 min-w-0"}>
                <span className="text-[10px] uppercase tracking-wider font-semibold text-muted-foreground/70 shrink-0">
                  {humanizeKey(k)}
                </span>
                <span className={`text-[0.9em] ${isLong ? "data-card-prose" : "font-mono text-foreground/80"}`}>
                  {valStr}
                </span>
              </div>
            )
          })}
        </div>
      ))}
      {hasMore && (
        <button
          onClick={() => setExpanded(!expanded)}
          className="text-[10px] text-[hsl(var(--primary))] hover:underline self-start"
        >
          {expanded ? "Show less" : `Show ${items.length - 2} more`}
        </button>
      )}
    </div>
  )
}

/** True when value is an array of plain objects (not nested arrays). */
function isArrayOfObjects(value: unknown): value is Record<string, unknown>[] {
  if (!Array.isArray(value) || value.length === 0) return false
  return value.every((v) => typeof v === "object" && v !== null && !Array.isArray(v))
}

function FieldValue({ fieldKey, value }: { fieldKey: string; value: unknown }) {
  if (isInlineArray(value)) {
    return <InlinePills items={value as (string | number)[]} />
  }
  if (isArrayOfObjects(value)) {
    return <ObjectArrayBlock items={value} fieldKey={fieldKey} />
  }
  if (getValueType(value) === "object") {
    return <CodeBlock value={value} />
  }
  if (typeof value === "string" && (isLongFormField(fieldKey) ? value.length > 80 : value.length > 120)) {
    return <ProseBlock text={value} />
  }
  return <CellValue value={value} />
}

function ProseBlock({ text }: { text: string }) {
  const [expanded, setExpanded] = useState(false)
  const needsClamp = text.length > 200

  return (
    <div>
      <p className={`data-card-prose ${needsClamp && !expanded ? "clamped" : ""}`}>
        {text}
      </p>
      {needsClamp && (
        <button
          onClick={() => setExpanded(!expanded)}
          className="text-[10px] text-[hsl(var(--primary))] hover:underline mt-1"
        >
          {expanded ? "Show less" : "Show more"}
        </button>
      )}
    </div>
  )
}

// ── Field row ─────────────────────────────────────────────────────────────

function FieldRow({ fieldKey, value }: { fieldKey: string; value: unknown }) {
  const short = isShortValue(value) && !isLongFormField(fieldKey)

  if (short) {
    return (
      <div className="flex items-baseline gap-3 min-w-0">
        <span className="data-card-label shrink-0 min-w-[80px]">{humanizeKey(fieldKey)}</span>
        <div className="min-w-0 flex-1 text-[1em] text-foreground">
          <FieldValue fieldKey={fieldKey} value={value} />
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-1">
      <span className="data-card-label">{humanizeKey(fieldKey)}</span>
      <div className="text-[1em] text-foreground">
        <FieldValue fieldKey={fieldKey} value={value} />
      </div>
    </div>
  )
}

// ── Collapsible section (shared by structured fields, metadata, trace) ───

function CollapsibleSection({
  label,
  badgeText,
  children,
  defaultOpen = false,
  className = "",
}: {
  label: string
  badgeText?: string
  children: React.ReactNode
  defaultOpen?: boolean
  className?: string
}) {
  const [open, setOpen] = useState(defaultOpen)

  return (
    <div className={`border-t border-border/50 mt-1 ${className}`}>
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1.5 py-2 px-4 text-[10px] text-muted-foreground hover:text-foreground transition-colors w-full"
      >
        <ChevronRight className={`h-3 w-3 transition-transform ${open ? "rotate-90" : ""}`} />
        <span className="uppercase tracking-wider font-semibold">{label}</span>
        {badgeText && <span className="text-muted-foreground/50 ml-1">{badgeText}</span>}
      </button>
      <div className="data-card-drawer" data-open={open}>
        <div>{children}</div>
      </div>
    </div>
  )
}

// ── Metadata drawer ───────────────────────────────────────────────────────

function MetadataDrawer({ fields }: { fields: ClassifiedField[] }) {
  if (fields.length === 0) return null

  return (
    <CollapsibleSection label="Metadata" badgeText={`${fields.length} fields`}>
      <div className="px-4 pb-3 flex flex-col gap-1.5">
        {fields.map((f) => (
          <div key={f.key} className="flex items-baseline gap-2 min-w-0">
            <span className="text-[9px] uppercase tracking-wider text-muted-foreground/60 font-medium shrink-0 min-w-[60px]">
              {humanizeKey(f.key)}
            </span>
            <span className="text-[11px] font-mono text-muted-foreground break-all">
              {formatValue(f.value, 120)}
            </span>
          </div>
        ))}
      </div>
    </CollapsibleSection>
  )
}

// ── Prompt Trace drawer ──────────────────────────────────────────────────

function PromptTraceDrawer({ trace }: { trace: PromptTrace }) {
  const [open, setOpen] = useState(false)

  const modelLabel = trace.model_name || "unknown"
  const modeLabel = trace.run_mode || "online"
  const isBatch = modeLabel === "batch"

  return (
    <div className="trace-section">
      <button
        onClick={() => setOpen(!open)}
        className={`trace-trigger ${open ? "open" : ""}`}
      >
        <ChevronRight className={`h-3 w-3 transition-transform ${open ? "rotate-90" : ""}`} />
        <span className="trace-label">Prompt Trace</span>
        <div className="trace-badges">
          <span className="trace-badge trace-badge-model">{modelLabel}</span>
          <span className={`trace-badge trace-badge-mode ${isBatch ? "batch" : ""}`}>{modeLabel}</span>
        </div>
      </button>
      <div className="data-card-drawer" data-open={open}>
        <div>
          <div className="trace-content">
            <div className="trace-panels">
              <div className="trace-panel trace-panel-prompt">
                <div className="trace-panel-header">
                  <span>Compiled Prompt</span>
                  {trace.prompt_length != null && (
                    <span className="trace-panel-size">{trace.prompt_length.toLocaleString()} chars</span>
                  )}
                </div>
                <div className="trace-panel-body">
                  {trace.compiled_prompt}
                </div>
              </div>
              <div className="trace-panel trace-panel-response">
                <div className="trace-panel-header">
                  <span>LLM Response</span>
                  {trace.response_length != null && (
                    <span className="trace-panel-size">{trace.response_length.toLocaleString()} chars</span>
                  )}
                </div>
                <div className="trace-panel-body">
                  {trace.response_text || <span className="text-muted-foreground/50 italic text-[10px]">Response pending</span>}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── DataCard ──────────────────────────────────────────────────────────────

export interface DataCardProps {
  record: Record<string, unknown>
  index?: number
  fontSize?: number
}

function getDisplayFields(record: Record<string, unknown>): Record<string, unknown> {
  const contentVal = record.content
  if (contentVal && typeof contentVal === "object" && !Array.isArray(contentVal)) {
    return contentVal as Record<string, unknown>
  }
  return record
}

export function DataCard({ record, index, fontSize }: DataCardProps) {
  const displayRecord = getDisplayFields(record)
  const { identity, metadata } = classifyRecord(record)

  const displayFields = Object.entries(displayRecord)
    .filter(([key]) => classifyField(key) === "content")
    .map(([key, value]) => ({ key, value, role: "content" as const }))

  // Split into scalar (simple) vs structured (complex) fields
  const scalarFields = displayFields.filter(
    (f) => !isArrayOfObjects(f.value) && (getValueType(f.value) !== "object" || isInlineArray(f.value)),
  )
  const structuredFields = displayFields.filter(
    (f) => isArrayOfObjects(f.value) || (getValueType(f.value) === "object" && !isInlineArray(f.value)),
  )

  const hasTrace = record._trace && typeof record._trace === "object" && "compiled_prompt" in record._trace

  return (
    <div
      className="data-card"
      style={fontSize ? { fontSize: `${fontSize}px` } : undefined}
    >
      {/* 1. Identity header */}
      <div className="px-4 pt-3 pb-1">
        <div className="flex items-center gap-2 flex-wrap">
          {typeof index === "number" && (
            <span className="text-[10px] font-mono text-muted-foreground/40 tabular-nums">
              #{index}
            </span>
          )}
          {identity.map((f) => (
            <span
              key={f.key}
              className="text-[10px] font-mono text-muted-foreground/60 truncate"
              title={`${f.key}: ${formatValue(f.value, 0)}`}
            >
              {formatValue(f.value, 32)}
            </span>
          ))}
          {typeof record._file === "string" && (
            <span className="text-[10px] font-mono text-muted-foreground/50 truncate" title={record._file}>
              {record._file}
            </span>
          )}
        </div>
      </div>

      {/* 2. Prompt Trace (input data — what was sent to the LLM) */}
      {hasTrace && (
        <PromptTraceDrawer trace={record._trace as PromptTrace} />
      )}

      {/* 3. Action Output — scalar fields inline, then structured fields */}
      {(scalarFields.length > 0 || structuredFields.length > 0) && (
        <div className="px-4 pb-3 pt-1 flex flex-col gap-2.5">
          {/* Section label */}
          {hasTrace && (
            <span className="text-[9px] uppercase tracking-wider font-semibold text-muted-foreground/50 pt-1">
              Output
            </span>
          )}
          {scalarFields.map((f) => (
            <FieldRow key={f.key} fieldKey={f.key} value={f.value} />
          ))}
          {structuredFields.map((f) => (
            <FieldRow key={f.key} fieldKey={f.key} value={f.value} />
          ))}
        </div>
      )}

      {scalarFields.length === 0 && structuredFields.length === 0 && (
        <div className="px-4 pb-3 text-xs text-muted-foreground italic">
          No content fields
        </div>
      )}

      {/* 4. Metadata (last — collapsible) */}
      <MetadataDrawer fields={metadata} />
    </div>
  )
}
