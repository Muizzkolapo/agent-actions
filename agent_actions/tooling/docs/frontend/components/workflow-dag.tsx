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
import {
  transformWorkflowToReactFlow,
  transformWorkflowToFieldLineage,
  type DAGNodeData,
  type LineageNodeData,
} from "@/lib/dag-transformer"
import type { Action } from "@/lib/mock-data"

// ─── dbt-style Model Node ───────────────────────────────────────────────────

function ModelNode({ data, isConnectable }: NodeProps<Node<DAGNodeData>>) {
  return (
    <div className="group flex items-center rounded-lg border border-border bg-card shadow-sm hover:shadow-md transition-shadow min-w-[220px] max-w-[340px]">
      <Handle type="target" position={Position.Left} isConnectable={isConnectable} className="!bg-[hsl(var(--chart-2))] !w-2 !h-2 !border-2 !border-card" />

      {/* Type badge */}
      <div className="flex h-full items-center px-3 py-3 border-r border-border/60">
        <div className="flex h-9 w-9 items-center justify-center rounded-md bg-[hsl(var(--chart-2))]/15 shrink-0">
          <span className="text-[10px] font-bold tracking-wider text-[hsl(var(--chart-2))]">LLM</span>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 px-3 py-2.5 min-w-0">
        <div className="text-sm font-mono font-semibold text-foreground truncate">{data.label}</div>
        <div className="text-[10px] text-muted-foreground mt-0.5 truncate">{data.model}</div>
        {(data.inputFields.length > 0 || data.outputFields.length > 0) && (
          <div className="flex items-center gap-2 mt-1.5">
            {data.inputFields.length > 0 && (
              <span className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-[hsl(var(--chart-2))]/10 text-[hsl(var(--chart-2))]">
                {data.inputFields.length} in
              </span>
            )}
            {data.outputFields.length > 0 && (
              <span className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-[hsl(var(--success))]/10 text-[hsl(var(--success))]">
                {data.outputFields.length} out
              </span>
            )}
          </div>
        )}
      </div>

      <Handle type="source" position={Position.Right} isConnectable={isConnectable} className="!bg-[hsl(var(--chart-2))] !w-2 !h-2 !border-2 !border-card" />
    </div>
  )
}

// ─── dbt-style Tool Node ────────────────────────────────────────────────────

function ToolNode({ data, isConnectable }: NodeProps<Node<DAGNodeData>>) {
  return (
    <div className="group flex items-center rounded-lg border border-border bg-card shadow-sm hover:shadow-md transition-shadow min-w-[220px] max-w-[340px]">
      <Handle type="target" position={Position.Left} isConnectable={isConnectable} className="!bg-[hsl(var(--success))] !w-2 !h-2 !border-2 !border-card" />

      {/* Type badge */}
      <div className="flex h-full items-center px-3 py-3 border-r border-border/60">
        <div className="flex h-9 w-9 items-center justify-center rounded-md bg-[hsl(var(--success))]/15 shrink-0">
          <span className="text-[10px] font-bold tracking-wider text-[hsl(var(--success))]">TOOL</span>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 px-3 py-2.5 min-w-0">
        <div className="text-sm font-mono font-semibold text-foreground truncate">{data.label}</div>
        <div className="text-[10px] text-muted-foreground mt-0.5 truncate">{data.impl || "tool"}</div>
        {(data.inputFields.length > 0 || data.outputFields.length > 0) && (
          <div className="flex items-center gap-2 mt-1.5">
            {data.inputFields.length > 0 && (
              <span className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-[hsl(var(--chart-2))]/10 text-[hsl(var(--chart-2))]">
                {data.inputFields.length} in
              </span>
            )}
            {data.outputFields.length > 0 && (
              <span className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-[hsl(var(--success))]/10 text-[hsl(var(--success))]">
                {data.outputFields.length} out
              </span>
            )}
          </div>
        )}
      </div>

      <Handle type="source" position={Position.Right} isConnectable={isConnectable} className="!bg-[hsl(var(--success))] !w-2 !h-2 !border-2 !border-card" />
    </div>
  )
}

// ─── Field Action Node (Lineage View) ───────────────────────────────────────

