import dagre from "dagre"
import type { Node, Edge } from "@xyflow/react"
import type { Action } from "./mock-data"

// ─── Shared action shape (Docs + VS Code) ───────────────────────────────────

export type DAGActionKind = "llm" | "tool" | "unknown"

export type DAGActionStatus =
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | "skipped"

export interface DAGAction {
  name: string
  deps: string[]
  kind: DAGActionKind
  intent?: string
  model?: string
  impl?: string
  status?: DAGActionStatus
  inputs?: string[]
  observe?: string[]
  outputs?: string[]
  outputFields?: string[]
  drops?: string[]
}

/** Minimal shape the VS Code host sends; kept UI-agnostic (no vscode types). */
export interface VsCodeDagActionInput {
  name: string
  dependencies: string[]
  kind?: DAGActionKind
  status?: DAGActionStatus
  intent?: string
  model?: string
  impl?: string
  inputs?: string[]
  observe?: string[]
  outputs?: string[]
  outputFields?: string[]
  drops?: string[]
}

export const DAG_LAYOUT_DEFAULTS = {
  nodeWidth: 320,
  nodeHeight: 100,
  nodesep: 120,
  ranksep: 240,
} as const

export type UnknownDepsPolicy = "filter" | "materialize"

export interface TransformActionsToReactFlowOptions {
  direction: "LR" | "TB"
  unknownDeps?: UnknownDepsPolicy
  nodeWidth?: number
  nodeHeight?: number
  nodesep?: number
  ranksep?: number
}

// ─── Provider detection ──────────────────────────────────────────────────────

function getProvider(model?: string): string {
  if (!model) return "unknown"
  if (model.includes("gpt") || model.includes("o1") || model.includes("o3")) return "openai"
  if (model.includes("claude")) return "anthropic"
  if (model.includes("gemini")) return "google"
  if (model.includes("llama") || model.includes("mistral")) return "ollama_local"
  return "unknown"
}

// ─── Field extraction (docs Action records) ────────────────────────────────

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

function collectFieldArraysFromDAGAction(a: DAGAction): {
  inputFields: string[]
  outputFields: string[]
  droppedFields: string[]
} {
  const inputFieldSet = new Set<string>()
  for (const field of a.inputs ?? []) inputFieldSet.add(field)
  for (const field of a.observe ?? []) inputFieldSet.add(field)
  const inputFields = Array.from(inputFieldSet)

  let outputFields: string[] = []
  if ((a.outputFields?.length ?? 0) > 0) {
    outputFields = [...(a.outputFields ?? [])]
  } else if ((a.outputs?.length ?? 0) > 0) {
    outputFields = [...(a.outputs ?? [])]
  }

  const droppedFields = [...(a.drops ?? [])]
  return { inputFields, outputFields, droppedFields }
}

// ─── DAG node render payload ────────────────────────────────────────────────

export interface DAGNodeData {
  label: string
  kind: DAGActionKind
  status?: DAGActionStatus
  model: string
  provider: string
  impl: string
  description: string
  inputFields: string[]
  outputFields: string[]
  droppedFields: string[]
  [key: string]: unknown
}

function dagActionToNodeData(a: DAGAction): DAGNodeData {
  const provider =
    a.kind === "llm" ? getProvider(a.model) : a.kind === "tool" ? "Tool" : "Unknown"
  const { inputFields, outputFields, droppedFields } = collectFieldArraysFromDAGAction(a)
  return {
    label: a.name,
    kind: a.kind,
    status: a.status,
    model: a.model ?? "unknown",
    provider,
    impl: a.impl ?? "tool",
    description: a.intent ?? "",
    inputFields,
    outputFields,
    droppedFields,
  }
}

function reactFlowNodeType(kind: DAGActionKind): "modelNode" | "toolNode" {
  return kind === "llm" ? "modelNode" : "toolNode"
}

// ─── Adapters ───────────────────────────────────────────────────────────────

export function adaptDocsActionsToDAGActions(
  actions: Record<string, Action>,
  workflowId: string,
): DAGAction[] {
  const out: DAGAction[] = []
  for (const [name, action] of Object.entries(actions)) {
    if (action.wf !== workflowId) continue
    out.push({
      name,
      deps: [...action.deps],
      kind: action.type === "llm" ? "llm" : "tool",
      intent: action.intent,
      model: action.model,
      impl: action.impl,
      inputs: action.inputs,
      observe: action.observe,
      outputs: action.outputs,
      outputFields: action.outputFields.map((f) => f.name),
      drops: action.drops,
    })
  }
  return out
}

