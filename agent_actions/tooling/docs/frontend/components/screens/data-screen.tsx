"use client"

import { useState, useMemo, useEffect, useCallback } from "react"
import { ArrowLeft, ArrowRight, ChevronRight, Minus, Plus } from "lucide-react"
import { CellValue, DataCard, getDisplayFields, type ActionInfo } from "@/components/ui/data-card"
import { useCatalogData } from "@/lib/catalog-context"
import { EM_DASH, plural } from "@/lib/format"
import { BackButton, Card, EmptyState, PageTitle, SearchInput, Segmented } from "@/components/graphite"
import type { DataNode, WorkflowDataSummary } from "@/lib/mock-data"

const RECORDS_PER_PAGE = 5

/** Execution order from the workflow's levels: action name → position. */
function buildExecutionOrder(levels: string[][]): Map<string, number> {
  const order = new Map<string, number>()
  let pos = 0
  for (const level of levels) for (const action of level) order.set(action, pos++)
  return order
}

export function DataScreen() {
  const { workflowData, workflows } = useCatalogData()
  const [selectedWorkflow, setSelectedWorkflow] = useState<WorkflowDataSummary | null>(null)
  const [selectedNode, setSelectedNode] = useState<DataNode | null>(null)

  const allNodes = useMemo(() => workflowData.flatMap((wf) => wf.nodes), [workflowData])
  const totalRecords = useMemo(() => allNodes.reduce((sum, n) => sum + n.recordCount, 0), [allNodes])

  if (selectedNode && selectedWorkflow) {
    return (
      <NodeDetail node={selectedNode} workflow={selectedWorkflow} onBack={() => setSelectedNode(null)} />
    )
  }

  if (selectedWorkflow) {
    return (
      <WorkflowDataDetail
        wf={selectedWorkflow}
        executionOrder={buildExecutionOrder(
          workflows.find((w) => w.name === selectedWorkflow.workflow)?.levels ?? [],
        )}
        onBack={() => setSelectedWorkflow(null)}
        onSelectNode={setSelectedNode}
      />
    )
  }

  return (
    <div className="flex max-w-[1180px] animate-view-in flex-col gap-4">
      <PageTitle
        title="Data Explorer"
        subtitle={
          allNodes.length === 0
            ? "No stored output yet"
            : `${plural(workflowData.length, "workflow")} · ${plural(allNodes.length, "node")} · ${plural(totalRecords, "record")}`
        }
      />

      <Card>
        {allNodes.length === 0 ? (
          <EmptyState message="No workflow output data available. Run a workflow, then regenerate the docs." />
        ) : (
          <>
            <div className="grid grid-cols-[minmax(0,1.6fr)_repeat(4,minmax(0,1fr))_20px] gap-2.5 bg-hover px-[18px] py-2.5 text-xs font-medium text-muted-foreground">
              <span>Workflow</span>
              <span className="text-right">Nodes</span>
              <span className="text-right">Targets</span>
              <span className="text-right">Sources</span>
              <span className="text-right">DB size</span>
              <span />
            </div>
            {workflowData.map((wf) => {
              const records = wf.nodes.reduce((s, n) => s + n.recordCount, 0)
              return (
                <button
                  key={wf.workflow}
                  onClick={() => setSelectedWorkflow(wf)}
                  className="grid w-full grid-cols-[minmax(0,1.6fr)_repeat(4,minmax(0,1fr))_20px] items-center gap-2.5 border-t border-border-soft px-[18px] py-3 text-left hover:bg-hover"
                >
                  <span className="min-w-0">
                    <span className="font-mono text-[13px] font-medium">{wf.workflow}</span>
                    <span className="ml-2 text-[11px] text-muted-foreground">
                      {plural(records, "record")}
                    </span>
                  </span>
                  <span className="text-right font-mono text-[12.5px]">{wf.nodes.length}</span>
                  <span className="text-right font-mono text-[12.5px]">{wf.targetCount}</span>
                  <span className="text-right font-mono text-[12.5px]">{wf.sourceCount}</span>
                  <span className="text-right font-mono text-[12.5px]">{wf.dbSize}</span>
                  <ChevronRight className="h-3.5 w-3.5 text-muted-2" />
                </button>
              )
            })}
          </>
        )}
      </Card>
    </div>
  )
}

/* ─── Workflow → nodes ──────────────────────────────────────────────────── */

