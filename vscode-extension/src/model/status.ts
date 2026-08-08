/**
 * Status resolution for workflow actions.
 *
 * Deliberately free of `vscode` imports: this is the logic that decides what
 * the sidebar claims about a run, and it must be testable without an editor
 * host. Anything needing the VS Code API belongs in the providers.
 */

/**
 * Action execution status derived from the manifest and agent_status.json.
 *
 * Mirrors `ActionStatus` in agent_actions/workflow/managers/state.py. The two
 * are coupled through the JSON files on disk, so a new member on either side
 * has to be added here as well.
 */
export type ActionStatus =
    | 'pending'
    | 'running'
    | 'batch_submitted'
    | 'checking_batch'
    | 'completed'
    | 'completed_with_failures'
    | 'failed'
    | 'skipped'
    | 'interrupted';

/**
 * Every member of ActionStatus, for exhaustive iteration.
 *
 * Kept in sync with agent_actions/workflow/managers/state.py by
 * status.test.ts, which fails if the framework grows a member this omits.
 */
export const ACTION_STATUSES: readonly ActionStatus[] = [
    'pending',
    'running',
    'batch_submitted',
    'checking_batch',
    'completed',
    'completed_with_failures',
    'failed',
    'skipped',
    'interrupted',
];

/** Manifest action entry from .manifest.json */
export interface ManifestActionInfo {
    index?: number;
    level?: number;
    status?: string;
    output_dir?: string;
    dependencies?: string[];
    record_count?: number | null;
}

/** Workflow manifest written once per run */
export interface ManifestData {
    workflow_name?: string;
    execution_order?: string[];
    levels?: string[][];
    actions?: Record<string, ManifestActionInfo>;
}

/** Runtime status from agent_io/.agent_status.json */
export interface AgentStatusData {
    [actionName: string]: string | { status: string; [key: string]: unknown };
}

/**
 * Convert a raw on-disk status string to an ActionStatus.
 *
 * Unrecognised values fall back to 'pending' — which is a lie about a run that
 * did start, so a status the framework can emit must be listed above.
 */
export function parseActionStatus(status: string | undefined): ActionStatus | undefined {
    const normalized = (status ?? '').toLowerCase();
    if ((ACTION_STATUSES as readonly string[]).includes(normalized)) {
        return normalized as ActionStatus;
    }
    if (normalized === 'success') {
        return 'completed';
    }
    if (normalized === 'error') {
        return 'failed';
    }
    return undefined;
}

export function toActionStatus(status: string | undefined): ActionStatus {
    return parseActionStatus(status) ?? 'pending';
}

/** Read one action's status out of the agent_status.json shape. */
function agentStatusFor(
    agentStatus: AgentStatusData | null,
    actionName: string
): string | undefined {
    const entry = agentStatus?.[actionName];
    if (typeof entry === 'string') {
        return entry;
    }
    if (typeof entry === 'object' && entry !== null) {
        const value = (entry as Record<string, unknown>).status;
        if (typeof value === 'string') {
            return value;
        }
    }
    return undefined;
}

/**
 * Resolve an action's status from the two runtime files.
 *
 * agent_status.json wins today because it is written per action during
 * execution, where the manifest carries the run-level view.
 */
export function resolveActionStatus(
    manifest: ManifestData | null,
    agentStatus: AgentStatusData | null,
    actionName: string
): ActionStatus {
    // Only a status we understand may pre-empt the manifest. An unrecognised
    // string is no more informative than a missing one, and treating it as
    // 'pending' would discard a manifest entry that does say something.
    const live = parseActionStatus(agentStatusFor(agentStatus, actionName));
    if (live !== undefined) {
        return live;
    }

    const fromManifest = manifest?.actions?.[actionName]?.status;
    if (fromManifest) {
        return toActionStatus(fromManifest);
    }

    return 'pending';
}

/**
 * The status a workflow should show given its actions.
 *
 * Ordered by what a reader needs to act on first: a live run outranks a
 * failure, which outranks an interruption, so the top of the tree answers
 * "is anything happening, and did anything go wrong" without expanding.
 * An empty workflow reads as pending, not completed — nothing ran.
 */
export function rollupStatus(statuses: readonly ActionStatus[]): ActionStatus {
    if (statuses.length === 0) {
        return 'pending';
    }
    for (const rank of ['running', 'failed', 'interrupted'] as const) {
        if (statuses.includes(rank)) {
            return rank;
        }
    }
    if (statuses.every((s) => s === 'completed' || s === 'skipped')) {
        return 'completed';
    }
    return 'pending';
}

/**
 * Sort key placing workflows that need attention at the top of the tree.
 *
 * Lower sorts first. Ties are broken by name at the call site so ordering is
 * stable between refreshes.
 */
export function workflowSortRank(status: ActionStatus): number {
    switch (status) {
        case 'running':
            return 0;
        case 'failed':
            return 1;
        case 'interrupted':
            return 2;
        case 'pending':
            return 3;
        default:
            return 4;
    }
}

/** Status counts for workflow progress display. */
export interface StatusSummary {
    total: number;
    completed: number;
    running: number;
    failed: number;
    pending: number;
    skipped: number;
    interrupted: number;
}

/**
 * The one-line summary shown on a collapsed workflow row.
 *
 * Reports at most one detail, the most actionable one. Skipped is included so
 * a workflow that finished with completed < total does not look unexplained.
 */
export function formatWorkflowSummary(
    status: ActionStatus,
    summary: StatusSummary,
    liveActionName?: string
): string {
    const parts = [`${summary.completed}/${summary.total}`];

    if (liveActionName) {
        parts.push(liveActionName);
    } else if (summary.failed > 0) {
        parts.push(`${summary.failed} failed`);
    } else if (summary.interrupted > 0) {
        parts.push(`${summary.interrupted} interrupted`);
    } else if (summary.skipped > 0) {
        parts.push(`${summary.skipped} skipped`);
    }

    return parts.join(' \u00B7 ');
}
