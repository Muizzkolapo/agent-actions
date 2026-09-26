"use client"

import React from "react"
import { Search } from "lucide-react"

/**
 * Graphite primitives. Every colour here comes from a token: the base semantic
 * tokens sit behind content, the `-t` variants are the only ones that may reach
 * a text colour.
 */

export type Tone = "running" | "passed" | "failed" | "warning" | "neutral"

const TONES: Record<Tone, { bg: string; text: string; icon: string | null }> = {
  running: { bg: "bg-info-a12", text: "text-info-t", icon: null },
  passed: { bg: "bg-success-a12", text: "text-success-t", icon: "✓" },
  failed: { bg: "bg-danger-a12", text: "text-danger-t", icon: "✕" },
  warning: { bg: "bg-warning-a12", text: "text-warning-t", icon: "⚠" },
  neutral: { bg: "bg-surface-2", text: "text-muted-foreground", icon: null },
}

/** Soft background, tone text, and a glyph — never a bare dot. */
export function StatusBadge({ tone, label }: { tone: Tone; label: string }) {
  const t = TONES[tone]
  return (
    <span
      className={`inline-flex h-5 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-pill px-2 text-xs font-medium ${t.bg} ${t.text}`}
    >
      {tone === "running" ? (
        <span className="h-1.5 w-1.5 shrink-0 animate-breathe rounded-pill bg-info" />
      ) : t.icon ? (
        <span className="text-[11px] leading-none">{t.icon}</span>
      ) : null}
      {label}
    </span>
  )
}

export function TypeTag({ type, className = "" }: { type: string; className?: string }) {
  const isLlm = type === "llm"
  return (
    <span
      className={`shrink-0 rounded-sm px-1.5 py-0.5 text-center text-[9.5px] font-semibold ${
        isLlm ? "bg-llm/10 text-llm-t" : "bg-tool/[0.08] text-tool-t"
      } ${className}`}
    >
      {isLlm ? "LLM" : "TOOL"}
    </span>
  )
}

/** Errors dominate warnings; a clean object says so rather than showing nothing. */
export function IssuePill({ errors, warnings }: { errors: number; warnings: number }) {
  if (errors > 0) {
    return (
      <span className="shrink-0 rounded-sm bg-danger-a12 px-[7px] py-px font-mono text-[10.5px] text-danger-t">
        {errors} err{warnings > 0 ? ` · ${warnings} warn` : ""}
      </span>
    )
  }
  if (warnings > 0) {
    return (
      <span className="shrink-0 rounded-sm bg-warning-a12 px-[7px] py-px font-mono text-[10.5px] text-warning-t">
        {warnings} warn
      </span>
    )
  }
  return (
    <span className="shrink-0 rounded-sm bg-surface-2 px-[7px] py-px font-mono text-[10.5px] text-muted-foreground">
      clean
    </span>
  )
}

export function PageTitle({ title, subtitle }: { title: string; subtitle?: React.ReactNode }) {
  return (
    <div>
      <h1 className="m-0 text-xl font-semibold leading-7 text-foreground">{title}</h1>
      {subtitle && <p className="mt-1 text-[12.5px] text-muted-foreground">{subtitle}</p>}
    </div>
  )
}

export function SearchInput({
  value,
  onChange,
  placeholder,
  className = "",
}: {
  value: string
  onChange: (v: string) => void
  placeholder: string
  className?: string
}) {
  return (
    <div className={`relative ${className}`}>
      <Search
        className="pointer-events-none absolute left-2.5 top-1/2 h-[13px] w-[13px] -translate-y-1/2 text-muted-2"
        strokeWidth={2.2}
      />
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full rounded-control border border-border bg-surface py-[7px] pl-[29px] pr-2.5 text-xs text-foreground-2 outline-none placeholder:text-muted-2 focus:border-input"
      />
    </div>
  )
}

export interface SegmentOption {
  value: string
  label: string
  count?: number
}

