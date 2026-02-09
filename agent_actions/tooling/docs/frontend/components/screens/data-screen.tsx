"use client"

import React, { useState, useMemo } from "react"
import {
  Database,
  ArrowLeft,
  ArrowRight,
  FileJson,
  HardDrive,
  Search,
  ChevronDown,
  ChevronUp,
  Rows3,
} from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { useCatalogData } from "@/lib/catalog-context"
import type { DataNode, WorkflowDataSummary } from "@/lib/mock-data"

const NODES_PER_PAGE = 6
const RECORDS_PER_PAGE = 5

export function DataScreen() {
  const { workflowData } = useCatalogData()
  const [selected, setSelected] = useState<DataNode | null>(null)
  const [search, setSearch] = useState("")
  const [workflowFilter, setWorkflowFilter] = useState<string>("all")
  const [expandedWorkflows, setExpandedWorkflows] = useState<Record<string, boolean>>({})

  const allNodes = useMemo(
    () => workflowData.flatMap((wf) => wf.nodes),
    [workflowData],
  )

  const totalRecords = useMemo(
    () => allNodes.reduce((sum, n) => sum + n.recordCount, 0),
    [allNodes],
  )

  // Filter nodes by search
  const filteredWorkflows = useMemo(() => {
    return workflowData
      .filter((wf) => workflowFilter === "all" || wf.workflow === workflowFilter)
      .map((wf) => {
        if (!search) return wf
        const filteredNodes = wf.nodes.filter(
          (n) =>
            n.node.toLowerCase().includes(search.toLowerCase()) ||
            n.files.some((f) => f.toLowerCase().includes(search.toLowerCase())),
        )
        return { ...wf, nodes: filteredNodes }
      })
      .filter((wf) => wf.nodes.length > 0)
  }, [workflowData, search, workflowFilter])

  const filteredNodeCount = filteredWorkflows.reduce((s, wf) => s + wf.nodes.length, 0)

  if (selected) {
    const parentWf = workflowData.find((wf) => wf.workflow === selected.workflow)
    return <NodeDetail node={selected} workflow={parentWf} onBack={() => setSelected(null)} />
  }

  if (allNodes.length === 0) {
    return (
      <div className="flex flex-col gap-6">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-foreground">Data Explorer</h1>
          <p className="text-sm text-muted-foreground mt-1">No data found</p>
        </div>
        <div className="rounded-xl border border-border bg-card p-8 text-center">
          <Database className="h-10 w-10 text-muted-foreground/40 mx-auto mb-3" />
          <p className="text-sm text-muted-foreground">
            No workflow output data available. Run a workflow first, then regenerate docs.
          </p>
        </div>
      </div>
    )
  }

  const toggleWorkflow = (wf: string) => {
    setExpandedWorkflows((prev) => ({ ...prev, [wf]: !prev[wf] }))
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">Data Explorer</h1>
        <p className="text-sm text-muted-foreground mt-1">
          {allNodes.length} node{allNodes.length !== 1 ? "s" : ""} across{" "}
          {workflowData.length} workflow{workflowData.length !== 1 ? "s" : ""}
          <span className="text-muted-foreground/60">
            {" "}{"\u00B7"} {totalRecords.toLocaleString()} total records
          </span>
        </p>
      </div>

      {/* Search + workflow filter */}
      <div className="flex items-center gap-3 flex-wrap">
        <div className="relative flex-1 min-w-[200px]">
          <Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Filter by node name or file..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9 h-9 bg-secondary border-0 text-sm placeholder:text-muted-foreground"
          />
        </div>
        <div className="flex gap-1">
          <FilterChip
            label="all"
            count={allNodes.length}
            active={workflowFilter === "all"}
            onClick={() => setWorkflowFilter("all")}
          />
          {workflowData.map((wf) => (
            <FilterChip
              key={wf.workflow}
              label={wf.workflow}
              count={wf.nodes.length}
              active={workflowFilter === wf.workflow}
              onClick={() => setWorkflowFilter(wf.workflow)}
            />
          ))}
        </div>
      </div>

      {/* Results */}
      {filteredWorkflows.length === 0 ? (
        <div className="rounded-xl border border-border bg-card p-8 text-center">
          <p className="text-sm text-muted-foreground">No nodes match the current filters</p>
        </div>
      ) : (
        filteredWorkflows.map((wf) => (
          <WorkflowSection
            key={wf.workflow}
            wf={wf}
            expanded={expandedWorkflows[wf.workflow] ?? false}
            onToggle={() => toggleWorkflow(wf.workflow)}
            onSelect={setSelected}
          />
        ))
      )}

      {search && (
        <p className="text-xs text-muted-foreground text-center">
          Showing {filteredNodeCount} of {allNodes.length} nodes
        </p>
      )}
    </div>
  )
}

