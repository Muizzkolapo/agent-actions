// ─── Types ──────────────────────────────────────────────────────────────────

export type WorkflowStatus = "running" | "completed" | "failed" | "paused"
export type ActionType = "llm" | "tool"
export type RunStatus = "PAUSED" | "FAILED" | "SUCCESS" | "running"

export interface Stats {
  total_workflows: number
  total_actions: number
  llm_actions: number
  tool_actions: number
  total_prompts: number
  total_schemas: number
  total_tool_functions: number
  total_runs: number
  validation_errors: number
  validation_warnings: number
  runtime_warnings?: number
  runtime_errors?: number
}

export interface WorkflowDefaults {
  model_vendor: string | null
  model_name: string | null
  json_mode: boolean | null
  granularity: string
  run_mode: string | null
}

export interface Workflow {
  id: string
  name: string
  version: string
  description: string
  path: string
  defaults: WorkflowDefaults
  actionCount: number
  llmCount: number
  toolCount: number
  levels: string[][]
  manifestStatus: WorkflowStatus
  readme: string | null
}

export interface ActionMetrics {
  execution_time: number | null
  tokens: { prompt_tokens?: number; completion_tokens?: number }
  success_count: number
  failed_count: number
}

export interface OutputField {
  name: string
  type: unknown
  description?: string
}

export interface Action {
  wf: string
  type: ActionType
  deps: string[]
  schema: string | null
  intent: string
  guard: { condition: string; on_false: string } | null
  prompt: string | null
  promptName: string | null
  impl?: string
  toolFunction?: { signature: string; docstring: string; file: string; sourceCode?: string }
  metrics: ActionMetrics
  // Lineage fields
  inputs: string[]
  outputs: string[]
  outputFields: OutputField[]
  drops: string[]
  observe: string[]
  model?: string
  provider?: string
}

export interface Run {
  id: string
  wf: string
  status: RunStatus
  started: string
  ended?: string
  duration: number
  total: number
  success: number
  failed: number
  skipped: number
  tokens: number
  error?: string | null
  actions: Record<string, { status: string; dur: number; type: string; model?: string; vendor?: string; impl?: string; started?: string; ended?: string }>
}

export interface Schema {
  id: string
  fields: string[] | number
  types: string[]
  source: string
  usedBy: { workflow: string; action: string }[]
}

export interface Prompt {
  id: string
  name: string
  source: string
  length: string
  usedBy: string[]
  preview: string
  content: string
}

export interface ToolFunction {
  name: string
  sig: string
  udf: boolean
  found: boolean
  file: string
  sourceCode?: string
}

export interface ValidationMessage {
  text: string
  count: number
  firstSeen: string
  lastSeen: string
}

export interface ValidationGroup {
  target: string
  count: number
  sample: string
  distinctCount: number
  timestamps: string[]
  messages: ValidationMessage[]
}

// Data Explorer types (populated from catalog.json workflow_data)
export interface DataNode {
  id: string             // "workflow.action_name"
  node: string           // "extract_raw_qa_3"
  workflow: string        // "my_workflow"
  recordCount: number
  files: string[]
  preview: Record<string, unknown>[]
}

export interface WorkflowDataSummary {
  workflow: string
  dbSize: string
  sourceCount: number
  targetCount: number
  nodes: DataNode[]
}

// Keep for base log compatibility
export interface LogEntry {
  id: string
  timestamp: string
  level: "info" | "warn" | "error" | "debug"
  category: "invocation" | "validation" | "event" | "system"
  message: string
  workflowId?: string
  runId?: string
}

// ─── Data (fetched from catalog.json workflow_data — no mock data) ───────
