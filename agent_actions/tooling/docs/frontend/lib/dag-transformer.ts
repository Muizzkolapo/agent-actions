import dagre from "dagre"
import { getViewportForBounds, type Node, type Edge, type Viewport } from "@xyflow/react"
import type { Action } from "./mock-data"

// ─── Provider detection ──────────────────────────────────────────────────────

function getProvider(model?: string): string {
  if (!model) return "unknown"
  if (model.includes("gpt") || model.includes("o1") || model.includes("o3")) return "openai"
  if (model.includes("claude")) return "anthropic"
  if (model.includes("gemini")) return "google"
  if (model.includes("llama") || model.includes("mistral")) return "ollama_local"
  return "unknown"
}

// ─── Field extraction ────────────────────────────────────────────────────────

export function extractActionFields(action: Action) {
  const inputFieldSet = new Set<string>()

  for (const field of action.inputs) inputFieldSet.add(field)
  for (const field of action.observe) inputFieldSet.add(field)

  const inputFields = Array.from(inputFieldSet)

  let outputFields: string[] = []
  if (action.outputFields.length > 0) {
    outputFields = action.outputFields.map((f) => f.name)
  } else if (action.outputs.length > 0) {
    outputFields = [...action.outputs]
  }

  const droppedFields = [...action.drops]

  return { inputFields, outputFields, droppedFields }
}

// ─── DAG view (action-level nodes) ──────────────────────────────────────────

export interface DAGNodeData {
  label: string
  model: string
  provider: string
  impl: string
  description: string
  inputFields: string[]
  outputFields: string[]
  droppedFields: string[]
  [key: string]: unknown
}

export function buildDAGNodesAndEdges(actions: Record<string, Action>, workflowId: string) {
  const nodes: Node<DAGNodeData>[] = []
  const edges: Edge[] = []
  let edgeId = 0

  const nodeIds = new Set<string>()

  for (const [key, action] of Object.entries(actions)) {
    if (action.wf !== workflowId) continue

    const provider = action.type === "llm" ? getProvider(action.model) : "Tool"
    const { inputFields, outputFields, droppedFields } = extractActionFields(action)
    const shortName = key.includes("/") ? key.split("/").pop()! : key

    nodes.push({
      id: key,
      type: action.type === "llm" ? "modelNode" : "toolNode",
      data: {
        label: shortName,
        model: action.model || "unknown",
        provider,
        impl: action.impl || "tool",
        description: action.intent || "",
        inputFields,
        outputFields,
        droppedFields,
      },
      position: { x: 0, y: 0 },
    })
    nodeIds.add(key)
  }

  for (const [key, action] of Object.entries(actions)) {
    if (action.wf !== workflowId) continue
    for (const dep of action.deps) {
      const depKey = `${workflowId}/${dep}`
      if (!nodeIds.has(depKey)) continue
      edges.push({
        id: `e${edgeId++}`,
        source: depKey,
        target: key,
      })
    }
  }

  return { nodes, edges }
}

// ─── Layout ─────────────────────────────────────────────────────────────────

export function applyDagreLayout<T extends Record<string, unknown>>(
  nodes: Node<T>[],
  edges: Edge[],
  opts: { direction?: "LR" | "TB"; nodeWidth?: number; nodeHeight?: number; nodesep?: number; ranksep?: number } = {},
) {
  const {
    direction = "LR",
    nodeWidth = 320,
    nodeHeight = 120,
    nodesep = 120,
    ranksep = 200,
  } = opts

  const g = new dagre.graphlib.Graph()
  g.setDefaultEdgeLabel(() => ({}))
  g.setGraph({ rankdir: direction, nodesep, ranksep, marginx: 50, marginy: 50 })

  for (const node of nodes) {
    g.setNode(node.id, { width: nodeWidth, height: nodeHeight })
  }
  for (const edge of edges) {
    g.setEdge(edge.source, edge.target)
  }

  dagre.layout(g)

  const positioned = nodes.map((node) => {
    const pos = g.node(node.id)
    return {
      ...node,
      position: {
        x: pos.x - nodeWidth / 2,
        y: pos.y - nodeHeight / 2,
      },
    }
  })

  return { nodes: positioned, edges }
}

// ─── Public API ─────────────────────────────────────────────────────────────

export const NODE_WIDTH = 240
export const NODE_HEIGHT = 56

export function transformWorkflowToReactFlow(actions: Record<string, Action>, workflowId: string) {
  const { nodes, edges } = buildDAGNodesAndEdges(actions, workflowId)
  return applyDagreLayout(nodes, edges, { nodeWidth: NODE_WIDTH, nodeHeight: NODE_HEIGHT, nodesep: 20, ranksep: 50 })
}

// ─── Initial viewport ───────────────────────────────────────────────────────

export const MIN_ZOOM = 0.02
export const MAX_ZOOM = 1.5
export const FIT_PADDING = 0.1
// Below this fit zoom the labels cannot be read, so open on the first stage instead.
export const MIN_READABLE_ZOOM = 0.5
export const READABLE_ZOOM = 0.8
const FIRST_STAGE_INSET = 40

export function initialViewport(nodes: Node[], width: number, height: number): Viewport | "fit" {
  if (nodes.length === 0 || width === 0 || height === 0) return "fit"

  const xs = nodes.map((n) => n.position.x)
  const ys = nodes.map((n) => n.position.y)
  const minX = Math.min(...xs)
  const minY = Math.min(...ys)
  const bounds = {
    x: minX,
    y: minY,
    width: Math.max(...xs) + NODE_WIDTH - minX,
    height: Math.max(...ys) + NODE_HEIGHT - minY,
  }
  const fit = getViewportForBounds(bounds, width, height, MIN_ZOOM, MAX_ZOOM, FIT_PADDING)
  if (fit.zoom >= MIN_READABLE_ZOOM) return "fit"

  const firstStage = nodes.filter((n) => n.position.x < minX + 1).map((n) => n.position.y)
  const centerY = (Math.min(...firstStage) + Math.max(...firstStage) + NODE_HEIGHT) / 2
  return {
    x: FIRST_STAGE_INSET - minX * READABLE_ZOOM,
    y: height / 2 - centerY * READABLE_ZOOM,
    zoom: READABLE_ZOOM,
  }
}


// ─── Lineage ────────────────────────────────────────────────────────────────

export interface Lineage {
  nodes: Set<string>
  edges: Set<string>
}

// Every node upstream and downstream of `id`, and only the edges on a path through it.
export function traceLineage(id: string, edges: Edge[]): Lineage {
  const walk = (from: "source" | "target", to: "source" | "target") => {
    const seen = new Set<string>([id])
    const queue = [id]
    while (queue.length > 0) {
      const current = queue.pop()!
      for (const e of edges) {
        if (e[to] === current && !seen.has(e[from])) {
          seen.add(e[from])
          queue.push(e[from])
        }
      }
    }
    return seen
  }
  const up = walk("source", "target")
  const down = walk("target", "source")

  const onPath = new Set<string>()
  for (const e of edges) {
    const upstream = up.has(e.source) && up.has(e.target)
    const downstream = down.has(e.source) && down.has(e.target)
    if (upstream || downstream) onPath.add(e.id)
  }
  return { nodes: new Set([...up, ...down]), edges: onPath }
}