function FieldActionNode({ data, isConnectable }: NodeProps<Node<LineageNodeData>>) {
  const [expanded, setExpanded] = useState(true)
  const isLlm = data.type === "llm"
  const accentVar = isLlm ? "--chart-2" : "--success"

  return (
    <div className={`w-[300px] rounded-lg border bg-card shadow-sm overflow-hidden ${
      isLlm ? "border-[hsl(var(--chart-2))]/30" : "border-[hsl(var(--success))]/30"
    }`}>
      {/* Input handles */}
      {data.inputFields.map((field, idx) => (
        <Handle
          key={`input-${field}`}
          type="target"
          position={Position.Left}
          id={`input-${field}`}
          isConnectable={isConnectable}
          className={`!w-1.5 !h-1.5 !border-0 ${isLlm ? "!bg-[hsl(var(--chart-2))]" : "!bg-[hsl(var(--success))]"}`}
          style={{ top: expanded ? `${68 + idx * 26}px` : "50%" }}
        />
      ))}

      {/* Output handles */}
      {data.outputFields.map((field, idx) => {
        const inputCount = data.inputFields.length
        const yOffset = expanded ? 68 + inputCount * 26 + 32 + idx * 26 : 50
        return (
          <Handle
            key={`output-${field}`}
            type="source"
            position={Position.Right}
            id={`output-${field}`}
            isConnectable={isConnectable}
            className="!bg-[hsl(var(--warning))] !w-1.5 !h-1.5 !border-0"
            style={{ top: expanded ? `${yOffset}px` : "50%" }}
          />
        )
      })}

      {/* Header - dbt style */}
      <button
        className="w-full flex items-center gap-0 hover:bg-accent/30 transition-colors"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-center px-3 py-2.5 border-r border-border/50">
          <div className={`h-7 w-7 rounded flex items-center justify-center text-[9px] font-bold tracking-wider shrink-0 ${
            isLlm
              ? "bg-[hsl(var(--chart-2))]/15 text-[hsl(var(--chart-2))]"
              : "bg-[hsl(var(--success))]/15 text-[hsl(var(--success))]"
          }`}>
            {isLlm ? "LLM" : "TOOL"}
          </div>
        </div>
        <div className="flex-1 flex items-center justify-between px-3 py-2.5">
          <span className="text-xs font-mono font-semibold text-foreground truncate">{data.label}</span>
          <span className="text-[10px] text-muted-foreground ml-2">{expanded ? "\u25BC" : "\u25B6"}</span>
        </div>
      </button>

      {/* Fields */}
      {expanded && (
        <div className="border-t border-border/50 px-3 py-2 space-y-2">
          {data.inputFields.length > 0 && (
            <div>
              <div className="text-[9px] font-semibold text-muted-foreground uppercase tracking-wider mb-1">Inputs</div>
              <div className="space-y-0.5">
                {data.inputFields.map((field) => (
                  <div key={field} className="flex items-center gap-1.5 px-2 py-0.5 rounded bg-[hsl(var(--chart-2))]/8">
                    <span className="h-1 w-1 rounded-full shrink-0" style={{ backgroundColor: `hsl(var(${accentVar}))` }} />
                    <span className="text-[10px] font-mono text-foreground/80 truncate">{field}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
          {data.outputFields.length > 0 && (
            <div>
              <div className="text-[9px] font-semibold text-muted-foreground uppercase tracking-wider mb-1">Outputs</div>
              <div className="space-y-0.5">
                {data.outputFields.map((field) => (
                  <div key={field} className="flex items-center justify-between px-2 py-0.5 rounded bg-[hsl(var(--warning))]/8">
                    <span className="text-[10px] font-mono text-foreground/80 truncate">{field}</span>
                    <span className="h-1 w-1 rounded-full bg-[hsl(var(--warning))] shrink-0" />
                  </div>
                ))}
              </div>
            </div>
          )}
          {data.droppedFields.length > 0 && (
            <div>
              <div className="text-[9px] font-semibold text-muted-foreground uppercase tracking-wider mb-1">Dropped</div>
              <div className="space-y-0.5">
                {data.droppedFields.map((field) => (
                  <div key={field} className="px-2 py-0.5 rounded bg-[hsl(var(--destructive))]/8">
                    <span className="text-[10px] font-mono text-muted-foreground line-through truncate">{field}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ─── DAG Content ────────────────────────────────────────────────────────────

function DAGContent({
  actions,
  workflowId,
  mode,
  onNodeClick,
}: {
  actions: Record<string, Action>
  workflowId: string
  mode: "dag" | "lineage"
  onNodeClick?: (name: string) => void
}) {
  const [nodes, setNodes, onNodesChange] = useNodesState([])
  const [edges, setEdges, onEdgesChange] = useEdgesState([])
  const { fitView } = useReactFlow()

  const nodeTypes = useMemo(
    () => ({
      modelNode: ModelNode,
      toolNode: ToolNode,
      fieldActionNode: FieldActionNode,
    }),
    [],
  )

  useEffect(() => {
    const transformed =
      mode === "lineage"
        ? transformWorkflowToFieldLineage(actions, workflowId)
        : transformWorkflowToReactFlow(actions, workflowId)

    setNodes(transformed.nodes as Node[])
    setEdges(transformed.edges)

    setTimeout(() => {
      try {
        fitView({ padding: 0.2, duration: 500 })
      } catch {
        // fitView can fail before render
      }
    }, 100)
  }, [actions, workflowId, mode, fitView, setNodes, setEdges])

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
        type: "smoothstep",
        animated: false,
        markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16 },
      }}
      className="rounded-lg"
    >
      <Background gap={24} size={1} className="!bg-background" />
      <Controls className="!bg-card !border-border !shadow-md !rounded-lg" showInteractive={false} />
      <MiniMap
        nodeColor={(n) =>
          n.type === "modelNode" ? "hsl(var(--chart-2))"
          : n.type === "toolNode" ? "hsl(var(--success))"
          : "hsl(var(--warning))"
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
  mode = "dag",
  onNodeClick,
}: {
  actions: Record<string, Action>
  workflowId: string
  mode?: "dag" | "lineage"
  onNodeClick?: (name: string) => void
}) {
  return (
    <div className="h-[600px] w-full rounded-xl border border-border bg-card overflow-hidden">
      <ReactFlowProvider>
        <DAGContent actions={actions} workflowId={workflowId} mode={mode} onNodeClick={onNodeClick} />
      </ReactFlowProvider>
    </div>
  )
}