function WorkflowDataDetail({
  wf,
  executionOrder,
  onBack,
  onSelectNode,
}: {
  wf: WorkflowDataSummary
  executionOrder: Map<string, number>
  onBack: () => void
  onSelectNode: (n: DataNode) => void
}) {
  const [search, setSearch] = useState("")

  const sorted = useMemo(
    () =>
      [...wf.nodes].sort((a, b) => {
        const orderA = executionOrder.get(a.node) ?? Infinity
        const orderB = executionOrder.get(b.node) ?? Infinity
        if (orderA !== orderB) return orderA - orderB
        return a.node.localeCompare(b.node)
      }),
    [wf.nodes, executionOrder],
  )

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return sorted
    return sorted.filter(
      (n) => n.node.toLowerCase().includes(q) || n.files.some((f) => f.toLowerCase().includes(q)),
    )
  }, [sorted, search])

  const totalRecords = wf.nodes.reduce((s, n) => s + n.recordCount, 0)

  return (
    <div className="flex max-w-[1180px] animate-view-in flex-col gap-3.5">
      <div className="flex items-center gap-3.5">
        <BackButton onClick={onBack} title="Back to workflows" />
        <div className="min-w-0">
          <h1 className="m-0 font-mono text-[19px] font-semibold">{wf.workflow}</h1>
          <p className="mt-1 text-[12.5px] text-muted-foreground">
            {plural(wf.nodes.length, "node")} · {plural(totalRecords, "record")} · {wf.dbSize} ·{" "}
            {plural(wf.targetCount, "target")} · {plural(wf.sourceCount, "source")}
          </p>
        </div>
      </div>

      <SearchInput
        value={search}
        onChange={setSearch}
        placeholder="Filter nodes…"
        className="max-w-[420px]"
      />

      <Card>
        <div className="grid grid-cols-[minmax(0,1fr)_100px_minmax(0,1fr)_20px] gap-2.5 bg-hover px-[18px] py-2.5 text-xs font-medium text-muted-foreground">
          <span>Action node</span>
          <span className="text-right">Records</span>
          <span>Files</span>
          <span />
        </div>
        {filtered.map((node) => (
          <button
            key={node.id}
            onClick={() => onSelectNode(node)}
            className="grid w-full grid-cols-[minmax(0,1fr)_100px_minmax(0,1fr)_20px] items-center gap-2.5 border-t border-border-soft px-[18px] py-2.5 text-left hover:bg-hover"
          >
            <span className="truncate font-mono text-[12.5px] font-medium">{node.node}</span>
            <span className="text-right font-mono text-xs">{node.recordCount.toLocaleString()}</span>
            <span className="flex min-w-0 items-center gap-1.5">
              <span className="truncate font-mono text-[11px] text-muted-foreground">
                {node.files[0] ?? EM_DASH}
              </span>
              {node.files.length > 1 && (
                <span className="shrink-0 rounded-sm bg-surface-2 px-1.5 py-px font-mono text-[10px] text-muted-foreground">
                  +{node.files.length - 1}
                </span>
              )}
            </span>
            <ChevronRight className="h-3.5 w-3.5 text-muted-2" />
          </button>
        ))}
        {filtered.length === 0 && (
          <EmptyState
            message="No nodes match this filter"
            actionLabel={search ? "Clear filter" : undefined}
            onAction={search ? () => setSearch("") : undefined}
          />
        )}
      </Card>
    </div>
  )
}

/* ─── Typography preferences for the record card ───────────────────────── */

const FONT_SIZES = [13, 14, 15, 16, 17, 18] as const
const WIDTH_PRESETS = [
  { label: "S", value: 560 },
  { label: "M", value: 720 },
  { label: "L", value: 920 },
] as const
const DEFAULT_FONT_IDX = 2
const DEFAULT_WIDTH_IDX = 1

function readStoredIndex(key: string, lookup: (v: number) => number): number | null {
  try {
    const raw = localStorage.getItem(key)
    if (raw) { const i = lookup(Number(raw)); if (i >= 0) return i }
  } catch { /* SSR / private browsing */ }
  return null
}