export function adaptVsCodeDagInputsToDAGActions(actions: VsCodeDagActionInput[]): DAGAction[] {
  return actions.map((a) => ({
    name: a.name,
    deps: [...a.dependencies],
    kind: a.kind ?? "tool",
    intent: a.intent,
    model: a.model,
    impl: a.impl,
    status: a.status,
    inputs: a.inputs,
    observe: a.observe,
    outputs: a.outputs,
    outputFields: a.outputFields,
    drops: a.drops,
  }))
}

// ─── Build graph + layout ───────────────────────────────────────────────────

export function transformActionsToReactFlow(
  actions: DAGAction[],
  opts: TransformActionsToReactFlowOptions,
): { nodes: Node<DAGNodeData>[]; edges: Edge[] } {
  const unknownDeps = opts.unknownDeps ?? "filter"
  const nodeWidth = opts.nodeWidth ?? DAG_LAYOUT_DEFAULTS.nodeWidth
  const nodeHeight = opts.nodeHeight ?? DAG_LAYOUT_DEFAULTS.nodeHeight
  const nodesep = opts.nodesep ?? DAG_LAYOUT_DEFAULTS.nodesep
  const ranksep = opts.ranksep ?? DAG_LAYOUT_DEFAULTS.ranksep

  const nameSet = new Set(actions.map((a) => a.name))
  const placeholderNames = new Set<string>()

  if (unknownDeps === "materialize") {
    for (const a of actions) {
      for (const dep of a.deps) {
        if (!nameSet.has(dep)) placeholderNames.add(dep)
      }
    }
  }

  const nodes: Node<DAGNodeData>[] = []

  for (const depName of placeholderNames) {
    nodes.push({
      id: depName,
      type: "toolNode",
      data: dagActionToNodeData({
        name: depName,
        deps: [],
        kind: "unknown",
        intent: "Unknown dependency (no matching action)",
      }),
      position: { x: 0, y: 0 },
    })
  }

  for (const a of actions) {
    nodes.push({
      id: a.name,
      type: reactFlowNodeType(a.kind),
      data: dagActionToNodeData(a),
      position: { x: 0, y: 0 },
    })
  }

  const edges: Edge[] = []
  let edgeId = 0

  for (const a of actions) {
    for (const dep of a.deps) {
      if (unknownDeps === "filter" && !nameSet.has(dep)) {
        continue
      }
      if (unknownDeps === "materialize" && !nameSet.has(dep) && !placeholderNames.has(dep)) {
        continue
      }
      edges.push({
        id: `e${edgeId++}`,
        source: dep,
        target: a.name,
        type: "default",
        animated: false,
        style: { stroke: "hsl(var(--muted-foreground))", strokeWidth: 1.5, opacity: 0.7 },
      })
    }
  }

  return applyDagreLayout(nodes, edges, {
    direction: opts.direction,
    nodeWidth,
    nodeHeight,
    nodesep,
    ranksep,
  })
}

export function applyDagreLayout<T extends Record<string, unknown>>(
  nodes: Node<T>[],
  edges: Edge[],
  opts: {
    direction?: "LR" | "TB"
    nodeWidth?: number
    nodeHeight?: number
    nodesep?: number
    ranksep?: number
  } = {},
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

  try {
    dagre.layout(g)
  } catch {
    const fallback = nodes.map((node, i) => ({
      ...node,
      position: { x: (i % 4) * (nodeWidth + 40), y: Math.floor(i / 4) * (nodeHeight + 40) },
    }))
    return { nodes: fallback, edges }
  }

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

/** @deprecated Prefer `adaptDocsActionsToDAGActions` + `transformActionsToReactFlow` with explicit `direction`. */
export function transformWorkflowToReactFlow(actions: Record<string, Action>, workflowId: string) {
  const dagActions = adaptDocsActionsToDAGActions(actions, workflowId)
  return transformActionsToReactFlow(dagActions, {
    direction: "LR",
    unknownDeps: "filter",
    ...DAG_LAYOUT_DEFAULTS,
  })
}
