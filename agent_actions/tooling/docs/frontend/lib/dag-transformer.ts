import dagre from "dagre"
import type { Node, Edge } from "@xyflow/react"
import type { Action } from "./mock-data"

// ─── Provider detection ──────────────────────────────────────────────────────

function getProvider(model?: string): string {
  if (!model) return "unknown"
  if (model.includes("gpt") || model.includes("o1") || model.includes("o3")) return "openai"
  if (model.includes("claude")) return "anthropic"
  if (model.includes("gemini")) return "google"
  if (model.includes("llama") || model.includes("mistral")) return "ollama"
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

  for (const [name, action] of Object.entries(actions)) {
    if (action.wf !== workflowId) continue

    const provider = action.type === "llm" ? getProvider(action.model) : "Tool"
    const { inputFields, outputFields, droppedFields } = extractActionFields(action)

    nodes.push({
      id: name,
      type: action.type === "llm" ? "modelNode" : "toolNode",
      data: {
        label: name,
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

    for (const dep of action.deps) {
      edges.push({
        id: `e${edgeId++}`,
        source: dep,
        target: name,
        type: "default",
        animated: false,
        style: { stroke: "hsl(var(--muted-foreground))", strokeWidth: 1.5, opacity: 0.7 },
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

export function transformWorkflowToReactFlow(actions: Record<string, Action>, workflowId: string) {
  const { nodes, edges } = buildDAGNodesAndEdges(actions, workflowId)
  return applyDagreLayout(nodes, edges, { nodeWidth: 320, nodeHeight: 100, nodesep: 120, ranksep: 240 })
}

