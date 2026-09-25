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
  type DAGNodeData,
} from "@/lib/dag-transformer"
import type { Action } from "@/lib/mock-data"

// ─── DAG Node (expandable to show fields) ────────────────────────

function ExpandableDAGNode({ data, isConnectable, isLlm, selected }: { data: DAGNodeData; isConnectable: boolean; isLlm: boolean; selected: boolean }) {
  const [expanded, setExpanded] = useState(false)
  const hasFields = data.inputFields.length > 0 || data.outputFields.length > 0

  return (
    <div className={`w-[320px] overflow-hidden rounded-card border bg-surface ${
      selected ? "border-accent-a30" : "border-border"
    }`}>
      <Handle type="target" position={Position.Left} isConnectable={isConnectable}
        className={`!h-2 !w-2 !border !border-surface ${isLlm ? "!bg-llm" : "!bg-tool"}`}
      />

      {/* Header row — clicks bubble to React Flow's onNodeClick; only the chevron stops propagation */}
      <div className="flex items-center">
        <div className="flex items-center px-3 py-2.5 border-r border-border-soft">
          <div className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-sm ${
            isLlm ? "bg-llm/10" : "bg-tool/[0.08]"
          }`}>
            <span className={`text-[8px] font-semibold ${isLlm ? "text-llm-t" : "text-tool-t"}`}>{isLlm ? "LLM" : "TOOL"}</span>
          </div>
        </div>
        <div className="flex-1 px-3 py-2.5 min-w-0">
          <div className="flex items-start justify-between gap-1">
            <span className="text-xs font-mono font-medium text-foreground truncate" title={data.label}>{data.label}</span>
            {hasFields && (
              <button
                type="button"
                aria-label={expanded ? "Collapse fields" : "Expand fields"}
                onClick={(e) => { e.stopPropagation(); setExpanded(!expanded) }}
                className="shrink-0 rounded-sm p-0.5 hover:bg-hover"
              >
                {expanded
                  ? <ChevronDown className="h-3 w-3 text-muted-foreground" />
                  : <ChevronRight className="h-3 w-3 text-muted-foreground" />}
              </button>
            )}
          </div>
          {data.description && (
            <div className="mt-0.5 line-clamp-2 text-[10px] text-muted-foreground">{data.description}</div>
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
        className={`!h-2 !w-2 !border !border-surface ${isLlm ? "!bg-llm" : "!bg-tool"}`}
      />
    </div>
  )
}

function ModelNode({ data, isConnectable, selected }: NodeProps<Node<DAGNodeData>>) {
  return <ExpandableDAGNode data={data} isConnectable={isConnectable ?? false} isLlm selected={selected ?? false} />
}

function ToolNode({ data, isConnectable, selected }: NodeProps<Node<DAGNodeData>>) {
  return <ExpandableDAGNode data={data} isConnectable={isConnectable ?? false} isLlm={false} selected={selected ?? false} />
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
  const { fitView } = useReactFlow()

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
      try {
        fitView({ padding: 0.1, duration: 500 })
      } catch {
        // fitView can fail before render
      }
    }, 100)
  }, [actions, workflowId, fitView, setNodes, setEdges])

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
      fitView
      minZoom={0.1}
      maxZoom={1.5}
      nodesDraggable
      nodesConnectable={false}
      defaultEdgeOptions={{
        type: "default",
        animated: false,
        style: { stroke: "hsl(var(--border-2))", strokeWidth: 1.5 },
        markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16, color: "hsl(var(--border-2))" },
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
