import type {
  RawCatalogJson,
  RawRunsJson,
  RawWorkflow,
  RawAction,
  RawPrompt,
  RawSchema,
  RawToolFunction,
  RawInvocation,
  RawValidationEntry,
  RawExecution,
  RawWorkflowData,
} from "./catalog-client"
import type {
  Stats,
  Workflow,
  WorkflowStatus,
  Action,
  ActionMetrics,
  Run,
  RunStatus,
  Schema,
  Prompt,
  ToolFunction,
  Invocation,
  ValidationGroup,
  DataNode,
  WorkflowDataSummary,
} from "./mock-data"

// ─── Stats ───────────────────────────────────────────────────────────────────

export function transformStats(catalog: RawCatalogJson): Stats {
  return { ...catalog.stats }
}

// ─── Workflows ───────────────────────────────────────────────────────────────

function statusFromManifest(manifest: RawWorkflow["manifest"]): WorkflowStatus {
  if (!manifest?.status) return "paused"
  const s = manifest.status.toLowerCase()
  if (s === "completed" || s === "success") return "completed"
  if (s === "failed") return "failed"
  if (s === "running") return "running"
  return "paused"
}

export function transformWorkflows(catalog: RawCatalogJson): Workflow[] {
  return Object.values(catalog.workflows).map((wf) => {
    let llmCount = 0
    let toolCount = 0
    for (const a of Object.values(wf.actions)) {
      if (a.type === "llm") llmCount++
      else toolCount++
    }

    return {
      id: wf.id,
      name: wf.name,
      version: wf.version,
      description: wf.description,
      defaults: {
        model_vendor: (wf.defaults.model_vendor as string) ?? null,
        model_name: (wf.defaults.model_name as string) ?? null,
        json_mode: (wf.defaults.json_mode as boolean) ?? null,
        granularity: (wf.defaults.granularity as string) ?? "Record",
        run_mode: (wf.defaults.run_mode as string) ?? null,
        few_shot: (wf.defaults.few_shot as number) ?? null,
      },
      actionCount: wf.action_count,
      llmCount,
      toolCount,
      levels: wf.manifest?.levels ?? [],
      manifestStatus: statusFromManifest(wf.manifest),
    }
  })
}

// ─── Actions ─────────────────────────────────────────────────────────────────

function buildActionMetrics(raw?: RawAction["metrics"]): ActionMetrics {
  return {
    execution_time: raw?.execution_time ?? null,
    tokens: {
      prompt_tokens: raw?.tokens?.prompt_tokens,
      completion_tokens: raw?.tokens?.completion_tokens,
    },
    success_count: raw?.success_count ?? 0,
    failed_count: raw?.failed_count ?? 0,
  }
}

export function transformActions(catalog: RawCatalogJson): Record<string, Action> {
  const result: Record<string, Action> = {}

  // Track seen action names to detect collisions across workflows
  const seen = new Map<string, string>() // actionName → workflowId

  for (const [wfId, wf] of Object.entries(catalog.workflows)) {
    for (const [actionName, rawAction] of Object.entries(wf.actions)) {
      // Look up prompt preview from catalog prompts
      let promptPreview: string | null = null
      if (rawAction.prompt && catalog.prompts[rawAction.prompt]) {
        const content = catalog.prompts[rawAction.prompt].content
        promptPreview = content ? content.slice(0, 200) : null
      }
      if (!promptPreview && rawAction.type === "llm" && rawAction.intent) {
        promptPreview = rawAction.intent
      }

      const action: Action = {
        wf: wfId,
        type: rawAction.type,
        deps: rawAction.dependencies ?? [],
        schema: typeof rawAction.schema === "string" ? rawAction.schema : null,
        intent: rawAction.intent ?? "",
        guard: rawAction.guard ?? null,
        prompt: promptPreview,
        impl: rawAction.implementation,
        metrics: buildActionMetrics(rawAction.metrics),
        // Lineage fields
        inputs: rawAction.inputs ?? [],
        outputs: rawAction.outputs ?? [],
        outputFields: (rawAction.output_fields ?? []).map((f) => ({
          name: f.name,
          type: f.type,
          description: f.description,
        })),
        drops: rawAction.drops ?? [],
        observe: rawAction.observe ?? [],
        model: rawAction.model,
        provider: rawAction.provider,
      }

      // Handle name collision across workflows
      let key = actionName
      if (seen.has(actionName) && seen.get(actionName) !== wfId) {
        key = `${wfId}__${actionName}`
      }
      seen.set(actionName, wfId)
      result[key] = action
    }
  }

  return result
}

// ─── Runs ────────────────────────────────────────────────────────────────────

function normalizeRunStatus(raw: string): RunStatus {
  const s = raw.toUpperCase()
  if (s === "SUCCESS" || s === "COMPLETED") return "SUCCESS"
  if (s === "FAILED") return "FAILED"
  if (s === "RUNNING") return "running"
  return "PAUSED"
}

export function transformRuns(runs: RawRunsJson): Run[] {
  return runs.executions.map((exec: RawExecution) => {
    const actions: Run["actions"] = {}
    for (const [name, a] of Object.entries(exec.actions ?? {})) {
      actions[name] = {
        status: a.status,
        dur: a.duration_seconds ?? 0,
        type: a.type,
        model: a.model,
        impl: a.impl,
      }
    }

    return {
      id: exec.id,
      wf: exec.workflow_id || exec.workflow_name,
      status: normalizeRunStatus(exec.status),
      started: exec.started_at,
      duration: exec.duration_seconds,
      total: exec.total_actions,
      success: exec.successful_actions,
      failed: exec.failed_actions,
      tokens: exec.total_tokens,
      error: exec.error_message ?? undefined,
      actions,
    }
  })
}