/* ─── Workflow Section with pagination ────────────────────────────────────── */

function WorkflowSection({
  wf,
  expanded,
  onToggle,
  onSelect,
}: {
  wf: WorkflowDataSummary
  expanded: boolean
  onToggle: () => void
  onSelect: (n: DataNode) => void
}) {
  const visibleNodes = expanded ? wf.nodes : wf.nodes.slice(0, NODES_PER_PAGE)
  const hasMore = wf.nodes.length > NODES_PER_PAGE

  return (
    <div className="flex flex-col gap-3">
      {/* Workflow header */}
      <div className="flex items-center gap-3">
        <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-[hsl(var(--primary))]/10">
          <HardDrive className="h-3.5 w-3.5 text-[hsl(var(--primary))]" />
        </div>
        <div className="flex-1">
          <h2 className="text-sm font-mono font-medium text-foreground">{wf.workflow}</h2>
          <span className="text-[10px] text-muted-foreground">
            {wf.dbSize} {"\u00B7"} {wf.nodes.length} node{wf.nodes.length !== 1 ? "s" : ""}
            {" "}{"\u00B7"} {wf.targetCount} target{wf.targetCount !== 1 ? "s" : ""}
            {wf.sourceCount > 0 && (
              <>{" "}{"\u00B7"} {wf.sourceCount} source{wf.sourceCount !== 1 ? "s" : ""}</>
            )}
          </span>
        </div>
        <Badge variant="secondary" className="text-[10px] font-mono font-normal rounded-md">
          {wf.dbSize}
        </Badge>
      </div>

      {/* Node table */}
      <div className="rounded-xl border border-border bg-card overflow-hidden">
        {/* Table header */}
        <div className="grid grid-cols-[1fr_100px_1fr_40px] items-center gap-4 px-5 py-2.5 bg-secondary/30">
          <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">Node</span>
          <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold text-right">Records</span>
          <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">Files</span>
          <span className="w-4" />
        </div>

        {/* Rows */}
        <div className="divide-y divide-border">
          {visibleNodes.map((node) => (
            <button
              key={node.id}
              className="grid grid-cols-[1fr_100px_1fr_40px] items-center gap-4 px-5 py-3 w-full text-left hover:bg-accent/30 transition-colors"
              onClick={() => onSelect(node)}
            >
              <div className="flex items-center gap-2.5 min-w-0">
                <div
                  className="flex h-7 w-7 items-center justify-center rounded-lg shrink-0"
                  style={{ backgroundColor: "hsl(var(--primary) / 0.1)" }}
                >
                  <Database className="h-3.5 w-3.5 text-[hsl(var(--primary))]" />
                </div>
                <span className="text-sm font-mono text-foreground truncate">{node.node}</span>
              </div>
              <span className="text-sm font-mono tabular-nums text-foreground text-right">
                {node.recordCount.toLocaleString()}
              </span>
              <div className="flex items-center gap-1.5 min-w-0">
                <FileJson className="h-3.5 w-3.5 text-[hsl(var(--primary))] shrink-0" />
                <span className="text-xs font-mono text-muted-foreground truncate">
                  {node.files[0] ?? "\u2014"}
                </span>
                {node.files.length > 1 && (
                  <Badge variant="secondary" className="text-[10px] font-mono font-normal rounded-md shrink-0">
                    +{node.files.length - 1}
                  </Badge>
                )}
              </div>
              <ArrowRight className="h-3.5 w-3.5 text-muted-foreground/40" />
            </button>
          ))}
        </div>

        {/* Show more / less */}
        {hasMore && (
          <button
            onClick={onToggle}
            className="flex items-center justify-center gap-1.5 w-full px-5 py-2.5 text-xs text-[hsl(var(--primary))] hover:bg-accent/30 transition-colors border-t border-border"
          >
            {expanded ? (
              <>Show less <ChevronUp className="h-3 w-3" /></>
            ) : (
              <>Show all {wf.nodes.length} nodes <ChevronDown className="h-3 w-3" /></>
            )}
          </button>
        )}
      </div>
    </div>
  )
}

