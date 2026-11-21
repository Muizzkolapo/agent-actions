"use client"

import { useState, useCallback, useEffect, useMemo } from "react"
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  Handle,
  Position,
  useNodesState,
  useEdgesState,
  useReactFlow,
  useStoreApi,
  ReactFlowProvider,
  type NodeProps,
  type Node,
  type Edge,
  MarkerType,
} from "@xyflow/react"
import "@xyflow/react/dist/style.css"
import { ChevronDown, ChevronRight } from "lucide-react"
import {
  transformWorkflowToReactFlow,
  initialViewport,
  FIT_PADDING,
  MAX_ZOOM,
  MIN_ZOOM,
  NODE_HEIGHT,
  NODE_WIDTH,
  type DAGNodeData,
} from "@/lib/dag-transformer"
import type { Action } from "@/lib/mock-data"

// ─── DAG Node (expandable to show fields) ────────────────────────

function ExpandableDAGNode({ id, data, isConnectable, isLlm, selected }: { id: string; data: DAGNodeData; isConnectable: boolean; isLlm: boolean; selected: boolean }) {
  const [expanded, setExpanded] = useState(false)
  const { updateNode } = useReactFlow()
  const hasFields = data.inputFields.length > 0 || data.outputFields.length > 0

  const toggle = (e: React.MouseEvent) => {
    e.stopPropagation()
    // Rows sit 20px apart, so an open node must draw above its neighbours.
    updateNode(id, { zIndex: expanded ? 0 : 10 })
    setExpanded(!expanded)
  }

  return (
    <div
      style={{ width: NODE_WIDTH }}
      title={data.description ? `${data.label}\n${data.description}` : data.label}
      className={`overflow-hidden rounded-sm border bg-surface ${
        selected ? "border-accent-a30 ring-1 ring-accent-a30" : "border-border-2"
      }`}
    >
      <Handle type="target" position={Position.Left} isConnectable={isConnectable}
        className={`!h-1.5 !w-1.5 !min-w-0 !border-0 ${isLlm ? "!bg-llm" : "!bg-tool"}`}
      />

      {/* Header row — clicks bubble to React Flow's onNodeClick; only the chevron stops propagation */}
      <div className="flex items-center" style={{ height: NODE_HEIGHT - 2 }}>
        <div className={`w-[3px] self-stretch ${isLlm ? "bg-llm" : "bg-tool"}`} />
        <div className="flex min-w-0 flex-1 items-center gap-1.5 px-2">
          <span className="min-w-0 flex-1 truncate font-mono text-[11px] font-medium text-foreground">{data.label}</span>
          <span className={`shrink-0 font-mono text-[8.5px] font-semibold ${isLlm ? "text-llm-t" : "text-tool-t"}`}>{isLlm ? "LLM" : "TOOL"}</span>
          {hasFields && (
            <button
              type="button"
              aria-label={expanded ? "Collapse fields" : "Expand fields"}
              onClick={toggle}
              className="shrink-0 rounded-sm p-0.5 hover:bg-hover"
            >
              {expanded
                ? <ChevronDown className="h-3 w-3 text-muted-foreground" />
                : <ChevronRight className="h-3 w-3 text-muted-foreground" />}
            </button>
          )}
        </div>
      </div>

      {/* Expandable fields */}
      {expanded && (
        <div className="space-y-1.5 border-t border-border-soft px-3 py-2">
          {data.inputFields.length > 0 && (
            <div className="space-y-1">
              <div className="flex items-center gap-1.5">
                <span className="font-mono text-[9px] font-medium text-muted-foreground">in</span>
                <span className="font-mono text-[9px] text-muted-2">{data.inputFields.length}</span>
                <div className="h-px flex-1 bg-border-soft" />
              </div>
              <div className="space-y-px">
                {data.inputFields.map((f) => (
                  <div key={f} className={`rounded-sm border-l-2 bg-surface-2 py-0.5 pl-2 ${
                    isLlm ? "border-llm" : "border-tool"
                  }`}>
                    <span className="font-mono text-[10px] text-foreground-2">{f}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
          {data.outputFields.length > 0 && (
            <div className="space-y-1">
              <div className="flex items-center gap-1.5">
                <span className="font-mono text-[9px] font-medium text-muted-foreground">out</span>
                <span className="font-mono text-[9px] text-muted-2">{data.outputFields.length}</span>
                <div className="h-px flex-1 bg-border-soft" />
              </div>
              <div className="space-y-px">
                {data.outputFields.map((f) => (
                  <div key={f} className="rounded-sm border-l-2 border-warning bg-surface-2 py-0.5 pl-2">
                    <span className="font-mono text-[10px] text-foreground-2">{f}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      <Handle type="source" position={Position.Right} isConnectable={isConnectable}
        className={`!h-1.5 !w-1.5 !min-w-0 !border-0 ${isLlm ? "!bg-llm" : "!bg-tool"}`}
      />
    </div>
  )
}

function ModelNode({ id, data, isConnectable, selected }: NodeProps<Node<DAGNodeData>>) {
  return <ExpandableDAGNode id={id} data={data} isConnectable={isConnectable ?? false} isLlm selected={selected ?? false} />
}

function ToolNode({ id, data, isConnectable, selected }: NodeProps<Node<DAGNodeData>>) {
  return <ExpandableDAGNode id={id} data={data} isConnectable={isConnectable ?? false} isLlm={false} selected={selected ?? false} />
}

// ─── DAG Content ────────────────────────────────────────────────────────────

function DAGContent({
  actions,
  workflowId,
  onNodeClick,
}: {
  actions: Record<string, Action>
  workflowId: string
  onNodeClick?: (name: string) => void
}) {
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([])
  const { fitView, setViewport } = useReactFlow()
  const store = useStoreApi()

  const nodeTypes = useMemo(
    () => ({
      modelNode: ModelNode,
      toolNode: ToolNode,
    }),
    [],
  )

  useEffect(() => {
    const transformed = transformWorkflowToReactFlow(actions, workflowId)

    setNodes(transformed.nodes)
    setEdges(transformed.edges)

    setTimeout(() => {
      const { width, height } = store.getState()
      const view = initialViewport(transformed.nodes, width, height)
      if (view === "fit") fitView({ padding: FIT_PADDING, duration: 500 })
      else setViewport(view, { duration: 500 })
    }, 100)
  }, [actions, workflowId, fitView, setViewport, store, setNodes, setEdges])

  const handleNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      onNodeClick?.(node.id)
    },
    [onNodeClick],
  )

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      onNodesChange={onNodesChange}
      onEdgesChange={onEdgesChange}
      onNodeClick={handleNodeClick}
      minZoom={MIN_ZOOM}
      maxZoom={MAX_ZOOM}
      nodesDraggable
      nodesConnectable={false}
      defaultEdgeOptions={{
        type: "smoothstep",
        animated: false,
        style: { stroke: "hsl(var(--muted-2))", strokeWidth: 1 },
        markerEnd: { type: MarkerType.ArrowClosed, width: 12, height: 12, color: "hsl(var(--muted-2))" },
      }}
      className="rounded-card"
    >
      <Background gap={24} size={1} color="hsl(var(--grid))" className="!bg-well" />
      <Controls className="!rounded-control !border-border !bg-surface !shadow-none" showInteractive={false} />
      <MiniMap
        nodeColor={(n) =>
          n.type === "modelNode" ? "hsl(var(--llm))"
          : n.type === "toolNode" ? "hsl(var(--tool))"
          : "hsl(var(--muted))"
        }
        className="!rounded-control !border-border !bg-surface"
        nodeBorderRadius={4}
      />
    </ReactFlow>
  )
}

// ─── Exported Component ─────────────────────────────────────────────────────

export function WorkflowDAGView({
  actions,
  workflowId,
  onNodeClick,
}: {
  actions: Record<string, Action>
  workflowId: string
  onNodeClick?: (name: string) => void
}) {
  // 280px ≈ top header (48px) + workflow detail header/tabs (~120px) + outer padding (112px)
  return (
    <div className="w-full overflow-hidden rounded-card border border-border bg-well" style={{ height: 'clamp(300px, calc(100vh - 280px), 100vh)' }}>
      <ReactFlowProvider>
        <DAGContent actions={actions} workflowId={workflowId} onNodeClick={onNodeClick} />
      </ReactFlowProvider>
    </div>
  )
}
