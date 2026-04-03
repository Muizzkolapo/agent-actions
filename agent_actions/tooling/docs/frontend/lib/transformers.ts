import type {
  RawCatalogJson,
  RawRunsJson,
  RawWorkflow,
  RawAction,
  RawPrompt,
  RawSchema,
  RawToolFunction,
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
      path: wf.path ?? "",
      defaults: {
        model_vendor: (wf.defaults.model_vendor as string) ?? null,
        model_name: (wf.defaults.model_name as string) ?? null,
        json_mode: (wf.defaults.json_mode as boolean) ?? null,
        granularity: (wf.defaults.granularity as string) ?? "Record",
        run_mode: (wf.defaults.run_mode as string) ?? null,
      },
      actionCount: wf.action_count,
      llmCount,
      toolCount,
      levels: wf.manifest?.levels ?? [],
      manifestStatus: statusFromManifest(wf.manifest),
      readme: wf.readme ?? null,
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
      // Resolve prompt: named reference → catalog lookup, otherwise inline content.
      // Intentionally no intent fallback — intent is shown separately in the Overview.
      let promptContent: string | null = null
      let promptName: string | null = null
      if (rawAction.prompt) {
        if (catalog.prompts[rawAction.prompt]) {
          promptName = rawAction.prompt
          promptContent = catalog.prompts[rawAction.prompt].content ?? null
        } else {
          // Inline prompt text (not a catalog key)
          promptContent = rawAction.prompt
        }
      }

      const action: Action = {
        wf: wfId,
        type: rawAction.type,
        deps: rawAction.dependencies ?? [],
        schema: typeof rawAction.schema === "string" ? rawAction.schema : null,
        intent: rawAction.intent ?? "",
        guard: rawAction.guard ?? null,
        prompt: promptContent,
        promptName,
        impl: rawAction.implementation,
        toolFunction: rawAction.tool_function && rawAction.tool_function.found !== false ? {
          signature: rawAction.tool_function.signature || "",
          docstring: rawAction.tool_function.docstring || "",
          file: rawAction.tool_function.file_path || "",
          sourceCode: rawAction.tool_function.source_code,
        } : undefined,
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
        vendor: a.vendor,
        impl: a.impl,
        started: a.started_at,
        ended: a.ended_at ?? undefined,
      }
    }

    return {
      id: exec.id,
      wf: exec.workflow_id || exec.workflow_name,
      status: normalizeRunStatus(exec.status),
      started: exec.started_at,
      ended: exec.ended_at ?? undefined,
      duration: exec.duration_seconds,
      total: exec.total_actions,
      success: exec.successful_actions,
      failed: exec.failed_actions,
      skipped: exec.skipped_actions ?? 0,
      tokens: exec.total_tokens,
      error: exec.error_message ?? undefined,
      actions,
    }
  })
}

// ─── Schemas ─────────────────────────────────────────────────────────────────

export function transformSchemas(catalog: RawCatalogJson): Schema[] {
  // Build reverse index: schema name → [{workflow, action}] from actions
  const reverseUsage: Record<string, { workflow: string; action: string }[]> = {}
  for (const a of Object.values(catalog.actions)) {
    let schemaName: string | undefined
    if (typeof a.schema === "string") {
      schemaName = a.schema
    } else if (a.schema && typeof a.schema === "object" && "name" in a.schema) {
      schemaName = a.schema.name as string
    }
    if (schemaName) {
      ;(reverseUsage[schemaName] ??= []).push({ workflow: a.workflow_id ?? "", action: a.name ?? "" })
    }
  }

  return Object.values(catalog.schemas).map((raw: RawSchema) => {
    const schemaId = raw.id || raw.name
    // Merge explicit used_by with reverse-indexed usage (deduplicated)
    const explicit = raw.used_by ?? []
    const reverse = reverseUsage[schemaId] ?? []
    const seen = new Set(explicit.map((r) => `${r.workflow}::${r.action}`))
    const merged = [...explicit]
    for (const r of reverse) {
      const key = `${r.workflow}::${r.action}`
      if (!seen.has(key)) { merged.push(r); seen.add(key) }
    }

    if (Array.isArray(raw.fields) && raw.fields.length > 0 && typeof raw.fields[0] === "object") {
      const fieldObjs = raw.fields as { name: string; type: string }[]
      return {
        id: schemaId,
        fields: fieldObjs.map((f) => f.name),
        types: fieldObjs.map((f) => f.type),
        source: raw.source_file ?? "",
        usedBy: merged,
      }
    }
    return {
      id: schemaId,
      fields: raw.field_count ?? 0,
      types: [],
      source: raw.source_file ?? "",
      usedBy: merged,
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
      sourceCode: raw.source_code ? raw.source_code : undefined,
    }
  })
}

// ─── Validation Groups ───────────────────────────────────────────────────────

function extractMessage(entry: RawValidationEntry): string {
  return entry.message || entry.error || entry.warning || ""
}

function groupValidationEntries(entries: RawValidationEntry[]): ValidationGroup[] {
  const groups = new Map<
    string,
    { count: number; sample: string; messageMap: Map<string, { count: number; timestamps: string[] }>; timestamps: string[] }
  >()
  for (const entry of entries) {
    const key = entry.target ?? "unknown"
    const msg = extractMessage(entry)
    const existing = groups.get(key)
    if (existing) {
      existing.count++
      if (msg) {
        const msgEntry = existing.messageMap.get(msg)
        if (msgEntry) {
          msgEntry.count++
          if (entry.timestamp) msgEntry.timestamps.push(entry.timestamp)
        } else {
          existing.messageMap.set(msg, { count: 1, timestamps: entry.timestamp ? [entry.timestamp] : [] })
        }
      }
      if (entry.timestamp) existing.timestamps.push(entry.timestamp)
    } else {
      const messageMap = new Map<string, { count: number; timestamps: string[] }>()
      if (msg) {
        messageMap.set(msg, { count: 1, timestamps: entry.timestamp ? [entry.timestamp] : [] })
      }
      const timestamps: string[] = []
      if (entry.timestamp) timestamps.push(entry.timestamp)
      groups.set(key, { count: 1, sample: msg, messageMap, timestamps })
    }
  }
  return Array.from(groups.entries())
    .map(([target, { count, sample, messageMap, timestamps }]) => {
      const messages = Array.from(messageMap.entries())
        .filter(([text]) => text !== "")
        .map(([text, m]) => {
          const sorted = [...m.timestamps].sort()
          return {
            text,
            count: m.count,
            firstSeen: sorted[0] ?? "",
            lastSeen: sorted[sorted.length - 1] ?? "",
          }
        })
        .sort((a, b) => b.count - a.count)

      return {
        target,
        count,
        sample,
        distinctCount: messageMap.size,
        timestamps: timestamps.sort(),
        messages,
      }
    })
    .sort((a, b) => b.count - a.count)
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
  validationErrorGroups: ValidationGroup[]
  validationWarningGroups: ValidationGroup[]
  runtimeErrorGroups: ValidationGroup[]
  runtimeWarningGroups: ValidationGroup[]
  workflowData: WorkflowDataSummary[]
  generatedAt: string
  projectName: string | null
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
    validationErrorGroups: errors,
    validationWarningGroups: warnings,
    runtimeErrorGroups: groupValidationEntries(catalog.logs?.runtime_errors ?? []),
    runtimeWarningGroups: groupValidationEntries(catalog.logs?.runtime_warnings ?? []),
    workflowData: transformWorkflowData(catalog),
    generatedAt: catalog.metadata?.generated_at ?? "",
    projectName: catalog.metadata?.project_name ?? null,
  }
}