export function Segmented({
  options,
  value,
  onChange,
  className = "",
}: {
  options: SegmentOption[]
  value: string
  onChange: (v: string) => void
  className?: string
}) {
  return (
    <div className={`flex gap-[3px] rounded-control border border-border bg-hover p-[3px] ${className}`}>
      {options.map((o) => (
        <button
          key={o.value}
          onClick={() => onChange(o.value)}
          aria-pressed={value === o.value}
          className={`flex items-center gap-1.5 rounded-control px-3 py-1 text-[11.5px] font-medium ${
            value === o.value ? "bg-surface text-foreground" : "text-muted-foreground hover:text-foreground"
          }`}
        >
          {o.label}
          {o.count != null && <span className="font-mono text-[10px]">{o.count.toLocaleString()}</span>}
        </button>
      ))}
    </div>
  )
}

export function Kbd({ children }: { children: React.ReactNode }) {
  return (
    <kbd className="rounded-sm border border-border bg-surface px-[5px] py-px font-mono text-[10px] font-normal text-muted-foreground">
      {children}
    </kbd>
  )
}

export function EmptyState({
  message,
  actionLabel,
  onAction,
  dashed = false,
}: {
  message: string
  actionLabel?: string
  onAction?: () => void
  dashed?: boolean
}) {
  return (
    <div
      className={`flex flex-col items-center gap-2.5 px-5 py-9 ${
        dashed ? "rounded-card border border-dashed border-border-2" : "border-t border-border-soft"
      }`}
    >
      <span className="text-[12.5px] text-muted-foreground">{message}</span>
      {actionLabel && onAction && (
        <button
          onClick={onAction}
          className="rounded-control border border-border bg-surface-2 px-3 py-1.5 text-[11.5px] text-foreground-2 hover:border-border-2"
        >
          {actionLabel}
        </button>
      )}
    </div>
  )
}

/** A card: border, no shadow, no tint. */
export function Card({
  children,
  className = "",
  accent = false,
}: {
  children: React.ReactNode
  className?: string
  accent?: boolean
}) {
  return (
    <div
      className={`min-w-0 overflow-hidden rounded-card border bg-surface ${
        accent ? "border-accent-a30" : "border-border"
      } ${className}`}
    >
      {children}
    </div>
  )
}

export function CardHeader({
  title,
  count,
  action,
}: {
  title: string
  count?: React.ReactNode
  action?: React.ReactNode
}) {
  return (
    <div className="flex items-center gap-2 border-b border-border px-[18px] py-[13px]">
      <span className="text-[15px] font-semibold leading-[22px] text-foreground">
        {title}
        {count != null && <span className="ml-1.5 font-normal text-muted-foreground">{count}</span>}
      </span>
      {action && <span className="ml-auto">{action}</span>}
    </div>
  )
}

export function ViewAllButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="border-0 bg-transparent text-[11px] font-medium text-muted-foreground hover:text-accent-t"
    >
      View all →
    </button>
  )
}

export function BackButton({ onClick, title }: { onClick: () => void; title: string }) {
  return (
    <button
      onClick={onClick}
      title={title}
      aria-label={title}
      className="flex h-8 w-8 shrink-0 items-center justify-center rounded-control border border-border bg-surface text-[15px] text-muted-foreground hover:text-foreground"
    >
      ←
    </button>
  )
}

/** Field-type colours — the Schemas distribution bar and type column. */
export function fieldTypeToken(type: unknown): { fill: string; text: string } {
  const t = typeof type === "string" ? type.toLowerCase() : Array.isArray(type) ? "array" : "object"
  if (t === "string") return { fill: "bg-primary", text: "text-accent-t" }
  if (t === "number" || t === "integer" || t === "float") return { fill: "bg-llm", text: "text-llm-t" }
  if (t === "boolean" || t === "bool") return { fill: "bg-tool", text: "text-tool-t" }
  if (t === "array") return { fill: "bg-type-array", text: "text-type-array" }
  if (t === "object" || t === "dict") return { fill: "bg-type-object", text: "text-type-object" }
  return { fill: "bg-muted-2", text: "text-muted-foreground" }
}
