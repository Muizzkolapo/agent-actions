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

function FieldValue({ fieldKey, value }: { fieldKey: string; value: unknown }) {
  if (isInlineArray(value)) {
    return <InlinePills items={value as (string | number)[]} />
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

// ── Metadata drawer ───────────────────────────────────────────────────────

function MetadataDrawer({ fields }: { fields: ClassifiedField[] }) {
  const [open, setOpen] = useState(false)

  if (fields.length === 0) return null

  return (
    <div className="border-t border-border/50 mt-1">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1.5 py-2 px-4 text-[10px] text-muted-foreground hover:text-foreground transition-colors w-full"
      >
        <ChevronRight className={`h-3 w-3 transition-transform ${open ? "rotate-90" : ""}`} />
        <span className="uppercase tracking-wider font-semibold">Metadata</span>
        <span className="text-muted-foreground/50 ml-1">{fields.length} fields</span>
      </button>
      <div className="data-card-drawer" data-open={open}>
        <div>
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

  const shortFields = displayFields.filter(
    (f) => isShortValue(f.value) && !isLongFormField(f.key),
  )
  const longFields = displayFields.filter(
    (f) => !isShortValue(f.value) || isLongFormField(f.key),
  )

  return (
    <div
      className="data-card"
      style={fontSize ? { fontSize: `${fontSize}px` } : undefined}
    >
      {/* Identity header */}
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

      {/* Content fields */}
      {(shortFields.length > 0 || longFields.length > 0) && (
        <div className="px-4 pb-3 pt-1 flex flex-col gap-2.5">
          {shortFields.map((f) => (
            <FieldRow key={f.key} fieldKey={f.key} value={f.value} />
          ))}
          {longFields.map((f) => (
            <FieldRow key={f.key} fieldKey={f.key} value={f.value} />
          ))}
        </div>
      )}

      {shortFields.length === 0 && longFields.length === 0 && (
        <div className="px-4 pb-3 text-xs text-muted-foreground italic">
          No content fields
        </div>
      )}

      <MetadataDrawer fields={metadata} />
    </div>
  )
}
