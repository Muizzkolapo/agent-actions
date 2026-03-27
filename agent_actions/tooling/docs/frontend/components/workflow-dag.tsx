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
    <div className={`rounded-lg border-2 bg-card shadow hover:shadow-md transition-shadow w-[320px] ${
      selected ? "border-foreground/80" : "border-foreground/20"
    }`}>
      <Handle type="target" position={Position.Left} isConnectable={isConnectable}
        className={`!w-2.5 !h-2.5 !border-2 !border-card ${isLlm ? "!bg-[hsl(var(--chart-2))]" : "!bg-[hsl(var(--success))]"}`}
      />

      {/* Header row — clicks bubble to React Flow's onNodeClick; only the chevron stops propagation */}
      <div className="flex items-center">
        <div className="flex items-center px-3 py-2.5 border-r border-border/50">
          <div className={`flex h-7 w-7 items-center justify-center rounded shrink-0 ${
            isLlm ? "bg-[hsl(var(--chart-2))]/20" : "bg-[hsl(var(--success))]/20"
          }`}>
            <span className={`text-[8px] font-bold tracking-wider ${
              isLlm ? "text-[hsl(var(--chart-2))]" : "text-[hsl(var(--success))]"
            }`}>{isLlm ? "LLM" : "TOOL"}</span>
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
                className="hover:bg-accent/40 rounded p-0.5 transition-colors shrink-0"
              >
                {expanded
                  ? <ChevronDown className="h-3 w-3 text-muted-foreground" />
                  : <ChevronRight className="h-3 w-3 text-muted-foreground" />}
              </button>
            )}
          </div>
          {data.description && (
            <div className="text-[10px] text-foreground/60 mt-0.5 line-clamp-2">{data.description}</div>
          )}
        </div>
      </div>

      {/* Expandable fields */}
      {expanded && (
        <div className="border-t border-border/50 px-3 py-2 space-y-1.5">
          {data.inputFields.length > 0 && (
            <div className="space-y-1">
              <div className="flex items-center gap-1.5">
                <span className="text-[9px] font-mono font-medium text-muted-foreground/70">in</span>
                <span className="text-[9px] font-mono text-muted-foreground/40">{data.inputFields.length}</span>
                <div className="flex-1 h-px bg-border/30" />
              </div>
              <div className="space-y-px">
                {data.inputFields.map((f) => (
                  <div key={f} className={`pl-2 py-0.5 rounded-sm border-l-2 bg-secondary/30 ${
                    isLlm ? "border-[hsl(var(--chart-2))]/60" : "border-[hsl(var(--success))]/60"
                  }`}>
                    <span className="text-[10px] font-mono text-foreground/80">{f}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
          {data.outputFields.length > 0 && (
            <div className="space-y-1">
              <div className="flex items-center gap-1.5">
                <span className="text-[9px] font-mono font-medium text-muted-foreground/70">out</span>
                <span className="text-[9px] font-mono text-muted-foreground/40">{data.outputFields.length}</span>
                <div className="flex-1 h-px bg-border/30" />
              </div>
              <div className="space-y-px">
                {data.outputFields.map((f) => (
                  <div key={f} className="pl-2 py-0.5 rounded-sm border-l-2 border-[hsl(var(--warning))]/60 bg-secondary/30">
                    <span className="text-[10px] font-mono text-foreground/80">{f}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      <Handle type="source" position={Position.Right} isConnectable={isConnectable}
        className={`!w-2.5 !h-2.5 !border-2 !border-card ${isLlm ? "!bg-[hsl(var(--chart-2))]" : "!bg-[hsl(var(--success))]"}`}
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
  const [nodes, setNodes, onNodesChange] = useNodesState([])
  const [edges, setEdges, onEdgesChange] = useEdgesState([])
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

    setNodes(transformed.nodes as Node[])
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
        style: { stroke: "hsl(var(--muted-foreground))", strokeWidth: 1.5, opacity: 0.7 },
        markerEnd: { type: MarkerType.ArrowClosed, width: 18, height: 18, color: "hsl(var(--muted-foreground))" },
      }}
      className="rounded-lg"
    >
      <Background gap={24} size={1} className="!bg-background" />
      <Controls className="!bg-card !border-border !shadow-md !rounded-lg" showInteractive={false} />
      <MiniMap
        nodeColor={(n) =>
          n.type === "modelNode" ? "hsl(var(--chart-2))"
          : n.type === "toolNode" ? "hsl(var(--success))"
          : "hsl(var(--muted-foreground))"
        }
        className="!bg-card !border-border !rounded-lg"
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
    <div className="w-full rounded-xl border border-border bg-card overflow-hidden" style={{ height: 'clamp(300px, calc(100vh - 280px), 100vh)' }}>
      <ReactFlowProvider>
        <DAGContent actions={actions} workflowId={workflowId} onNodeClick={onNodeClick} />
      </ReactFlowProvider>
    </div>
  )
}
