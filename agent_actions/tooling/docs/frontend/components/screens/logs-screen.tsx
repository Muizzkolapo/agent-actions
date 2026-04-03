"use client"

import { useState, useMemo, useCallback, useEffect, useRef } from "react"
import { ChartContainer, ChartTooltip, ChartTooltipContent } from "@/components/ui/chart"
import type { ChartConfig } from "@/components/ui/chart"
import { useCatalogData } from "@/lib/catalog-context"
import {
  ChevronDown,
  ChevronRight,
  ArrowUpDown,
  ArrowLeft,
  AlertTriangle,
  AlertCircle,
  Flame,
  TrendingDown,
  Target,
} from "lucide-react"
import { AreaChart, Area } from "recharts"
import type { ValidationGroup } from "@/lib/mock-data"

// ─── Types ───────────────────────────────────────────────────────────────────

type LogTab = "errors" | "warnings" | "runtime"
type SortDir = "asc" | "desc"

interface SortState<K extends string> {
  key: K
  dir: SortDir
}

interface TopSource {
  target: string
  count: number
  pct: number
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function formatTimestampFull(iso: string): string {
  try {
    const d = new Date(iso)
    return d.toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    })
  } catch {
    return iso
  }
}

/** Safe min/max for large arrays (avoids call-stack overflow from spread) */
function safeMin(arr: number[]): number {
  let v = arr[0]
  for (let i = 1; i < arr.length; i++) if (arr[i] < v) v = arr[i]
  return v
}
function safeMax(arr: number[]): number {
  let v = arr[0]
  for (let i = 1; i < arr.length; i++) if (arr[i] > v) v = arr[i]
  return v
}

/** Build a 7-bucket histogram from timestamps for sparkline rendering */
function buildSparkData(timestamps: string[], buckets = 7): number[] {
  if (timestamps.length === 0) return Array(buckets).fill(0)
  const times = timestamps.map((t) => new Date(t).getTime()).filter((t) => !isNaN(t))
  if (times.length === 0) return Array(buckets).fill(0)
  const min = safeMin(times)
  const max = safeMax(times)
  const range = max - min || 1
  const data = Array(buckets).fill(0) as number[]
  for (const t of times) {
    const idx = Math.min(Math.floor(((t - min) / range) * buckets), buckets - 1)
    data[idx]++
  }
  return data
}

/** Build 12-bucket time series for combined TrendStrip chart */
function buildTimeSeriesData(
  errorGroups: ValidationGroup[],
  warningGroups: ValidationGroup[],
  buckets = 12,
): { bucket: string; errors: number; warnings: number }[] {
  const errorTs = errorGroups.flatMap((g) => g.timestamps)
  const warningTs = warningGroups.flatMap((g) => g.timestamps)
  const allTs = [...errorTs, ...warningTs]
  if (allTs.length === 0) return []

  const times = allTs.map((t) => new Date(t).getTime()).filter((t) => !isNaN(t))
  if (times.length === 0) return []

  const min = safeMin(times)
  const max = safeMax(times)
  const range = max - min || 1

  const errBuckets = Array(buckets).fill(0) as number[]
  const warnBuckets = Array(buckets).fill(0) as number[]

  for (const ts of errorTs) {
    const t = new Date(ts).getTime()
    if (!isNaN(t)) {
      const idx = Math.min(Math.floor(((t - min) / range) * buckets), buckets - 1)
      errBuckets[idx]++
    }
  }
  for (const ts of warningTs) {
    const t = new Date(ts).getTime()
    if (!isNaN(t)) {
      const idx = Math.min(Math.floor(((t - min) / range) * buckets), buckets - 1)
      warnBuckets[idx]++
    }
  }

  return Array.from({ length: buckets }, (_, i) => ({
    bucket: `${i + 1}`,
    errors: errBuckets[i],
    warnings: warnBuckets[i],
  }))
}

/** Build 12-bucket time series for a single category */
function buildSingleSeriesData(
  groups: ValidationGroup[],
  key: string,
  buckets = 12,
): { bucket: string; [k: string]: string | number }[] {
  const allTs = groups.flatMap((g) => g.timestamps)
  if (allTs.length === 0) return []

  const times = allTs.map((t) => new Date(t).getTime()).filter((t) => !isNaN(t))
  if (times.length === 0) return []

  const min = safeMin(times)
  const max = safeMax(times)
  const range = max - min || 1

  const data = Array(buckets).fill(0) as number[]
  for (const ts of allTs) {
    const t = new Date(ts).getTime()
    if (!isNaN(t)) {
      const idx = Math.min(Math.floor(((t - min) / range) * buckets), buckets - 1)
      data[idx]++
    }
  }

  return Array.from({ length: buckets }, (_, i) => ({
    bucket: `${i + 1}`,
    [key]: data[i],
  }))
}

/** Find the top source from validation groups */
function findTopSource(groups: ValidationGroup[]): TopSource | null {
  if (groups.length === 0) return null
  const total = groups.reduce((s, g) => s + g.count, 0)
  const top = [...groups].sort((a, b) => b.count - a.count)[0]
  return { target: top.target, count: top.count, pct: Math.round((top.count / total) * 100) }
}