function useTypographyPrefs() {
  const [fontIdx, setFontIdx] = useState(
    () =>
      readStoredIndex("docs-card-font-size", (v) =>
        FONT_SIZES.indexOf(v as (typeof FONT_SIZES)[number]),
      ) ?? DEFAULT_FONT_IDX,
  )
  const [widthIdx, setWidthIdx] = useState(
    () =>
      readStoredIndex("docs-card-width", (v) => WIDTH_PRESETS.findIndex((p) => p.value === v)) ??
      DEFAULT_WIDTH_IDX,
  )

  useEffect(() => {
    try { localStorage.setItem("docs-card-font-size", String(FONT_SIZES[fontIdx])) } catch { /* unavailable */ }
  }, [fontIdx])
  useEffect(() => {
    try { localStorage.setItem("docs-card-width", String(WIDTH_PRESETS[widthIdx].value)) } catch { /* unavailable */ }
  }, [widthIdx])

  const stepFont = useCallback((dir: 1 | -1) => {
    setFontIdx((prev) => {
      const next = prev + dir
      return next < 0 || next >= FONT_SIZES.length ? prev : next
    })
  }, [])

  const stepWidth = useCallback((dir: 1 | -1) => {
    setWidthIdx((prev) => {
      const next = prev + dir
      return next < 0 || next >= WIDTH_PRESETS.length ? prev : next
    })
  }, [])

  return {
    fontSize: FONT_SIZES[fontIdx],
    fontIdx,
    maxWidth: WIDTH_PRESETS[widthIdx].value,
    widthLabel: WIDTH_PRESETS[widthIdx].label,
    widthIdx,
    stepFont,
    stepWidth,
  }
}

function TypographyControls({
  fontSize, fontIdx, widthLabel, widthIdx, stepFont, stepWidth,
}: ReturnType<typeof useTypographyPrefs>) {
  return (
    <div className="flex items-center gap-1.5">
      <div className="typo-pill" title="Font size">
        <button type="button" className="typo-btn" onClick={() => stepFont(-1)} disabled={fontIdx === 0} aria-label="Decrease font size">
          <span className="text-[10px] font-medium">A</span>
        </button>
        <span className="typo-val">{fontSize}</span>
        <button type="button" className="typo-btn" onClick={() => stepFont(1)} disabled={fontIdx === FONT_SIZES.length - 1} aria-label="Increase font size">
          <span className="text-sm font-medium">A</span>
        </button>
      </div>
      <div className="typo-pill" title="Card width">
        <button type="button" className="typo-btn" onClick={() => stepWidth(-1)} disabled={widthIdx === 0} aria-label="Narrower">
          <Minus className="h-3 w-3" />
        </button>
        <span className="typo-val">{widthLabel}</span>
        <button type="button" className="typo-btn" onClick={() => stepWidth(1)} disabled={widthIdx === WIDTH_PRESETS.length - 1} aria-label="Wider">
          <Plus className="h-3 w-3" />
        </button>
      </div>
    </div>
  )
}

/* ─── Node → records ────────────────────────────────────────────────────── */

type ViewMode = "card" | "json" | "table"