/* ─── Node Detail with paginated data table ──────────────────────────────── */

function NodeDetail({
  node,
  workflow,
  onBack,
}: {
  node: DataNode
  workflow?: WorkflowDataSummary
  onBack: () => void
}) {
  const [page, setPage] = useState(0)
  const [viewMode, setViewMode] = useState<"table" | "json">("table")

  // Extract columns from preview records
  const columns = useMemo(() => {
    if (node.preview.length === 0) return []
    const colSet = new Set<string>()
    for (const row of node.preview) {
      for (const key of Object.keys(row)) {
        colSet.add(key)
      }
    }
    return Array.from(colSet)
  }, [node.preview])

  const totalPages = Math.ceil(node.preview.length / RECORDS_PER_PAGE)
  const pageRecords = node.preview.slice(
    page * RECORDS_PER_PAGE,
    (page + 1) * RECORDS_PER_PAGE,
  )

  return (
    <div className="flex flex-col gap-6">
      {/* Header */}
      <div className="flex items-center gap-4">
        <button
          onClick={onBack}
          className="flex h-8 w-8 items-center justify-center rounded-lg border border-border bg-card text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
        >
          <ArrowLeft className="h-4 w-4" />
        </button>
        <div className="flex-1">
          <div className="flex items-center gap-2.5">
            <div
              className="flex h-8 w-8 items-center justify-center rounded-lg shrink-0"
              style={{ backgroundColor: "hsl(var(--primary) / 0.1)" }}
            >
              <Database className="h-4 w-4 text-[hsl(var(--primary))]" />
            </div>
            <h1 className="text-xl font-mono font-semibold text-foreground">{node.node}</h1>
          </div>
          <p className="text-sm text-muted-foreground mt-1">
            {node.workflow} {"\u00B7"} {node.recordCount.toLocaleString()} records
            {workflow && <> {"\u00B7"} DB: {workflow.dbSize}</>}
          </p>
        </div>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <InfoCard label="Records" value={node.recordCount.toLocaleString()} />
        <InfoCard label="Files" value={String(node.files.length)} />
        <InfoCard label="Workflow" value={node.workflow} />
        <InfoCard label="DB Size" value={workflow?.dbSize ?? "\u2014"} />
      </div>

      {/* Files */}
      {node.files.length > 0 && (
        <div className="rounded-xl border border-border bg-card p-4">
          <h3 className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-3">
            Source Files
          </h3>
          <div className="flex flex-wrap gap-2">
            {node.files.map((file) => (
              <div
                key={file}
                className="flex items-center gap-1.5 rounded-lg bg-secondary/50 border border-border/50 px-3 py-1.5"
              >
                <FileJson className="h-3 w-3 text-[hsl(var(--primary))]" />
                <span className="text-xs font-mono text-foreground">{file}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Data preview */}
      <div className="rounded-xl border border-border bg-card overflow-hidden">
        {/* Toolbar */}
        <div className="flex items-center justify-between border-b border-border px-4 py-2.5 bg-secondary/30">
          <div className="flex items-center gap-2">
            <Rows3 className="h-3.5 w-3.5 text-muted-foreground" />
            <span className="text-[10px] font-mono text-muted-foreground">
              Showing {node.preview.length > 0 ? page * RECORDS_PER_PAGE + 1 : 0}
              {"\u2013"}
              {Math.min((page + 1) * RECORDS_PER_PAGE, node.preview.length)} of{" "}
              {node.preview.length} preview records
              {node.recordCount > node.preview.length && (
                <span className="text-muted-foreground/50"> ({node.recordCount} total in DB)</span>
              )}
            </span>
          </div>
          <div className="flex items-center gap-1">
            <button
              onClick={() => setViewMode("table")}
              className={`rounded-md px-2.5 py-1 text-[10px] font-medium transition-all ${
                viewMode === "table"
                  ? "bg-[hsl(var(--primary))]/15 text-[hsl(var(--primary))]"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              Table
            </button>
            <button
              onClick={() => setViewMode("json")}
              className={`rounded-md px-2.5 py-1 text-[10px] font-medium transition-all ${
                viewMode === "json"
                  ? "bg-[hsl(var(--primary))]/15 text-[hsl(var(--primary))]"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              JSON
            </button>
          </div>
        </div>

        {/* Content */}
        {node.preview.length === 0 ? (
          <div className="p-8 text-center">
            <p className="text-sm text-muted-foreground">No preview records available</p>
          </div>
        ) : viewMode === "table" ? (
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead>
                <tr className="border-b border-border bg-secondary/20">
                  <th className="px-4 py-2 text-[10px] uppercase tracking-wider text-muted-foreground font-semibold w-10">
                    #
                  </th>
                  {columns.map((col) => (
                    <th
                      key={col}
                      className="px-4 py-2 text-[10px] uppercase tracking-wider text-muted-foreground font-semibold whitespace-nowrap"
                    >
                      {col}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {pageRecords.map((row, i) => (
                  <tr
                    key={page * RECORDS_PER_PAGE + i}
                    className="hover:bg-accent/20 transition-colors"
                  >
                    <td className="px-4 py-2.5 text-[10px] font-mono text-muted-foreground tabular-nums">
                      {page * RECORDS_PER_PAGE + i + 1}
                    </td>
                    {columns.map((col) => (
                      <td key={col} className="px-4 py-2.5 max-w-[300px]">
                        <CellValue value={row[col]} />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="p-5 overflow-x-auto max-h-[500px] overflow-y-auto">
            <pre className="text-xs font-mono text-foreground/80 leading-relaxed whitespace-pre-wrap">
              {JSON.stringify(pageRecords, null, 2)}
            </pre>
          </div>
        )}

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="flex items-center justify-between border-t border-border px-4 py-2.5 bg-secondary/20">
            <button
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={page === 0}
              className="flex items-center gap-1 rounded-md px-2.5 py-1 text-xs font-medium text-muted-foreground hover:text-foreground disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
            >
              <ArrowLeft className="h-3 w-3" /> Previous
            </button>
            <div className="flex items-center gap-1">
              {Array.from({ length: totalPages }, (_, i) => (
                <button
                  key={i}
                  onClick={() => setPage(i)}
                  className={`flex h-6 w-6 items-center justify-center rounded-md text-[10px] font-mono font-medium transition-all ${
                    page === i
                      ? "bg-[hsl(var(--primary))]/15 text-[hsl(var(--primary))] ring-1 ring-[hsl(var(--primary))]/20"
                      : "text-muted-foreground hover:bg-accent"
                  }`}
                >
                  {i + 1}
                </button>
              ))}
            </div>
            <button
              onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
              disabled={page === totalPages - 1}
              className="flex items-center gap-1 rounded-md px-2.5 py-1 text-xs font-medium text-muted-foreground hover:text-foreground disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
            >
              Next <ArrowRight className="h-3 w-3" />
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

/* ─── Shared components ──────────────────────────────────────────────────── */

function CellValue({ value }: { value: unknown }) {
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
    return <span className="text-xs font-mono tabular-nums text-foreground">{value.toLocaleString()}</span>
  }
  if (typeof value === "object") {
    const str = JSON.stringify(value)
    return (
      <span className="text-xs font-mono text-muted-foreground truncate block max-w-[300px]" title={str}>
        {str.length > 80 ? str.slice(0, 80) + "\u2026" : str}
      </span>
    )
  }
  const str = String(value)
  return (
    <span className="text-xs font-mono text-foreground truncate block max-w-[300px]" title={str}>
      {str.length > 120 ? str.slice(0, 120) + "\u2026" : str}
    </span>
  )
}

function FilterChip({
  label,
  count,
  active,
  onClick,
}: {
  label: string
  count: number
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-all ${
        active
          ? "bg-[hsl(var(--primary))]/15 text-[hsl(var(--primary))] ring-1 ring-[hsl(var(--primary))]/20"
          : "text-muted-foreground hover:bg-accent hover:text-foreground"
      }`}
    >
      <span className="font-mono truncate max-w-[120px]">{label}</span>
      <span className="text-[10px] tabular-nums opacity-60">{count}</span>
    </button>
  )
}

function InfoCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">{label}</span>
      <p className="text-sm font-mono text-foreground mt-1 truncate">{value}</p>
    </div>
  )
}