/** Compute rate per hour from timestamps */
function computeRate(timestamps: string[]): number | null {
  if (timestamps.length < 2) return null
  const times = timestamps.map((t) => new Date(t).getTime()).filter((t) => !isNaN(t)).sort()
  if (times.length < 2) return null
  const hours = (times[times.length - 1] - times[0]) / 3_600_000
  if (hours < 1) return null
  return Math.round(times.length / hours)
}

/** Compute active duration in days from timestamps */
function computeDurationDays(timestamps: string[]): number | null {
  if (timestamps.length < 2) return null
  const times = timestamps.map((t) => new Date(t).getTime()).filter((t) => !isNaN(t)).sort()
  if (times.length < 2) return null
  const days = Math.ceil((times[times.length - 1] - times[0]) / 86_400_000)
  return days > 0 ? days : null
}

// ─── Sparkline ───────────────────────────────────────────────────────────────

function MiniSparkline({ data, color, width = 80, height = 24 }: { data: number[]; color: string; width?: number; height?: number }) {
  const max = Math.max(safeMax(data), 1)
  const step = width / (data.length - 1 || 1)
  const points = data.map((v, i) => `${i * step},${height - (v / max) * height * 0.7 - height * 0.15}`).join(" ")
  return (
    <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" style={{ width, height }} className="shrink-0">
      <polyline fill="none" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" points={points} opacity={0.7} />
    </svg>
  )
}

// ─── Chart Configs ───────────────────────────────────────────────────────────

const trendChartConfig = {
  errors: { label: "Errors", color: "hsl(var(--destructive))" },
  warnings: { label: "Warnings", color: "hsl(var(--warning))" },
} satisfies ChartConfig

const errorsChartConfig = {
  errors: { label: "Errors", color: "hsl(var(--destructive))" },
} satisfies ChartConfig

const warningsChartConfig = {
  warnings: { label: "Warnings", color: "hsl(var(--warning))" },
} satisfies ChartConfig

// ─── Main Component ──────────────────────────────────────────────────────────