function NodeDetail({
  node,
  workflow,
  onBack,
}: {
  node: DataNode
  workflow: WorkflowDataSummary
  onBack: () => void
}) {
  const { actions } = useCatalogData()
  const [page, setPage] = useState(0)
  const [viewMode, setViewMode] = useState<ViewMode>("card")
  const typo = useTypographyPrefs()

  const actionConfig = actions[`${node.workflow}/${node.node}`]
  const actionInfo: ActionInfo | undefined = actionConfig
    ? {
        name: node.node,
        kind: actionConfig.type || "unknown",
        impl: actionConfig.impl || undefined,
        intent: actionConfig.intent || undefined,
        dependencies: actionConfig.deps || [],
      }
    : undefined

  const columns = useMemo(() => {
    const colSet = new Set<string>()
    for (const row of node.preview) {
      for (const key of Object.keys(getDisplayFields(row))) colSet.add(key)
    }
    return [...colSet]
  }, [node.preview])

  const totalPages = Math.ceil(node.preview.length / RECORDS_PER_PAGE)
  const pageRecords = node.preview.slice(page * RECORDS_PER_PAGE, (page + 1) * RECORDS_PER_PAGE)

  return (
    <div className="flex max-w-[1180px] animate-view-in flex-col gap-3.5">
      <div className="flex items-center gap-3.5">
        <BackButton onClick={onBack} title={`Back to ${workflow.workflow}`} />
        <div className="min-w-0">
          <h1 className="m-0 font-mono text-[19px] font-semibold">{node.node}</h1>
          <p className="mt-1 text-[12.5px] text-muted-foreground">
            {node.workflow} · {plural(node.recordCount, "record")} · {workflow.dbSize}
          </p>
        </div>
      </div>

      {node.files.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {node.files.map((file) => (
            <span
              key={file}
              className="rounded-control border border-border-soft bg-surface-2 px-2.5 py-1 font-mono text-[11px] text-foreground-2"
            >
              {file}
            </span>
          ))}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2.5">
        <span className="text-[13px] font-semibold">Records</span>
        <span className="font-mono text-[11px] text-muted-foreground">
          {node.preview.length > 0 ? page * RECORDS_PER_PAGE + 1 : 0}–
          {Math.min((page + 1) * RECORDS_PER_PAGE, node.preview.length)} of {node.preview.length}
          {node.recordCount > node.preview.length && ` (${node.recordCount.toLocaleString()} stored)`}
        </span>
        <span className="flex-1" />
        {viewMode === "card" && <TypographyControls {...typo} />}
        <Segmented
          options={[
            { value: "card", label: "Card" },
            { value: "json", label: "JSON" },
            { value: "table", label: "Table" },
          ]}
          value={viewMode}
          onChange={(v) => setViewMode(v as ViewMode)}
        />
      </div>

      {node.preview.length === 0 ? (
        <Card>
          <EmptyState message="No preview records were captured for this node." />
        </Card>
      ) : viewMode === "table" ? (
        <Card>
          <div className="overflow-x-auto">
            <table className="w-full dense-table">
              <thead>
                <tr>
                  <th className="w-10 text-left">#</th>
                  {columns.map((col) => (
                    <th key={col} className="whitespace-nowrap text-left">{col}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {pageRecords.map((row, i) => {
                  const fields = getDisplayFields(row)
                  return (
                    <tr key={page * RECORDS_PER_PAGE + i} className="hover:bg-hover">
                      <td className="font-mono text-muted-foreground">{page * RECORDS_PER_PAGE + i + 1}</td>
                      {columns.map((col) => (
                        <td key={col} className="max-w-[300px]">
                          <CellValue value={fields[col]} />
                        </td>
                      ))}
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </Card>
      ) : viewMode === "json" ? (
        <Card>
          <pre className="max-h-[500px] overflow-auto whitespace-pre-wrap p-4 font-mono text-xs leading-relaxed text-foreground-2">
            {JSON.stringify(pageRecords, null, 2)}
          </pre>
        </Card>
      ) : (
        <div className="mx-auto flex w-full flex-col gap-3" style={{ maxWidth: typo.maxWidth }}>
          {pageRecords.map((row, i) => {
            const idx = page * RECORDS_PER_PAGE + i
            const key = typeof row.target_id === "string" ? row.target_id : idx
            return (
              <DataCard
                key={key}
                record={row}
                index={idx + 1}
                fontSize={typo.fontSize}
                defaultOpen={i === 0}
                actionInfo={actionInfo}
              />
            )
          })}
        </div>
      )}

      {totalPages > 1 && (
        <div className="flex items-center justify-between rounded-card border border-border bg-surface px-4 py-2">
          <button
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            disabled={page === 0}
            className="flex items-center gap-1 rounded-control px-2 py-1 text-xs text-muted-foreground hover:text-foreground disabled:cursor-not-allowed disabled:opacity-30"
          >
            <ArrowLeft className="h-3 w-3" /> Prev
          </button>
          <div className="flex items-center gap-1">
            {Array.from({ length: totalPages }, (_, i) => (
              <button
                key={i}
                onClick={() => setPage(i)}
                className={`flex h-5 w-5 items-center justify-center rounded-sm font-mono text-[10px] ${
                  page === i ? "bg-accent-a12 text-accent-t" : "text-muted-foreground hover:bg-hover"
                }`}
              >
                {i + 1}
              </button>
            ))}
          </div>
          <button
            onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
            disabled={page === totalPages - 1}
            className="flex items-center gap-1 rounded-control px-2 py-1 text-xs text-muted-foreground hover:text-foreground disabled:cursor-not-allowed disabled:opacity-30"
          >
            Next <ArrowRight className="h-3 w-3" />
          </button>
        </div>
      )}
    </div>
  )
}
