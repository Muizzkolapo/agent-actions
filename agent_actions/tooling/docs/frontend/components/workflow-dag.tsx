"use client"

import { useState, useCallback, useEffect, useLayoutEffect, useMemo, useRef, type RefObject } from "react"
import {
  ReactFlow,
  Background,
  Controls,
  ControlButton,
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
import { ChevronDown, ChevronRight, Maximize2, Minimize2 } from "lucide-react"
import {
  transformWorkflowToReactFlow,
  initialViewport,
  traceLineage,
  FIT_MAX_ZOOM,
  FIT_PADDING,
  MAX_ZOOM,
  MIN_ZOOM,
  NODE_HEIGHT,
  NODE_WIDTH,
  type DAGNodeData,
} from "@/lib/dag-transformer"
import type { Action } from "@/lib/mock-data"

// ─── DAG Node (expandable to show fields) ────────────────────────

// On the header row, not the node's centre, so an expanded node keeps its edges in place.
const HANDLE_STYLE = { top: NODE_HEIGHT / 2 }

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
        selected ? "border-success ring-1 ring-success" : "border-border-2"
      }`}
    >
      <Handle type="target" position={Position.Left} isConnectable={isConnectable} style={HANDLE_STYLE}
        className={`!h-1.5 !w-1.5 !min-w-0 !border-0 ${isLlm ? "!bg-llm" : "!bg-tool"}`}
      />

      {/* Header row — clicks bubble to React Flow's node handlers; only the chevron stops propagation */}
      <div className="flex items-center" style={{ height: NODE_HEIGHT - 2 }}>
        <div className={`w-[3px] self-stretch ${isLlm ? "bg-llm" : "bg-tool"}`} />
        <div className="flex min-w-0 flex-1 items-center gap-1.5 px-2.5">
          <div className="min-w-0 flex-1">
            <div className="truncate font-mono text-[12px] font-medium text-foreground">{data.label}</div>
            <div className="mt-0.5 truncate font-mono text-[10px] text-muted-foreground">{isLlm ? data.model : data.impl}</div>
          </div>
          <span className={`shrink-0 font-mono text-[9px] font-semibold ${isLlm ? "text-llm-t" : "text-tool-t"}`}>{isLlm ? "LLM" : "TOOL"}</span>
          {hasFields && (
            <button
              type="button"
              aria-label={expanded ? "Collapse fields" : "Expand fields"}
              onClick={toggle}
              onDoubleClick={(e) => e.stopPropagation()}
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

      <Handle type="source" position={Position.Right} isConnectable={isConnectable} style={HANDLE_STYLE}
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

const FIT_OPTIONS = { padding: FIT_PADDING, maxZoom: FIT_MAX_ZOOM }
const PATH_EDGE_STYLE = { stroke: "hsl(var(--success))", strokeWidth: 2 }
const PATH_EDGE_MARKER = { type: MarkerType.ArrowClosed, width: 12, height: 12, color: "hsl(var(--success))" }
const FADED_EDGE_STYLE = { stroke: "hsl(var(--muted-2))", strokeWidth: 1, opacity: 0.15 }

function FullscreenButton({ target }: { target: RefObject<HTMLDivElement | null> }) {
  const [isFullscreen, setIsFullscreen] = useState(false)

  useEffect(() => {
    const sync = () => setIsFullscreen(document.fullscreenElement === target.current)
    document.addEventListener("fullscreenchange", sync)
    return () => document.removeEventListener("fullscreenchange", sync)
  }, [target])

  const toggle = () => {
    if (document.fullscreenElement) void document.exitFullscreen()
    else void target.current?.requestFullscreen()
  }

  const label = isFullscreen ? "Exit full screen" : "Full screen"
  return (
    <ControlButton onClick={toggle} title={label} aria-label={label} className="react-flow__controls-fullscreen">
      {isFullscreen ? <Minimize2 /> : <Maximize2 />}
    </ControlButton>
  )
}

// ─── DAG Content ────────────────────────────────────────────────────────────

function DAGContent({
  actions,
  workflowId,
  selectedKey,
  onNodeOpen,
  fullscreenTarget,
}: {
  actions: Record<string, Action>
  workflowId: string
  selectedKey?: string | null
  onNodeOpen?: (name: string) => void
  fullscreenTarget: RefObject<HTMLDivElement | null>
}) {
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([])
  const [tracedKey, setTracedKey] = useState<string | null>(null)
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
    setTracedKey(null)

    setTimeout(() => {
      const { width, height } = store.getState()
      const view = initialViewport(transformed.nodes, width, height)
      if (view === "fit") fitView({ ...FIT_OPTIONS, duration: 500 })
      else setViewport(view, { duration: 500 })
    }, 100)
  }, [actions, workflowId, fitView, setViewport, store, setNodes, setEdges])

  // Moving to another action from the details panel traces that action too.
  useEffect(() => {
    if (selectedKey) setTracedKey(selectedKey)
  }, [selectedKey])

  const lineage = useMemo(
    () => (tracedKey ? traceLineage(tracedKey, edges) : null),
    [tracedKey, edges],
  )

  const shownNodes = useMemo(
    () =>
      nodes.map((n) => ({
        ...n,
        selected: n.id === tracedKey,
        style: { ...n.style, opacity: lineage && !lineage.nodes.has(n.id) ? 0.3 : 1 },
      })),
    [nodes, lineage, tracedKey],
  )

  const shownEdges = useMemo(
    () =>
      lineage
        ? edges.map((e) =>
            lineage.edges.has(e.id)
              ? { ...e, zIndex: 1, style: PATH_EDGE_STYLE, markerEnd: PATH_EDGE_MARKER }
              : { ...e, style: FADED_EDGE_STYLE },
          )
        : edges,
    [edges, lineage],
  )

  // A double click fires two clicks first, so a click sets the trace rather than toggling it.
  const handleNodeClick = useCallback((_: React.MouseEvent, node: Node) => setTracedKey(node.id), [])
  const handlePaneClick = useCallback(() => setTracedKey(null), [])
  const handleNodeDoubleClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      // The details panel sits outside the graph, so leave full screen to show it.
      if (document.fullscreenElement) void document.exitFullscreen()
      onNodeOpen?.(node.id)
    },
    [onNodeOpen],
  )

  return (
    <ReactFlow
      nodes={shownNodes}
      edges={shownEdges}
      nodeTypes={nodeTypes}
      onNodesChange={onNodesChange}
      onEdgesChange={onEdgesChange}
      onNodeClick={handleNodeClick}
      onNodeDoubleClick={handleNodeDoubleClick}
      onPaneClick={handlePaneClick}
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
      <Controls className="!rounded-control !border-border !bg-surface !shadow-none" showInteractive={false} fitViewOptions={FIT_OPTIONS}>
        <FullscreenButton target={fullscreenTarget} />
      </Controls>
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

// ─── Height ─────────────────────────────────────────────────────────────────

const MIN_GRAPH_HEIGHT = 300

// Fill from the graph's top edge down to main's bottom padding, so the page does not
// scroll. The header above varies with the description and the window width: measure it.
function useHeightToBottomOfMain(ref: RefObject<HTMLDivElement | null>) {
  const [height, setHeight] = useState(MIN_GRAPH_HEIGHT)

  useLayoutEffect(() => {
    const el = ref.current
    const main = el?.closest("main")
    if (!el || !main) return
    const fit = () => {
      const top = el.getBoundingClientRect().top - main.getBoundingClientRect().top + main.scrollTop
      const bottomPadding = parseFloat(getComputedStyle(main).paddingBottom)
      setHeight(Math.max(MIN_GRAPH_HEIGHT, Math.floor(main.clientHeight - top - bottomPadding)))
    }
    fit()
    // main resizes with the window; its first child resizes when the header above wraps.
    const observer = new ResizeObserver(fit)
    observer.observe(main)
    if (main.firstElementChild) observer.observe(main.firstElementChild)
    // The screen slides in, so the first reading of its top edge is a few px low.
    main.addEventListener("animationend", fit)
    return () => {
      observer.disconnect()
      main.removeEventListener("animationend", fit)
    }
  }, [ref])

  return height
}

// ─── Exported Component ─────────────────────────────────────────────────────

export function WorkflowDAGView({
  actions,
  workflowId,
  selectedKey,
  onNodeOpen,
}: {
  actions: Record<string, Action>
  workflowId: string
  selectedKey?: string | null
  onNodeOpen?: (name: string) => void
}) {
  const containerRef = useRef<HTMLDivElement>(null)
  const height = useHeightToBottomOfMain(containerRef)
  return (
    <div ref={containerRef} className="w-full overflow-hidden rounded-card border border-border bg-well" style={{ height }}>
      <ReactFlowProvider>
        <DAGContent actions={actions} workflowId={workflowId} selectedKey={selectedKey} onNodeOpen={onNodeOpen} fullscreenTarget={containerRef} />
      </ReactFlowProvider>
    </div>
  )
}