// ─── Schemas ─────────────────────────────────────────────────────────────────

export function transformSchemas(catalog: RawCatalogJson): Schema[] {
  return Object.values(catalog.schemas).map((raw: RawSchema) => {
    if (Array.isArray(raw.fields) && raw.fields.length > 0 && typeof raw.fields[0] === "object") {
      // Structured fields with name/type
      const fieldObjs = raw.fields as { name: string; type: string }[]
      return {
        id: raw.id || raw.name,
        fields: fieldObjs.map((f) => f.name),
        types: fieldObjs.map((f) => f.type),
      }
    }
    // Fallback: field_count as numeric
    return {
      id: raw.id || raw.name,
      fields: raw.field_count ?? 0,
      types: [],
    }
  })
}

// ─── Prompts ─────────────────────────────────────────────────────────────────

function categorizeLength(charCount: number): string {
  if (charCount < 500) return "short"
  if (charCount < 2000) return "medium"
  return "long"
}

export function transformPrompts(catalog: RawCatalogJson): Prompt[] {
  return Object.entries(catalog.prompts).map(([key, raw]: [string, RawPrompt]) => {
    return {
      id: raw.id || key,
      name: raw.name || key,
      source: raw.source_file_name || raw.source_file || "",
      length: categorizeLength(raw.length ?? raw.content?.length ?? 0),
      usedBy: (raw.used_by ?? []).map((u) => u.action),
      preview: raw.content ? raw.content.slice(0, 200) : "",
      content: raw.content ?? "",
    }
  })
}

// ─── Tool Functions ──────────────────────────────────────────────────────────

export function transformToolFunctions(catalog: RawCatalogJson): ToolFunction[] {
  return Object.entries(catalog.tool_functions).map(([name, raw]: [string, RawToolFunction]) => {
    return {
      name: raw.name || name,
      sig: raw.signature || "",
      udf: raw.is_udf ?? false,
      found: raw.found !== false,
      file: raw.file_path || "",
    }
  })
}

// ─── Invocations ─────────────────────────────────────────────────────────────

export function transformInvocations(catalog: RawCatalogJson): Invocation[] {
  return (catalog.logs?.recent_invocations ?? []).map((raw: RawInvocation) => ({
    id: raw.invocation_id,
    ts: raw.timestamp,
    wf: raw.workflow_name ?? "",
    cmd: raw.command ?? null,
  }))
}

// ─── Validation Groups ───────────────────────────────────────────────────────

function groupValidationEntries(entries: RawValidationEntry[]): ValidationGroup[] {
  const groups = new Map<string, { count: number; sample: string }>()
  for (const entry of entries) {
    const key = entry.target ?? "unknown"
    const existing = groups.get(key)
    if (existing) {
      existing.count++
    } else {
      groups.set(key, { count: 1, sample: entry.message ?? "" })
    }
  }
  return Array.from(groups.entries()).map(([target, { count, sample }]) => ({
    target,
    count,
    sample,
  }))
}

export function transformValidationGroups(catalog: RawCatalogJson): {
  errors: ValidationGroup[]
  warnings: ValidationGroup[]
} {
  return {
    errors: groupValidationEntries(catalog.logs?.validation_errors ?? []),
    warnings: groupValidationEntries(catalog.logs?.validation_warnings ?? []),
  }
}

// ─── Workflow Data ───────────────────────────────────────────────────────────

export function transformWorkflowData(catalog: RawCatalogJson): WorkflowDataSummary[] {
  return Object.entries(catalog.workflow_data ?? {}).map(
    ([workflowName, raw]: [string, RawWorkflowData]) => {
      const nodes: DataNode[] = Object.entries(raw.nodes ?? {}).map(
        ([nodeName, nodeData]) => ({
          id: `${workflowName}.${nodeName}`,
          node: nodeName,
          workflow: workflowName,
          recordCount: nodeData.record_count ?? 0,
          files: nodeData.files ?? [],
          preview: nodeData.preview ?? [],
        }),
      )

      return {
        workflow: workflowName,
        dbSize: raw.db_size ?? "0 B",
        sourceCount: raw.source_count ?? 0,
        targetCount: raw.target_count ?? 0,
        nodes,
      }
    },
  )
}

// ─── All-in-one ──────────────────────────────────────────────────────────────

export interface CatalogData {
  stats: Stats
  workflows: Workflow[]
  actions: Record<string, Action>
  runs: Run[]
  schemas: Schema[]
  prompts: Prompt[]
  toolFunctions: ToolFunction[]
  invocations: Invocation[]
  validationErrorGroups: ValidationGroup[]
  validationWarningGroups: ValidationGroup[]
  workflowData: WorkflowDataSummary[]
  generatedAt: string
}

export function transformAll(catalog: RawCatalogJson, runs: RawRunsJson): CatalogData {
  const { errors, warnings } = transformValidationGroups(catalog)
  return {
    stats: transformStats(catalog),
    workflows: transformWorkflows(catalog),
    actions: transformActions(catalog),
    runs: transformRuns(runs),
    schemas: transformSchemas(catalog),
    prompts: transformPrompts(catalog),
    toolFunctions: transformToolFunctions(catalog),
    invocations: transformInvocations(catalog),
    validationErrorGroups: errors,
    validationWarningGroups: warnings,
    workflowData: transformWorkflowData(catalog),
    generatedAt: catalog.metadata?.generated_at ?? "",
  }
}
