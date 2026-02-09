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
} from "@xyflow/react"
import "@xyflow/react/dist/style.css"
import { Badge } from "@/components/ui/badge"
import {
  transformWorkflowToReactFlow,
  transformWorkflowToFieldLineage,
  type DAGNodeData,
  type LineageNodeData,
} from "@/lib/dag-transformer"
import type { Action } from "@/lib/mock-data"

// ─── Model Node ──────────────────────────────────────────────────────────────

function ModelNode({ data, isConnectable }: NodeProps<Node<DAGNodeData>>) {
  const providerColor =
    data.provider === "openai" ? "text-emerald-400"
    : data.provider === "anthropic" ? "text-purple-400"
    : data.provider === "google" ? "text-blue-400"
    : "text-muted-foreground"

  return (
    <div className="w-[320px] rounded-lg border-2 border-blue-500/60 bg-card shadow-lg shadow-blue-500/10 overflow-hidden">
      <Handle type="target" position={Position.Left} isConnectable={isConnectable} className="!bg-blue-500 !w-2.5 !h-2.5 !border-0" />

      {/* Header */}
      <div className="flex items-center gap-2.5 px-3.5 py-2.5 border-b border-border">
        <div className="h-7 w-7 rounded-full bg-blue-500/20 flex items-center justify-center text-sm shrink-0">
          <span className="text-blue-400">AI</span>
        </div>
        <span className="text-sm font-mono font-semibold text-foreground truncate">{data.label}</span>
      </div>

      {/* Body */}
      <div className="px-3.5 py-2 text-xs space-y-1">
        <div className="flex justify-between">
          <span className="text-muted-foreground">Provider</span>
          <span className={`capitalize font-medium ${providerColor}`}>{data.provider}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">Model</span>
          <span className="font-mono text-foreground">{data.model}</span>
        </div>
      </div>

      {/* Fields summary */}
      {(data.inputFields.length > 0 || data.outputFields.length > 0) && (
        <div className="px-3.5 py-2 border-t border-border/50">
          {data.fieldsExpanded ? (
            <div className="space-y-2">
              {data.inputFields.length > 0 && (
                <div>
                  <div className="text-[10px] font-semibold text-blue-400 uppercase tracking-wider mb-1">Inputs</div>
                  <div className="space-y-0.5">
                    {data.inputFields.map((f) => (
                      <div key={f} className="px-2 py-0.5 rounded bg-blue-500/10 text-[10px] font-mono text-blue-300">{f}</div>
                    ))}
                  </div>
                </div>
              )}
              {data.outputFields.length > 0 && (
                <div>
                  <div className="text-[10px] font-semibold text-emerald-400 uppercase tracking-wider mb-1">Outputs</div>
                  <div className="space-y-0.5">
                    {data.outputFields.map((f) => (
                      <div key={f} className="px-2 py-0.5 rounded bg-emerald-500/10 text-[10px] font-mono text-emerald-300">{f}</div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="flex items-center gap-2 text-[10px]">
              {data.inputFields.length > 0 && (
                <span className="text-blue-400">{data.inputFields.length} inputs</span>
              )}
              {data.inputFields.length > 0 && data.outputFields.length > 0 && (
                <span className="text-muted-foreground/40">|</span>
              )}
              {data.outputFields.length > 0 && (
                <span className="text-emerald-400">{data.outputFields.length} outputs</span>
              )}
            </div>
          )}
        </div>
      )}

      <Handle type="source" position={Position.Right} isConnectable={isConnectable} className="!bg-blue-500 !w-2.5 !h-2.5 !border-0" />
    </div>
  )
}

// ─── Tool Node ───────────────────────────────────────────────────────────────

function ToolNode({ data, isConnectable }: NodeProps<Node<DAGNodeData>>) {
  return (
    <div className="w-[320px] rounded-lg border-2 border-emerald-500/60 bg-card shadow-lg shadow-emerald-500/10 overflow-hidden">
      <Handle type="target" position={Position.Left} isConnectable={isConnectable} className="!bg-emerald-500 !w-2.5 !h-2.5 !border-0" />

      {/* Header */}
      <div className="flex items-center gap-2.5 px-3.5 py-2.5 border-b border-border">
        <div className="h-7 w-7 rounded-full bg-emerald-500/20 flex items-center justify-center text-sm shrink-0">
          <span className="text-emerald-400">FN</span>
        </div>
        <span className="text-sm font-mono font-semibold text-foreground truncate">{data.label}</span>
      </div>

      {/* Body */}
      <div className="px-3.5 py-2 text-xs space-y-1">
        <div className="flex justify-between">
          <span className="text-muted-foreground">Type</span>
          <span className="font-mono text-emerald-400">tool</span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">Impl</span>
          <span className="font-mono text-foreground">{data.impl}</span>
        </div>
      </div>

      {/* Fields summary */}
      {(data.inputFields.length > 0 || data.outputFields.length > 0) && (
        <div className="px-3.5 py-2 border-t border-border/50">
          {data.fieldsExpanded ? (
            <div className="space-y-2">
              {data.inputFields.length > 0 && (
                <div>
                  <div className="text-[10px] font-semibold text-blue-400 uppercase tracking-wider mb-1">Inputs</div>
                  <div className="space-y-0.5">
                    {data.inputFields.map((f) => (
                      <div key={f} className="px-2 py-0.5 rounded bg-blue-500/10 text-[10px] font-mono text-blue-300">{f}</div>
                    ))}
                  </div>
                </div>
              )}
              {data.outputFields.length > 0 && (
                <div>
                  <div className="text-[10px] font-semibold text-emerald-400 uppercase tracking-wider mb-1">Outputs</div>
                  <div className="space-y-0.5">
                    {data.outputFields.map((f) => (
                      <div key={f} className="px-2 py-0.5 rounded bg-emerald-500/10 text-[10px] font-mono text-emerald-300">{f}</div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="flex items-center gap-2 text-[10px]">
              {data.inputFields.length > 0 && (
                <span className="text-blue-400">{data.inputFields.length} inputs</span>
              )}
              {data.inputFields.length > 0 && data.outputFields.length > 0 && (
                <span className="text-muted-foreground/40">|</span>
              )}
              {data.outputFields.length > 0 && (
                <span className="text-emerald-400">{data.outputFields.length} outputs</span>
              )}
            </div>
          )}
        </div>
      )}

      <Handle type="source" position={Position.Right} isConnectable={isConnectable} className="!bg-emerald-500 !w-2.5 !h-2.5 !border-0" />
    </div>
  )
}

// ─── Field Action Node (Lineage View) ────────────────────────────────────────

function FieldActionNode({ data, isConnectable }: NodeProps<Node<LineageNodeData>>) {
  const [expanded, setExpanded] = useState(false)
  const isLlm = data.type === "llm"
  const accentColor = isLlm ? "blue" : "emerald"

  return (
    <div className={`w-[320px] rounded-lg border bg-card shadow-md overflow-hidden ${
      isLlm ? "border-blue-500/40" : "border-emerald-500/40"
    }`}>
      {/* Input handles */}
      {data.inputFields.map((field, idx) => (
        <Handle
          key={`input-${field}`}
          type="target"
          position={Position.Left}
          id={`input-${field}`}
          isConnectable={isConnectable}
          className="!bg-blue-500 !w-1.5 !h-1.5 !border-0"
          style={{ top: expanded ? `${80 + idx * 28}px` : "50%" }}
        />
      ))}

      {/* Output handles */}
      {data.outputFields.map((field, idx) => {
        const inputCount = data.inputFields.length
        const yOffset = expanded ? 80 + inputCount * 28 + 36 + idx * 28 : 50
        return (
          <Handle
            key={`output-${field}`}
            type="source"
            position={Position.Right}
            id={`output-${field}`}
            isConnectable={isConnectable}
            className="!bg-amber-500 !w-1.5 !h-1.5 !border-0"
            style={{ top: expanded ? `${yOffset}px` : "50%" }}
          />
        )
      })}

      {/* Header */}
      <button
        className="w-full flex items-center gap-2 px-3.5 py-2.5 border-b border-border/50 hover:bg-accent/30 transition-colors"
        onClick={() => setExpanded(!expanded)}
      >
        <div className={`h-5 w-5 rounded flex items-center justify-center text-[10px] shrink-0 ${
          isLlm ? "bg-blue-500/20 text-blue-400" : "bg-emerald-500/20 text-emerald-400"
        }`}>
          {isLlm ? "AI" : "FN"}
        </div>
        <span className="text-xs font-mono font-medium text-foreground flex-1 text-left truncate">{data.label}</span>
        <span className="text-[10px] text-muted-foreground">{expanded ? "\u25BC" : "\u25B6"}</span>
      </button>

      {/* Body */}
      <div className="px-3.5 py-2">
        {expanded ? (
          <div className="space-y-3">
            {data.inputFields.length > 0 && (
              <div>
                <div className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider mb-1.5">Inputs</div>
                <div className="space-y-1">
                  {data.inputFields.map((field) => (
                    <div key={field} className="flex items-center gap-1.5 px-2 py-1 rounded bg-blue-500/10">
                      <span className="h-1.5 w-1.5 rounded-full bg-blue-500 shrink-0" />
                      <span className="text-[11px] font-mono text-blue-300">{field}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
            {data.outputFields.length > 0 && (
              <div>
                <div className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider mb-1.5">Outputs</div>
                <div className="space-y-1">
                  {data.outputFields.map((field) => (
                    <div key={field} className="flex items-center justify-between px-2 py-1 rounded bg-amber-500/10">
                      <span className="text-[11px] font-mono text-amber-300">{field}</span>
                      <span className="h-1.5 w-1.5 rounded-full bg-amber-500 shrink-0" />
                    </div>
                  ))}
                </div>
              </div>
            )}
            {data.droppedFields.length > 0 && (
              <div>
                <div className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider mb-1.5">Dropped</div>
                <div className="space-y-1">
                  {data.droppedFields.map((field) => (
                    <div key={field} className="flex items-center gap-1.5 px-2 py-1 rounded bg-red-500/10">
                      <span className="text-[11px] font-mono text-red-400 line-through">{field}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        ) : (
          <div className="flex items-center gap-2 text-[10px]">
            {data.inputFields.length > 0 && (
              <span className="text-blue-400">{data.inputFields.length} inputs</span>
            )}
            {data.inputFields.length > 0 && data.outputFields.length > 0 && (
              <span className="text-muted-foreground/40">|</span>
            )}
            {data.outputFields.length > 0 && (
              <span className="text-amber-400">{data.outputFields.length} outputs</span>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

// ─── DAG Content (uses ReactFlow hooks) ──────────────────────────────────────

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
        fitView({ padding: 0.15, duration: 600 })
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
      defaultEdgeOptions={{ type: "smoothstep", animated: true }}
      className="rounded-lg"
    >
      <Background gap={20} size={1} className="!bg-secondary/30" />
      <Controls className="!bg-card !border-border !shadow-lg" showInteractive={false} />
      <MiniMap
        nodeColor={(n) => (n.type === "modelNode" ? "#3b82f6" : n.type === "toolNode" ? "#10b981" : "#f59e0b")}
        className="!bg-card !border-border"
        nodeBorderRadius={4}
      />
    </ReactFlow>
  )
}

// ─── Exported Components ─────────────────────────────────────────────────────

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
