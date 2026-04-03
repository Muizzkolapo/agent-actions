// Fetch catalog.json and runs.json from the artefact directory.
// In production these are served by `agac docs serve` under /artefact/*.

export interface RawCatalogJson {
  metadata: {
    generated_at: string
    total_workflows: number
    generator_version?: string
    project_name?: string | null
  }
  workflows: Record<string, RawWorkflow>
  actions: Record<string, RawAction & { workflow_id: string }>
  prompts: Record<string, RawPrompt>
  schemas: Record<string, RawSchema>
  tool_functions: Record<string, RawToolFunction>
  runs: Record<string, unknown>
  workflow_data: Record<string, RawWorkflowData>
  logs: {
    events_path?: string
    recent_invocations: unknown[]
    validation_errors: RawValidationEntry[]
    validation_warnings: RawValidationEntry[]
    runtime_warnings?: RawValidationEntry[]
    runtime_errors?: RawValidationEntry[]
  }
  stats: {
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
  }
}

export interface RawWorkflow {
  id: string
  name: string
  description: string
  path: string
  version: string
  defaults: Record<string, unknown>
  actions: Record<string, RawAction>
  action_count: number
  latest_run: unknown | null
  manifest: {
    status?: string
    levels?: string[][]
    [key: string]: unknown
  } | null
  readme?: string | null
}

export interface RawAction {
  type: "llm" | "tool"
  name: string
  intent?: string
  dependencies: string[]
  implementation?: string
  schema?: string | Record<string, unknown>
  prompt?: string
  guard?: {
    condition: string
    on_false: string
  } | null
  metrics?: {
    execution_time?: number | null
    tokens?: { prompt_tokens?: number; completion_tokens?: number }
    success_count?: number
    failed_count?: number
    filtered_count?: number
    skipped_count?: number
    exhausted_count?: number
    latency_ms?: number
    provider?: string | null
    model?: string | null
    cache_miss_count?: number
  }
  tool_function?: RawToolFunction
  // Lineage fields
  inputs?: string[]
  outputs?: string[]
  output_fields?: { name: string; type: unknown; description?: string }[]
  drops?: string[]
  observe?: string[]
  model?: string
  provider?: string
  granularity?: string | null
}

export interface RawPrompt {
  id: string
  name: string
  content: string
  source_file: string
  source_file_name: string
  line_start: number
  line_end: number
  length: number
  used_by: { workflow: string; action: string }[]
}

export interface RawSchema {
  id: string
  name: string
  type?: string
  fields: { name: string; type: string; description?: string }[]
  field_count?: number
  source_file?: string
  used_by?: { workflow: string; action: string }[]
}

export interface RawToolFunction {
  name?: string
  file_path: string
  signature: string
  line_start?: number
  line_end?: number
  docstring?: string
  is_udf: boolean
  found?: boolean
  source_code?: string
}

export interface RawValidationEntry {
  target: string
  message?: string
  error?: string
  warning?: string
  field?: string
  timestamp?: string
  [key: string]: unknown
}

// --- workflow_data ---

export interface RawWorkflowDataNode {
  record_count: number
  files: string[]
  preview: Record<string, unknown>[]
}

export interface RawWorkflowData {
  db_path: string
  db_size: string
  source_count: number
  target_count: number
  nodes: Record<string, RawWorkflowDataNode>
}

// --- runs.json ---

export interface RawRunsJson {
  metadata: {
    generated_at: string
    total_runs: number
  }
  executions: RawExecution[]
  workflow_metrics?: Record<string, unknown>
}

export interface RawExecution {
  id: string
  workflow_id: string
  workflow_name: string
  status: string
  started_at: string
  ended_at?: string | null
  duration_seconds: number
  total_actions: number
  successful_actions: number
  failed_actions: number
  skipped_actions?: number
  total_tokens: number
  error_message?: string | null
  actions: Record<string, {
    status: string
    started_at?: string
    ended_at?: string | null
    duration_seconds: number
    type: "llm" | "tool"
    vendor?: string
    model?: string
    impl?: string
    tokens?: { total_tokens?: number; input_tokens?: number; output_tokens?: number }
    error?: string
  }>
}

// --- Fetch ---

export interface FetchResult {
  catalog: RawCatalogJson
  runs: RawRunsJson
}

export async function fetchCatalogData(): Promise<FetchResult> {
  const bust = `?v=${Date.now()}`

  const [catalogRes, runsRes] = await Promise.all([
    fetch(`/artefact/catalog.json${bust}`),
    fetch(`/artefact/runs.json${bust}`),
  ])

  if (catalogRes.status === 404) {
    throw new Error("No catalog found. Run `agac docs generate` first.")
  }
  if (!catalogRes.ok) {
    throw new Error(`Failed to load catalog.json (HTTP ${catalogRes.status})`)
  }

  const catalog: RawCatalogJson = await catalogRes.json()

  // runs.json is optional — empty runs is valid
  let runs: RawRunsJson = { metadata: { generated_at: "", total_runs: 0 }, executions: [] }
  if (runsRes.ok) {
    runs = await runsRes.json()
  }

  return { catalog, runs }
}