export function LogsScreen() {
  const { validationErrorGroups, validationWarningGroups, runtimeErrorGroups, runtimeWarningGroups, stats } = useCatalogData()
  const [activeTab, setActiveTab] = useState<LogTab>("errors")
  const [focusedTarget, setFocusedTarget] = useState<string | null>(null)
  const [selectedGroup, setSelectedGroup] = useState<ValidationGroup | null>(null)

  const trendData = useMemo(
    () => buildTimeSeriesData(validationErrorGroups, validationWarningGroups),
    [validationErrorGroups, validationWarningGroups],
  )
  const hasTrend = trendData.length > 0

  const errorTopSource = useMemo(() => findTopSource(validationErrorGroups), [validationErrorGroups])
  const warningTopSource = useMemo(() => findTopSource(validationWarningGroups), [validationWarningGroups])
  const errorSparkData = useMemo(() => buildSparkData(validationErrorGroups.flatMap((g) => g.timestamps)), [validationErrorGroups])
  const warningSparkData = useMemo(() => buildSparkData(validationWarningGroups.flatMap((g) => g.timestamps)), [validationWarningGroups])

  const runtimeCount = runtimeErrorGroups.reduce((s, g) => s + g.count, 0) + runtimeWarningGroups.reduce((s, g) => s + g.count, 0)
  const tabs: { id: LogTab; label: string; count: number; icon: React.ReactNode; color: string }[] = [
    { id: "errors", label: "Errors", count: stats.validation_errors, icon: <AlertCircle className="h-3 w-3" />, color: "hsl(var(--destructive))" },
    { id: "warnings", label: "Warnings", count: stats.validation_warnings, icon: <AlertTriangle className="h-3 w-3" />, color: "hsl(var(--warning))" },
    { id: "runtime", label: "Runtime", count: runtimeCount, icon: <Flame className="h-3 w-3" />, color: "hsl(var(--warning))" },
  ]

  // Stable reference for clearing focus (avoids re-triggering useEffect)
  const clearFocus = useCallback(() => setFocusedTarget(null), [])

  // L1: Navigate to a tab, optionally focusing a specific target row
  const navigateToTab = useCallback((tab: LogTab, target?: string) => {
    setActiveTab(tab)
    setFocusedTarget(target ?? null)
    setSelectedGroup(null)
  }, [])

  const runtimeAllGroups = useMemo(
    () => [...runtimeErrorGroups, ...runtimeWarningGroups].sort((a, b) => b.count - a.count),
    [runtimeErrorGroups, runtimeWarningGroups],
  )

  const activeGroups = useMemo(() => {
    if (activeTab === "errors") return validationErrorGroups
    if (activeTab === "warnings") return validationWarningGroups
    return runtimeAllGroups
  }, [activeTab, validationErrorGroups, validationWarningGroups, runtimeAllGroups])

  const totalForActiveTab = useMemo(
    () => activeGroups.reduce((s, g) => s + g.count, 0),
    [activeGroups],
  )

  // L3: SourceDetail view replaces the entire dashboard
  if (selectedGroup) {
    return (
      <SourceDetail
        group={selectedGroup}
        colorVar={activeTab === "errors" ? "--destructive" : "--warning"}
        totalCount={totalForActiveTab}
        onBack={() => setSelectedGroup(null)}
      />
    )
  }

  return (
    <div className="flex flex-col gap-4">
      {/* Title */}
      <div>
        <h1 className="text-lg font-semibold tracking-tight text-foreground">Logs & Events</h1>
        <p className="text-xs text-muted-foreground mt-0.5">Diagnostic overview — validation errors and warnings</p>
      </div>

      {/* ── Health Summary Strip ──────────────────────────────────────── */}
      <div className="grid grid-cols-2 gap-3">
        <HealthCard
          icon={<AlertCircle className="h-4 w-4" />}
          label="Errors"
          value={stats.validation_errors}
          accent="destructive"
          sub={validationErrorGroups.length > 0 ? `${validationErrorGroups.length} distinct sources` : "No errors"}
          topSource={errorTopSource}
          sparkData={errorSparkData}
          onClick={() => navigateToTab("errors")}
        />
        <HealthCard
          icon={<AlertTriangle className="h-4 w-4" />}
          label="Warnings"
          value={stats.validation_warnings}
          accent="warning"
          sub={validationWarningGroups.length > 0 ? `${validationWarningGroups.length} distinct sources` : "No warnings"}
          topSource={warningTopSource}
          sparkData={warningSparkData}
          onClick={() => navigateToTab("warnings")}
        />
      </div>

      {/* ── Diagnostic Findings ───────────────────────────────────────── */}
      <DiagnosticFindings
        errorGroups={validationErrorGroups}
        warningGroups={validationWarningGroups}
        errorTopSource={errorTopSource}
        warningTopSource={warningTopSource}
        stats={stats}
        onNavigate={navigateToTab}
      />

      {/* ── Trend Strip (combined area chart) ─────────────────────────── */}
      {hasTrend && (
        <div className="rounded-lg border border-border bg-card p-3">
          <div className="flex items-center justify-between mb-2">
            <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">Issue Trend</span>
            <span className="text-[10px] text-muted-foreground tabular-nums">
              {(stats.validation_errors + stats.validation_warnings).toLocaleString()} total issues
            </span>
          </div>
          <ChartContainer config={trendChartConfig} className="h-[80px] w-full !aspect-auto">
            <AreaChart data={trendData} margin={{ top: 0, right: 0, bottom: 0, left: 0 }}>
              <defs>
                <linearGradient id="fillErrors" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="var(--color-errors)" stopOpacity={0.35} />
                  <stop offset="100%" stopColor="var(--color-errors)" stopOpacity={0.02} />
                </linearGradient>
                <linearGradient id="fillWarnings" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="var(--color-warnings)" stopOpacity={0.25} />
                  <stop offset="100%" stopColor="var(--color-warnings)" stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <ChartTooltip content={<ChartTooltipContent />} />
              <Area
                dataKey="warnings"
                type="monotone"
                fill="url(#fillWarnings)"
                stroke="var(--color-warnings)"
                strokeWidth={1.5}
              />
              <Area
                dataKey="errors"
                type="monotone"
                fill="url(#fillErrors)"
                stroke="var(--color-errors)"
                strokeWidth={1.5}
              />
            </AreaChart>
          </ChartContainer>
          <div className="flex items-center justify-between mt-1.5">
            <span className="text-[9px] text-muted-foreground/50">Earlier</span>
            <span className="text-[9px] text-muted-foreground/50">Now</span>
          </div>
        </div>
      )}

      {/* ── Tab Bar ───────────────────────────────────────────────────── */}
      <div className="flex gap-1">
        {tabs.map((tab) => {
          const isActive = activeTab === tab.id
          const isUrgent = tab.id === "errors" && tab.count > 0
          return (
            <button
              key={tab.id}
              onClick={() => navigateToTab(tab.id)}
              className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-all ${
                isActive ? "" : "text-muted-foreground hover:bg-accent hover:text-foreground"
              }`}
              style={
                isActive
                  ? {
                      backgroundColor: `color-mix(in srgb, ${tab.color} 12%, transparent)`,
                      color: tab.color,
                      boxShadow: `inset 0 0 0 1px color-mix(in srgb, ${tab.color} 30%, transparent)`,
                    }
                  : undefined
              }
            >
              {tab.icon}
              {tab.label}
              <span
                className={`text-[10px] tabular-nums font-semibold rounded-full px-1.5 py-px ${
                  isActive
                    ? "opacity-80"
                    : isUrgent
                      ? "bg-[hsl(var(--destructive))]/10 text-[hsl(var(--destructive))]"
                      : "opacity-50"
                }`}
              >
                {tab.count.toLocaleString()}
              </span>
            </button>
          )
        })}
      </div>

      {/* ── Tab Content ───────────────────────────────────────────────── */}
      <div className="rounded-lg border border-border bg-card overflow-hidden">
        {activeTab === "errors" && (
          <ValidationBreakdown
            groups={validationErrorGroups}
            colorVar="--destructive"
            seriesKey="errors"
            chartConfig={errorsChartConfig}
            emptyLabel="No errors — looking clean"
            focusedTarget={focusedTarget}
            onClearFocus={clearFocus}
            onViewDetail={setSelectedGroup}
          />
        )}
        {activeTab === "warnings" && (
          <ValidationBreakdown
            groups={validationWarningGroups}
            colorVar="--warning"
            seriesKey="warnings"
            chartConfig={warningsChartConfig}
            emptyLabel="No warnings"
            focusedTarget={focusedTarget}
            onClearFocus={clearFocus}
            onViewDetail={setSelectedGroup}
          />
        )}
        {activeTab === "runtime" && (
          <ValidationBreakdown
            groups={runtimeAllGroups}
            colorVar="--warning"
            seriesKey="warnings"
            chartConfig={warningsChartConfig}
            emptyLabel="No runtime warnings or errors"
            focusedTarget={focusedTarget}
            onClearFocus={clearFocus}
            onViewDetail={setSelectedGroup}
          />
        )}
      </div>
    </div>
  )
}

// ─── Health Card ─────────────────────────────────────────────────────────────

function HealthCard({
  icon,
  label,
  value,
  accent,
  sub,
  topSource,
  sparkData,
  onClick,
}: {
  icon: React.ReactNode
  label: string
  value: number
  accent: "destructive" | "warning"
  sub: string
  topSource?: TopSource | null
  sparkData: number[]
  onClick?: () => void
}) {
  const accentVar = `var(--${accent})`
  const color = `hsl(${accentVar})`
  const hasIssues = value > 0
  const iconBgMap: Record<string, string> = {
    destructive: "bg-[hsl(var(--destructive))]/10",
    warning: "bg-[hsl(var(--warning))]/10",
  }
  const iconFgMap: Record<string, string> = {
    destructive: "text-[hsl(var(--destructive))]",
    warning: "text-[hsl(var(--warning))]",
  }

  return (
    <button
      type="button"
      onClick={onClick}
      className="group relative rounded-lg border border-border bg-card p-4 text-left overflow-hidden cursor-pointer hover:border-foreground/20 hover:shadow-sm transition-all"
      style={hasIssues ? { borderLeft: `3px solid ${color}` } : undefined}
    >
      {/* Sparkline watermark */}
      <div className="absolute bottom-0 right-0 w-24 h-10 opacity-[0.12]">
        <MiniSparkline data={sparkData} color={color} width={96} height={40} />
      </div>
      <div className="flex items-center gap-2 mb-2">
        <div className={`flex items-center justify-center h-7 w-7 rounded-md ${iconBgMap[accent]}`}>
          <span className={iconFgMap[accent]}>{icon}</span>
        </div>
        <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-medium">{label}</span>
      </div>
      <div
        className="text-2xl font-semibold font-mono tabular-nums"
        style={hasIssues ? { color } : undefined}
      >
        {value.toLocaleString()}
      </div>
      <p className="text-[11px] mt-1 text-muted-foreground">{sub}</p>
      {topSource && (
        <p className="text-[10px] mt-0.5 text-muted-foreground truncate">
          Top: <span className="font-mono font-medium text-foreground">{topSource.target}</span>
          <span className="tabular-nums ml-1 opacity-60">({topSource.pct}%)</span>
        </p>
      )}
    </button>
  )
}

// ─── Diagnostic Findings ─────────────────────────────────────────────────────

function DiagnosticFindings({
  errorGroups,
  warningGroups,
  errorTopSource,
  warningTopSource,
  stats,
  onNavigate,
}: {
  errorGroups: ValidationGroup[]
  warningGroups: ValidationGroup[]
  errorTopSource: TopSource | null
  warningTopSource: TopSource | null
  stats: { validation_errors: number; validation_warnings: number }
  onNavigate: (tab: LogTab, target?: string) => void
}) {
  const findings: { icon: React.ReactNode; text: string; severity: "destructive" | "warning" | "success"; onClick?: () => void }[] = []

  // Error findings
  if (stats.validation_errors > 0 && errorTopSource) {
    const sourceText = errorGroups.length === 1
      ? `1 error source: ${errorTopSource.target}`
      : `${errorGroups.length} error sources \u00b7 top: ${errorTopSource.target} (${errorTopSource.pct}%)`
    findings.push({
      icon: <AlertCircle className="h-3 w-3" />,
      text: sourceText,
      severity: "destructive",
      onClick: () => onNavigate("errors", errorTopSource.target),
    })
  } else if (stats.validation_errors === 0) {
    findings.push({
      icon: <TrendingDown className="h-3 w-3" />,
      text: "No validation errors",
      severity: "success",
    })
  }

  // Warning concentration finding
  if (warningTopSource && warningTopSource.pct >= 80) {
    findings.push({
      icon: <Flame className="h-3 w-3" />,
      text: `Warning hotspot \u00b7 ${warningTopSource.target} accounts for ${warningTopSource.pct}%`,
      severity: "warning",
      onClick: () => onNavigate("warnings", warningTopSource.target),
    })
  } else if (stats.validation_warnings > 0 && warningTopSource) {
    findings.push({
      icon: <AlertTriangle className="h-3 w-3" />,
      text: `${warningGroups.length} warning sources \u00b7 ${stats.validation_warnings.toLocaleString()} total`,
      severity: "warning",
      onClick: () => onNavigate("warnings", warningTopSource.target),
    })
  }

  if (findings.length === 0) return null

  const severityColor: Record<string, string> = {
    destructive: "hsl(var(--destructive))",
    warning: "hsl(var(--warning))",
    success: "hsl(var(--success))",
  }

  return (
    <div className="flex items-center gap-2 flex-wrap">
      {findings.map((f, i) => (
        <button
          type="button"
          key={i}
          onClick={f.onClick}
          className={`inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-[11px] font-medium transition-all ${f.onClick ? "cursor-pointer hover:opacity-80" : ""}`}
          style={{
            backgroundColor: `color-mix(in srgb, ${severityColor[f.severity]} 8%, transparent)`,
            color: severityColor[f.severity],
            boxShadow: `inset 0 0 0 1px color-mix(in srgb, ${severityColor[f.severity]} 15%, transparent)`,
          }}
        >
          {f.icon}
          <span>{f.text}</span>
        </button>
      ))}
    </div>
  )
}

// ─── Sortable Header ─────────────────────────────────────────────────────────

function SortableHeader<K extends string>({
  label,
  sortKey,
  current,
  onSort,
  align = "left",
}: {
  label: string
  sortKey: K
  current: SortState<K>
  onSort: (key: K) => void
  align?: "left" | "center"
}) {
  const active = current.key === sortKey
  return (
    <th className={`text-${align} cursor-pointer select-none hover:text-foreground transition-colors`} onClick={() => onSort(sortKey)}>
      <span className="inline-flex items-center gap-1">
        {label}
        <ArrowUpDown className={`h-3 w-3 ${active ? "opacity-80" : "opacity-30"}`} />
      </span>
    </th>
  )
}

// ─── Validation Breakdown (enhanced — shared for Errors & Warnings) ─────────

type VGSortKey = "count" | "target"

function ValidationBreakdown({
  groups,
  colorVar,
  seriesKey,
  chartConfig,
  emptyLabel,
  focusedTarget,
  onClearFocus,
  onViewDetail,
}: {
  groups: ValidationGroup[]
  colorVar: string
  seriesKey: string
  chartConfig: ChartConfig
  emptyLabel: string
  focusedTarget?: string | null
  onClearFocus?: () => void
  onViewDetail?: (group: ValidationGroup) => void
}) {
  const [sort, setSort] = useState<SortState<VGSortKey>>({ key: "count", dir: "desc" })
  const [expandedTarget, setExpandedTarget] = useState<string | null>(null)
  const tableRef = useRef<HTMLTableElement>(null)

  // Apply focusedTarget from parent (L1 drill-down) — auto-expand the target row
  useEffect(() => {
    if (focusedTarget) {
      setExpandedTarget(focusedTarget)
      // Scroll first, then clear focus — avoids parent re-render racing with RAF
      requestAnimationFrame(() => {
        const row = tableRef.current?.querySelector(`[data-target="${CSS.escape(focusedTarget)}"]`)
        row?.scrollIntoView({ behavior: "smooth", block: "nearest" })
        onClearFocus?.()
      })
    }
  }, [focusedTarget, onClearFocus])

  const toggleSort = useCallback(
    (key: VGSortKey) => {
      setSort((s) => (s.key === key ? { key, dir: s.dir === "asc" ? "desc" : "asc" } : { key, dir: "desc" }))
    },
    [],
  )

  const sorted = useMemo(() => {
    const arr = [...groups]
    const dir = sort.dir === "asc" ? 1 : -1
    if (sort.key === "count") {
      arr.sort((a, b) => dir * (a.count - b.count))
    } else {
      arr.sort((a, b) => dir * a.target.localeCompare(b.target))
    }
    return arr
  }, [groups, sort])

  const totalCount = groups.reduce((s, g) => s + g.count, 0)
  const color = `hsl(var(${colorVar}))`

  const breakdownData = useMemo(() => buildSingleSeriesData(groups, seriesKey), [groups, seriesKey])
  const hasBreakdownChart = breakdownData.length > 0

  const gradientId = `fill-${seriesKey}`

  // Detect hotspot: top source accounting for > 60%
  const hotspot = useMemo(() => {
    if (groups.length < 2) return null
    const top = [...groups].sort((a, b) => b.count - a.count)[0]
    const pct = totalCount > 0 ? Math.round((top.count / totalCount) * 100) : 0
    if (pct < 60) return null
    return { target: top.target, count: top.count, distinctCount: top.distinctCount, pct }
  }, [groups, totalCount])

  if (groups.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
        <div className="text-sm">{emptyLabel}</div>
      </div>
    )
  }

  return (
    <div className="flex flex-col">
      {/* Hotspot callout */}
      {hotspot && (
        <button
          type="button"
          onClick={() => setExpandedTarget(hotspot.target)}
          className="mx-3 mt-3 rounded-md px-3 py-2.5 flex items-center gap-3 text-left cursor-pointer hover:opacity-90 transition-opacity"
          style={{
            backgroundColor: `color-mix(in srgb, ${color} 6%, transparent)`,
            boxShadow: `inset 0 0 0 1px color-mix(in srgb, ${color} 15%, transparent)`,
          }}
        >
          <div
            className="flex items-center justify-center h-6 w-6 rounded shrink-0"
            style={{ backgroundColor: `color-mix(in srgb, ${color} 15%, transparent)` }}
          >
            <Target className="h-3.5 w-3.5" style={{ color }} />
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-[10px] font-semibold uppercase tracking-wider" style={{ color }}>Hotspot</span>
              <span className="text-xs font-mono font-medium text-foreground truncate">{hotspot.target}</span>
            </div>
            <p className="text-[10px] text-muted-foreground mt-0.5">
              Accounts for <span className="font-semibold tabular-nums" style={{ color }}>{hotspot.pct}%</span> of all {seriesKey} ({hotspot.count.toLocaleString()} of {totalCount.toLocaleString()})
              {hotspot.distinctCount > 1 && <span> {"\u00b7"} {hotspot.distinctCount} distinct messages</span>}
            </p>
          </div>
        </button>
      )}

      {/* Breakdown area chart */}
      {hasBreakdownChart && (
        <div className="px-4 py-3 border-b border-border">
          <div className="flex items-center justify-between mb-1">
            <span className="text-[10px] text-muted-foreground">Distribution over time</span>
            <span className="text-[10px] text-muted-foreground tabular-nums">
              {totalCount.toLocaleString()} total
            </span>
          </div>
          <ChartContainer config={chartConfig} className="h-[52px] w-full !aspect-auto">
            <AreaChart data={breakdownData} margin={{ top: 0, right: 0, bottom: 0, left: 0 }}>
              <defs>
                <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={`var(--color-${seriesKey})`} stopOpacity={0.3} />
                  <stop offset="100%" stopColor={`var(--color-${seriesKey})`} stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <ChartTooltip content={<ChartTooltipContent />} />
              <Area
                dataKey={seriesKey}
                type="monotone"
                fill={`url(#${gradientId})`}
                stroke={`var(--color-${seriesKey})`}
                strokeWidth={1.5}
              />
            </AreaChart>
          </ChartContainer>
        </div>
      )}

      {/* Table */}
      <table ref={tableRef} className="w-full dense-table">
        <thead>
          <tr>
            <SortableHeader label="Count" sortKey="count" current={sort} onSort={toggleSort} align="center" />
            <th className="text-left w-28">Proportion</th>
            <SortableHeader label="Target" sortKey="target" current={sort} onSort={toggleSort} />
            <th className="text-left">Sample</th>
            <th className="text-center w-10"></th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((g) => {
            const isExpanded = expandedTarget === g.target
            return (
              <ValidationGroupRow
                key={g.target}
                group={g}
                color={color}
                colorVar={colorVar}
                totalCount={totalCount}
                isExpanded={isExpanded}
                onToggle={() => setExpandedTarget(isExpanded ? null : g.target)}
                onViewDetail={onViewDetail}
              />
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

// ─── Validation Group Row ────────────────────────────────────────────────────

function ValidationGroupRow({
  group,
  color,
  colorVar,
  totalCount,
  isExpanded,
  onToggle,
  onViewDetail,
}: {
  group: ValidationGroup
  color: string
  colorVar: string
  totalCount: number
  isExpanded: boolean
  onToggle: () => void
  onViewDetail?: (group: ValidationGroup) => void
}) {
  const sparkData = useMemo(() => buildSparkData(group.timestamps), [group.timestamps])
  const hasSparkData = sparkData.some((v) => v > 0)
  const proportion = totalCount > 0 ? (group.count / totalCount) * 100 : 0
  const isDominant = proportion >= 60
  const rate = useMemo(() => computeRate(group.timestamps), [group.timestamps])
  const durationDays = useMemo(() => computeDurationDays(group.timestamps), [group.timestamps])
  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onToggle() }
  }, [onToggle])

  return (
    <>
      <tr data-target={group.target} className="hover:bg-accent/30 transition-colors cursor-pointer" tabIndex={0} onClick={onToggle} onKeyDown={handleKeyDown}>
        <td className="text-center w-20">
          <span
            className="inline-block rounded-md px-2 py-0.5 text-[11px] font-semibold tabular-nums min-w-[2.5rem]"
            style={{
              backgroundColor: `color-mix(in srgb, ${color} ${isDominant ? 18 : 12}%, transparent)`,
              color,
            }}
          >
            {group.count.toLocaleString()}
          </span>
        </td>
        <td className="w-28">
          <div className="flex items-center gap-2">
            <div className="flex-1 h-1.5 rounded-full bg-secondary overflow-hidden">
              <div
                className="h-full rounded-full transition-all duration-500"
                style={{
                  width: `${proportion}%`,
                  backgroundColor: color,
                  opacity: isDominant ? 1 : 0.7,
                }}
              />
            </div>
            <span className="text-[10px] tabular-nums text-muted-foreground shrink-0 w-7 text-right">
              {Math.round(proportion)}%
            </span>
          </div>
        </td>
        <td>
          <span className="font-mono font-medium text-[11px] text-foreground">
            {group.target}
          </span>
        </td>
        <td className="text-muted-foreground max-w-[350px]">
          {group.sample ? (
            <span className="line-clamp-1">{group.sample}</span>
          ) : (
            <span className="italic text-muted-foreground/40">No message captured</span>
          )}
        </td>
        <td className="text-center w-10">
          {isExpanded ? (
            <ChevronDown className="h-3.5 w-3.5 text-muted-foreground mx-auto" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5 text-muted-foreground/40 mx-auto" />
          )}
        </td>
      </tr>

      {/* Expanded detail panel */}
      {isExpanded && (
        <tr>
          <td colSpan={5} className="!p-0">
            <div
              className="border-t border-border px-4 py-3 space-y-2.5"
              style={{
                backgroundColor: `color-mix(in srgb, ${color} 3%, transparent)`,
                borderLeft: `3px solid ${color}`,
              }}
            >
              {/* Stats row */}
              <div className="flex items-center gap-4 text-[11px] flex-wrap">
                <div className="flex items-center gap-1.5">
                  <span className="text-muted-foreground">Occurrences:</span>
                  <span className="font-semibold tabular-nums" style={{ color }}>{group.count.toLocaleString()}</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <span className="text-muted-foreground">Share:</span>
                  <span className="font-semibold tabular-nums">{Math.round((group.count / totalCount) * 100)}%</span>
                </div>
                {group.distinctCount > 0 && (
                  <div className="flex items-center gap-1.5">
                    <span className="text-muted-foreground">Distinct messages:</span>
                    <span className="font-semibold tabular-nums">{group.distinctCount}</span>
                  </div>
                )}
                {rate != null && (
                  <div className="flex items-center gap-1.5">
                    <span className="text-muted-foreground">Rate:</span>
                    <span className="font-semibold tabular-nums">~{rate}/hr</span>
                  </div>
                )}
                {durationDays != null && (
                  <div className="flex items-center gap-1.5">
                    <span className="text-muted-foreground">Active:</span>
                    <span className="font-semibold tabular-nums">{durationDays}d</span>
                  </div>
                )}
                {hasSparkData && (
                  <div className="flex items-center gap-1.5 ml-auto">
                    <span className="text-muted-foreground text-[10px]">Distribution:</span>
                    <MiniSparkline data={sparkData} color={color} width={80} height={16} />
                  </div>
                )}
              </div>

              {/* Sample message block */}
              {group.sample && (
                <div>
                  <div className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold mb-1">Sample message</div>
                  <div
                    className="rounded-md px-3 py-2 text-[11px] font-mono leading-relaxed border"
                    style={{
                      backgroundColor: `color-mix(in srgb, ${color} 4%, hsl(var(--card)))`,
                      borderColor: `color-mix(in srgb, ${color} 15%, transparent)`,
                    }}
                  >
                    <span className="text-foreground">{group.sample}</span>
                  </div>
                </div>
              )}

              {/* View all messages link (L2 → L3) */}
              {onViewDetail && group.messages.length > 1 && (
                <button
                  type="button"
                  onClick={(e) => { e.stopPropagation(); onViewDetail(group) }}
                  className="inline-flex items-center gap-1 text-[11px] font-medium hover:underline transition-colors"
                  style={{ color }}
                >
                  View all {group.messages.length} messages &rarr;
                </button>
              )}

              {/* Temporal info */}
              {group.timestamps.length > 0 && (
                <div className="flex items-center gap-4 text-[10px] text-muted-foreground">
                  <span>First seen: {formatTimestampFull(group.timestamps[0])}</span>
                  {group.timestamps.length > 1 && (
                    <span>Last seen: {formatTimestampFull(group.timestamps[group.timestamps.length - 1])}</span>
                  )}
                </div>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  )
}

// ─── Source Detail (L3 — full message list) ─────────────────────────────────

type MsgSortKey = "count" | "message"

function SourceDetail({
  group,
  colorVar,
  totalCount,
  onBack,
}: {
  group: ValidationGroup
  colorVar: string
  totalCount: number
  onBack: () => void
}) {
  const [sort, setSort] = useState<SortState<MsgSortKey>>({ key: "count", dir: "desc" })
  const color = `hsl(var(${colorVar}))`

  const toggleSort = useCallback(
    (key: MsgSortKey) => {
      setSort((s) => (s.key === key ? { key, dir: s.dir === "asc" ? "desc" : "asc" } : { key, dir: "desc" }))
    },
    [],
  )

  const sortedMessages = useMemo(() => {
    const arr = [...group.messages]
    const dir = sort.dir === "asc" ? 1 : -1
    if (sort.key === "count") {
      arr.sort((a, b) => dir * (a.count - b.count))
    } else {
      arr.sort((a, b) => dir * a.text.localeCompare(b.text))
    }
    return arr
  }, [group.messages, sort])

  const sparkData = buildSparkData(group.timestamps, 12)
  const proportion = totalCount > 0 ? Math.round((group.count / totalCount) * 100) : 0
  const rate = computeRate(group.timestamps)
  const durationDays = computeDurationDays(group.timestamps)

  return (
    <div className="flex flex-col gap-4">
      {/* Header */}
      <div className="flex items-center gap-4">
        <button
          onClick={onBack}
          className="flex h-8 w-8 items-center justify-center rounded-lg border border-border bg-card text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
        >
          <ArrowLeft className="h-4 w-4" />
        </button>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2.5">
            <h1 className="text-lg font-mono font-semibold text-foreground truncate">{group.target}</h1>
            <span
              className="inline-block rounded-md px-2 py-0.5 text-[11px] font-semibold tabular-nums"
              style={{
                backgroundColor: `color-mix(in srgb, ${color} 15%, transparent)`,
                color,
              }}
            >
              {group.count.toLocaleString()}
            </span>
          </div>
          <p className="text-xs text-muted-foreground mt-0.5">
            {group.messages.length} distinct message{group.messages.length !== 1 ? "s" : ""} &middot; {proportion}% of total
          </p>
        </div>
      </div>

      {/* Stats strip */}
      <div className="rounded-lg border border-border bg-card p-3">
        <div className="flex items-center gap-5 text-[11px] flex-wrap">
          <div className="flex items-center gap-1.5">
            <span className="text-muted-foreground">Occurrences:</span>
            <span className="font-semibold tabular-nums" style={{ color }}>{group.count.toLocaleString()}</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="text-muted-foreground">Share:</span>
            <span className="font-semibold tabular-nums">{proportion}%</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="text-muted-foreground">Distinct messages:</span>
            <span className="font-semibold tabular-nums">{group.messages.length}</span>
          </div>
          {rate && (
            <div className="flex items-center gap-1.5">
              <span className="text-muted-foreground">Rate:</span>
              <span className="font-semibold tabular-nums">~{rate}/hr</span>
            </div>
          )}
          {durationDays && (
            <div className="flex items-center gap-1.5">
              <span className="text-muted-foreground">Active:</span>
              <span className="font-semibold tabular-nums">{durationDays}d</span>
            </div>
          )}
          <div className="flex items-center gap-1.5 ml-auto">
            <span className="text-muted-foreground text-[10px]">Distribution:</span>
            <MiniSparkline data={sparkData} color={color} width={200} height={28} />
          </div>
        </div>
      </div>

      {/* Messages table */}
      <div className="rounded-lg border border-border bg-card overflow-hidden">
        <table className="w-full dense-table">
          <thead>
            <tr>
              <SortableHeader label="Message" sortKey="message" current={sort} onSort={toggleSort} />
              <SortableHeader label="Count" sortKey="count" current={sort} onSort={toggleSort} align="center" />
              <th className="text-left">First Seen</th>
              <th className="text-left">Last Seen</th>
            </tr>
          </thead>
          <tbody>
            {sortedMessages.map((msg) => (
              <tr key={msg.text} className="hover:bg-accent/30 transition-colors">
                <td className="max-w-[500px]">
                  <span className="font-mono text-[11px] text-foreground break-words">{msg.text}</span>
                </td>
                <td className="text-center w-20">
                  <span
                    className="inline-block rounded-md px-2 py-0.5 text-[11px] font-semibold tabular-nums min-w-[2.5rem]"
                    style={{
                      backgroundColor: `color-mix(in srgb, ${color} 12%, transparent)`,
                      color,
                    }}
                  >
                    {msg.count.toLocaleString()}
                  </span>
                </td>
                <td className="text-[11px] text-muted-foreground whitespace-nowrap">
                  {msg.firstSeen ? formatTimestampFull(msg.firstSeen) : "\u2014"}
                </td>
                <td className="text-[11px] text-muted-foreground whitespace-nowrap">
                  {msg.lastSeen ? formatTimestampFull(msg.lastSeen) : "\u2014"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Temporal footer */}
      {group.timestamps.length > 0 && (
        <div className="flex items-center gap-4 text-[10px] text-muted-foreground px-1">
          <span>Overall first seen: {formatTimestampFull(group.timestamps[0])}</span>
          {group.timestamps.length > 1 && (
            <span>Overall last seen: {formatTimestampFull(group.timestamps[group.timestamps.length - 1])}</span>
          )}
        </div>
      )}
    </div>
  )
}
