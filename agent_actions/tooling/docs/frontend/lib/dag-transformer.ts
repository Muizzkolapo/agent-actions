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

export interface FieldMapping {
  displayField: string
  sourceAction: string | null
  sourceField: string
}

export interface ExtractedFields {
  inputFields: string[]
  outputFields: string[]
  droppedFields: string[]
  inputFieldMappings: FieldMapping[]
}

export function extractActionFields(action: Action): ExtractedFields {
  const inputFieldSet = new Set<string>()
  const inputFieldMappings: FieldMapping[] = []

  // Inputs from catalog (e.g. ["source.page_content", "fact_extractor.candidate_facts_list"])
  for (const field of action.inputs) {
    inputFieldSet.add(field)
    const parts = field.split(".")
    if (parts.length >= 2) {
      inputFieldMappings.push({
        displayField: field,
        sourceAction: parts[0],
        sourceField: parts.slice(1).join("."),
      })
    } else {
      inputFieldMappings.push({
        displayField: field,
        sourceAction: null,
        sourceField: field,
      })
    }
  }

  // Observe fields (may add more inputs)
  for (const field of action.observe) {
    if (!inputFieldSet.has(field)) {
      inputFieldSet.add(field)
      const parts = field.split(".")
      inputFieldMappings.push({
        displayField: field,
        sourceAction: parts.length >= 2 ? parts[0] : null,
        sourceField: parts.length >= 2 ? parts.slice(1).join(".") : field,
      })
    }
  }

  const inputFields = Array.from(inputFieldSet)

  // Output fields from outputFields or outputs
  let outputFields: string[] = []
  if (action.outputFields.length > 0) {
    outputFields = action.outputFields.map((f) => f.name)
  } else if (action.outputs.length > 0) {
    outputFields = [...action.outputs]
  }

  const droppedFields = [...action.drops]

  return { inputFields, outputFields, droppedFields, inputFieldMappings }
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
  fieldsExpanded: boolean
  onExpandFields?: (label: string) => void
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
        fieldsExpanded: true,
      },
      position: { x: 0, y: 0 },
    })

    for (const dep of action.deps) {
      edges.push({
        id: `e${edgeId++}`,
        source: dep,
        target: name,
        type: "smoothstep",
        animated: true,
        style: { stroke: "hsl(var(--primary))", strokeWidth: 2 },
      })
    }
  }

  return { nodes, edges }
}

// ─── Lineage view (field-level nodes + field-to-field edges) ────────────────

export interface LineageNodeData {
  label: string
  type: "llm" | "tool"
  inputFields: string[]
  outputFields: string[]
  droppedFields: string[]
  [key: string]: unknown
}

function buildFieldToFieldEdges(
  actionEntries: [string, Action][],
): Edge[] {
  const edges: Edge[] = []
  let edgeId = 0

  // Build map of outputs per action
  const actionOutputs = new Map<string, Set<string>>()
  const actionFieldMappings = new Map<string, FieldMapping[]>()

  for (const [name, action] of actionEntries) {
    const { outputFields, inputFieldMappings } = extractActionFields(action)
    actionOutputs.set(name, new Set(outputFields))
    actionFieldMappings.set(name, inputFieldMappings)
  }

  for (const [actionName, action] of actionEntries) {
    const mappings = actionFieldMappings.get(actionName) || []

    for (const mapping of mappings) {
      if (mapping.sourceAction) {
        // Explicit mapping (e.g. "fact_extractor.candidate_facts_list")
        const sourceOutputs = actionOutputs.get(mapping.sourceAction)
        if (sourceOutputs?.has(mapping.sourceField)) {
          edges.push({
            id: `field-e${edgeId++}`,
            source: mapping.sourceAction,
            sourceHandle: `output-${mapping.sourceField}`,
            target: actionName,
            targetHandle: `input-${mapping.displayField}`,
            type: "smoothstep",
            animated: true,
            style: { stroke: "hsl(var(--success))", strokeWidth: 2 },
          })
        }
      } else {
        // Implicit mapping — match with deps
        for (const depName of action.deps) {
          const depOutputs = actionOutputs.get(depName)
          if (!depOutputs) continue

          const inputField = mapping.displayField
          if (depOutputs.has(inputField)) {
            edges.push({
              id: `field-e${edgeId++}`,
              source: depName,
              sourceHandle: `output-${inputField}`,
              target: actionName,
              targetHandle: `input-${inputField}`,
              type: "smoothstep",
              animated: true,
              style: { stroke: "hsl(var(--success))", strokeWidth: 2 },
            })
          } else {
            // Nested match: "source.page_content" → "page_content"
            const fieldParts = inputField.split(".")
            const fieldName = fieldParts[fieldParts.length - 1]
            if (depOutputs.has(fieldName)) {
              edges.push({
                id: `field-e${edgeId++}`,
                source: depName,
                sourceHandle: `output-${fieldName}`,
                target: actionName,
                targetHandle: `input-${inputField}`,
                type: "smoothstep",
                animated: true,
                style: {
                  stroke: "hsl(var(--chart-5))",
                  strokeWidth: 2,
                  strokeDasharray: "6,3",
                },
              })
            }
          }
        }
      }
    }
  }

  return edges
}

export function buildLineageNodesAndEdges(actions: Record<string, Action>, workflowId: string) {
  const entries: [string, Action][] = Object.entries(actions).filter(
    ([, a]) => a.wf === workflowId,
  )

  const nodes: Node<LineageNodeData>[] = entries.map(([name, action]) => {
    const { inputFields, outputFields, droppedFields } = extractActionFields(action)
    return {
      id: name,
      type: "fieldActionNode",
      data: {
        label: name,
        type: action.type,
        inputFields,
        outputFields,
        droppedFields,
      },
      position: { x: 0, y: 0 },
    }
  })

  const edges = buildFieldToFieldEdges(entries)

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
  return applyDagreLayout(nodes, edges, { nodeWidth: 320, nodeHeight: 140, nodesep: 120, ranksep: 200 })
}

export function transformWorkflowToFieldLineage(actions: Record<string, Action>, workflowId: string) {
  const { nodes, edges } = buildLineageNodesAndEdges(actions, workflowId)
  return applyDagreLayout(nodes, edges, { nodeWidth: 320, nodeHeight: 90, nodesep: 180, ranksep: 350 })
}
