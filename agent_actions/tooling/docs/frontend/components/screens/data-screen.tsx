"use client"

import React, { useState, useMemo } from "react"
import {
  Database,
  ArrowLeft,
  ArrowRight,
  FileJson,
  HardDrive,
  Search,
  Rows3,
  ChevronRight,
  LayoutGrid,
} from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { CellValue, DataCard } from "@/components/ui/data-card"
import { useCatalogData } from "@/lib/catalog-context"
import type { DataNode, WorkflowDataSummary } from "@/lib/mock-data"

const RECORDS_PER_PAGE = 5

export function DataScreen() {
  const { workflowData } = useCatalogData()
  const [selectedWorkflow, setSelectedWorkflow] = useState<WorkflowDataSummary | null>(null)
  const [selectedNode, setSelectedNode] = useState<DataNode | null>(null)

  const allNodes = useMemo(
    () => workflowData.flatMap((wf) => wf.nodes),
    [workflowData],
  )

  const totalRecords = useMemo(
    () => allNodes.reduce((sum, n) => sum + n.recordCount, 0),
    [allNodes],
  )

  // Node detail view
  if (selectedNode && selectedWorkflow) {
    return (
      <NodeDetail
        node={selectedNode}
        workflow={selectedWorkflow}
        onBack={() => setSelectedNode(null)}
      />
    )
  }

  // Workflow drill-down: show action nodes for selected workflow
  if (selectedWorkflow) {
    return (
      <WorkflowDetail
        wf={selectedWorkflow}
        onBack={() => setSelectedWorkflow(null)}
        onSelectNode={setSelectedNode}
      />
    )
  }

  // Top level: workflow list
  if (allNodes.length === 0) {
    return (
      <div className="flex flex-col gap-4">
        <div>
          <h1 className="text-lg font-semibold tracking-tight text-foreground">Data Explorer</h1>
          <p className="text-xs text-muted-foreground mt-0.5">No data found</p>
        </div>
        <div className="rounded-lg border border-border bg-card p-8 text-center">
          <Database className="h-8 w-8 text-muted-foreground/40 mx-auto mb-2" />
          <p className="text-xs text-muted-foreground">
            No workflow output data available. Run a workflow first, then regenerate docs.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-lg font-semibold tracking-tight text-foreground">Data Explorer</h1>
        <p className="text-xs text-muted-foreground mt-0.5">
          {workflowData.length} workflow{workflowData.length !== 1 ? "s" : ""} &middot;{" "}
          {allNodes.length} nodes &middot; {totalRecords.toLocaleString()} records
        </p>
      </div>

      {/* Workflow cards */}
      <div className="rounded-lg border border-border bg-card overflow-hidden">
        <table className="w-full dense-table">
          <thead>
            <tr>
              <th className="text-left">Workflow</th>
              <th className="text-right w-20">Nodes</th>
              <th className="text-right w-20">Targets</th>
              <th className="text-right w-20">Sources</th>
              <th className="text-right w-24">DB Size</th>
              <th className="w-8" />
            </tr>
          </thead>
          <tbody>
            {workflowData.map((wf) => {
              const wfRecords = wf.nodes.reduce((s, n) => s + n.recordCount, 0)
              return (
                <tr
                  key={wf.workflow}
                  className="hover:bg-accent/30 transition-colors cursor-pointer"
                  onClick={() => setSelectedWorkflow(wf)}
                >
                  <td>
                    <div className="flex items-center gap-2.5">
                      <div className="flex h-6 w-6 items-center justify-center rounded-md bg-[hsl(var(--primary))]/10 shrink-0">
                        <HardDrive className="h-3 w-3 text-[hsl(var(--primary))]" />
                      </div>
                      <div>
                        <span className="font-mono font-medium text-foreground">{wf.workflow}</span>
                        <span className="text-[10px] text-muted-foreground ml-2">{wfRecords.toLocaleString()} records</span>
                      </div>
                    </div>
                  </td>
                  <td className="text-right font-mono tabular-nums">{wf.nodes.length}</td>
                  <td className="text-right font-mono tabular-nums">{wf.targetCount}</td>
                  <td className="text-right font-mono tabular-nums">{wf.sourceCount}</td>
                  <td className="text-right font-mono tabular-nums">{wf.dbSize}</td>
                  <td>
                    <ChevronRight className="h-3.5 w-3.5 text-muted-foreground/40" />
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

/* ─── Workflow Detail: action nodes list ─────────────────────────────────── */

function WorkflowDetail({
  wf,
  onBack,
  onSelectNode,
}: {
  wf: WorkflowDataSummary
  onBack: () => void
  onSelectNode: (n: DataNode) => void
}) {
  const [search, setSearch] = useState("")

  const filteredNodes = useMemo(() => {
    if (!search) return wf.nodes
    return wf.nodes.filter(
      (n) =>
        n.node.toLowerCase().includes(search.toLowerCase()) ||
        n.files.some((f) => f.toLowerCase().includes(search.toLowerCase())),
    )
  }, [wf.nodes, search])

  const totalRecords = wf.nodes.reduce((s, n) => s + n.recordCount, 0)

  return (
    <div className="flex flex-col gap-4">
      {/* Back + header */}
      <button
        onClick={onBack}
        className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors w-fit"
      >
        <ArrowLeft className="h-3.5 w-3.5" />
        Back to Workflows
      </button>

      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-lg font-semibold tracking-tight text-foreground font-mono">{wf.workflow}</h1>
          <p className="text-xs text-muted-foreground mt-0.5">
            {wf.nodes.length} nodes &middot; {totalRecords.toLocaleString()} records &middot; {wf.dbSize}
          </p>
        </div>
        <div className="flex gap-2">
          <Badge variant="secondary" className="text-[10px] font-mono rounded">
            {wf.targetCount} targets
          </Badge>
          {wf.sourceCount > 0 && (
            <Badge variant="secondary" className="text-[10px] font-mono rounded">
              {wf.sourceCount} sources
            </Badge>
          )}
        </div>
      </div>

      {/* Search */}
      <div className="relative max-w-sm">
        <Search className="absolute left-3 top-2 h-3.5 w-3.5 text-muted-foreground" />
        <Input
          placeholder="Filter nodes..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="pl-9 h-8 bg-secondary border-0 text-xs placeholder:text-muted-foreground"
        />
      </div>

      {/* Node table */}
      <div className="rounded-lg border border-border bg-card overflow-hidden">
        <table className="w-full dense-table">
          <thead>
            <tr>
              <th className="text-left">Action Node</th>
              <th className="text-right w-24">Records</th>
              <th className="text-left">Files</th>
              <th className="w-8" />
            </tr>
          </thead>
          <tbody>
            {filteredNodes.map((node) => (
              <tr
                key={node.id}
                className="hover:bg-accent/30 transition-colors cursor-pointer"
                onClick={() => onSelectNode(node)}
              >
                <td>
                  <div className="flex items-center gap-2">
                    <Database className="h-3.5 w-3.5 text-[hsl(var(--primary))] shrink-0" />
                    <span className="font-mono font-medium text-foreground">{node.node}</span>
                  </div>
                </td>
                <td className="text-right font-mono tabular-nums">{node.recordCount.toLocaleString()}</td>
                <td>
                  <div className="flex items-center gap-1.5">
                    <FileJson className="h-3 w-3 text-[hsl(var(--primary))] shrink-0" />
                    <span className="font-mono text-muted-foreground truncate">{node.files[0] ?? "\u2014"}</span>
                    {node.files.length > 1 && (
                      <Badge variant="secondary" className="text-[10px] font-mono rounded shrink-0">
                        +{node.files.length - 1}
                      </Badge>
                    )}
                  </div>
                </td>
                <td>
                  <ChevronRight className="h-3.5 w-3.5 text-muted-foreground/40" />
                </td>
              </tr>
            ))}
            {filteredNodes.length === 0 && (
              <tr>
                <td colSpan={4} className="text-center text-muted-foreground py-8">No nodes match filter</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

/* ─── Node Detail with paginated data views ──────────────────────────────── */

type ViewMode = "table" | "json" | "card"

const VIEW_MODES: { key: ViewMode; label: string }[] = [
  { key: "table", label: "Table" },
  { key: "json", label: "JSON" },
  { key: "card", label: "Card" },
]

function NodeDetail({
  node,
  workflow,
  onBack,
}: {
  node: DataNode
  workflow: WorkflowDataSummary
  onBack: () => void
}) {
  const [page, setPage] = useState(0)
  const [viewMode, setViewMode] = useState<ViewMode>("card")

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
    <div className="flex flex-col gap-4">
      {/* Back */}
      <button
        onClick={onBack}
        className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors w-fit"
      >
        <ArrowLeft className="h-3.5 w-3.5" />
        Back to {workflow.workflow}
      </button>

      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-lg font-semibold tracking-tight text-foreground font-mono">{node.node}</h1>
          <p className="text-xs text-muted-foreground mt-0.5">
            {node.workflow} &middot; {node.recordCount.toLocaleString()} records &middot; {workflow.dbSize}
          </p>
        </div>
      </div>

      {/* Files */}
      {node.files.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {node.files.map((file) => (
            <div
              key={file}
              className="flex items-center gap-1.5 rounded-md bg-secondary/50 border border-border/50 px-2.5 py-1"
            >
              <FileJson className="h-3 w-3 text-[hsl(var(--primary))]" />
              <span className="text-[11px] font-mono text-foreground">{file}</span>
            </div>
          ))}
        </div>
      )}

      {/* Data preview */}
      <div className={`rounded-lg border border-border bg-card overflow-hidden ${viewMode === "card" ? "border-0 bg-transparent" : ""}`}>
        <div className={`flex items-center justify-between border-b border-border px-4 py-2 ${viewMode === "card" ? "rounded-lg border bg-card" : ""}`}>
          <div className="flex items-center gap-2">
            {viewMode === "card" ? (
              <LayoutGrid className="h-3.5 w-3.5 text-muted-foreground" />
            ) : (
              <Rows3 className="h-3.5 w-3.5 text-muted-foreground" />
            )}
            <span className="text-xs font-semibold text-foreground">Records</span>
            <span className="text-[10px] text-muted-foreground tabular-nums">
              {node.preview.length > 0 ? page * RECORDS_PER_PAGE + 1 : 0}
              {"\u2013"}
              {Math.min((page + 1) * RECORDS_PER_PAGE, node.preview.length)} of {node.preview.length}
              {node.recordCount > node.preview.length && (
                <> ({node.recordCount} total)</>
              )}
            </span>
          </div>
          <div className="flex items-center gap-1">
            {VIEW_MODES.map((m) => (
              <button
                key={m.key}
                onClick={() => setViewMode(m.key)}
                className={`rounded-md px-2 py-1 text-[10px] font-medium transition-all ${
                  viewMode === m.key
                    ? "bg-[hsl(var(--primary))]/15 text-[hsl(var(--primary))]"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                {m.label}
              </button>
            ))}
          </div>
        </div>

        {node.preview.length === 0 ? (
          <div className="p-8 text-center">
            <p className="text-xs text-muted-foreground">No preview records available</p>
          </div>
        ) : viewMode === "table" ? (
          <div className="overflow-x-auto">
            <table className="w-full dense-table">
              <thead>
                <tr>
                  <th className="text-left w-10">#</th>
                  {columns.map((col) => (
                    <th key={col} className="text-left whitespace-nowrap">{col}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {pageRecords.map((row, i) => (
                  <tr key={page * RECORDS_PER_PAGE + i} className="hover:bg-accent/20 transition-colors">
                    <td className="font-mono text-muted-foreground tabular-nums">
                      {page * RECORDS_PER_PAGE + i + 1}
                    </td>
                    {columns.map((col) => (
                      <td key={col} className="max-w-[300px]">
                        <CellValue value={row[col]} />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : viewMode === "json" ? (
          <div className="p-4 overflow-x-auto max-h-[500px] overflow-y-auto">
            <pre className="text-xs font-mono text-foreground/80 leading-relaxed whitespace-pre-wrap">
              {JSON.stringify(pageRecords, null, 2)}
            </pre>
          </div>
        ) : (
          /* Card view */
          <div className="flex flex-col gap-3 pt-3 max-w-[720px]">
            {pageRecords.map((row, i) => {
              const idx = page * RECORDS_PER_PAGE + i
              const key = typeof row.source_guid === "string" ? row.source_guid : idx
              return (
                <DataCard
                  key={key}
                  record={row}
                  index={idx + 1}
                />
              )
            })}
          </div>
        )}

        {/* Pagination */}
        {totalPages > 1 && (
          <div className={`flex items-center justify-between border-t border-border px-4 py-2 ${viewMode === "card" ? "rounded-lg border bg-card mt-3" : ""}`}>
            <button
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={page === 0}
              className="flex items-center gap-1 rounded-md px-2 py-1 text-xs text-muted-foreground hover:text-foreground disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
            >
              <ArrowLeft className="h-3 w-3" /> Prev
            </button>
            <div className="flex items-center gap-1">
              {Array.from({ length: totalPages }, (_, i) => (
                <button
                  key={i}
                  onClick={() => setPage(i)}
                  className={`flex h-5 w-5 items-center justify-center rounded text-[10px] font-mono transition-all ${
                    page === i
                      ? "bg-[hsl(var(--primary))]/15 text-[hsl(var(--primary))]"
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
              className="flex items-center gap-1 rounded-md px-2 py-1 text-xs text-muted-foreground hover:text-foreground disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
            >
              Next <ArrowRight className="h-3 w-3" />
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
