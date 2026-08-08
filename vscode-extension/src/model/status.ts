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
    /** Run-level status: 'running' until the workflow finishes. */
    status?: string;
    /** Process that owns the run, and the host it runs on. */
    pid?: number;
    hostname?: string;
}

/**
 * Whether the process that started the run still exists.
 *
 * 'unknown' is the safe answer and the common one: a manifest written by an
 * older framework has no pid, and a pid from another machine says nothing.
 * Callers must not downgrade anything on 'unknown'.
 */
export type RunLiveness = 'live' | 'dead' | 'unknown';

export function runLiveness(
    manifest: ManifestData | null,
    localHostname: string,
    isProcessAlive: (pid: number) => boolean
): RunLiveness {
    if (!manifest) {
        return 'unknown';
    }
    if (manifest.status && manifest.status !== 'running') {
        // The run recorded its own ending, so nothing in it is still going.
        return 'dead';
    }
    if (typeof manifest.pid !== 'number') {
        return 'unknown';
    }
    if (manifest.hostname && manifest.hostname !== localHostname) {
        return 'unknown';
    }
    return isProcessAlive(manifest.pid) ? 'live' : 'dead';
}

/** Statuses that claim work is happening right now. */
const IN_FLIGHT: readonly ActionStatus[] = ['running', 'checking_batch'];

/**
 * Correct an in-flight status when the run that wrote it is gone.
 *
 * A process killed outright — SIGKILL, OOM, power loss — never gets to record
 * a terminal status, so the file keeps claiming 'running' indefinitely. The
 * action did not fail; we simply know it never finished.
 */
export function reconcileWithLiveness(
    status: ActionStatus,
    liveness: RunLiveness
): ActionStatus {
    if (liveness === 'dead' && IN_FLIGHT.includes(status)) {
        return 'interrupted';
    }
    return status;
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
const ROLLUP_PRECEDENCE: readonly ActionStatus[] = [
    'running',
    'checking_batch',
    'batch_submitted',
    'failed',
    'interrupted',
    'completed_with_failures',
];

/** Statuses that mean the action reached an acceptable end. */
const SETTLED: readonly ActionStatus[] = ['completed', 'skipped'];

export function rollupStatus(statuses: readonly ActionStatus[]): ActionStatus {
    if (statuses.length === 0) {
        return 'pending';
    }
    for (const rank of ROLLUP_PRECEDENCE) {
        if (statuses.includes(rank)) {
            return rank;
        }
    }
    if (statuses.every((s) => SETTLED.includes(s))) {
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
        case 'checking_batch':
            return 0;
        case 'batch_submitted':
            return 1;
        case 'failed':
            return 2;
        case 'interrupted':
            return 3;
        case 'completed_with_failures':
            return 4;
        case 'pending':
            return 5;
        case 'completed':
        case 'skipped':
            return 6;
    }
    // No default: adding a status to the union must fail the build here rather
    // than silently sorting it last. That omission is what let three real
    // statuses render as never-started.
    return assertNever(status);
}

function assertNever(value: never): never {
    throw new Error(`Unhandled ActionStatus: ${String(value)}`);
}

/** Status counts for workflow progress display. */
export interface StatusSummary {
    total: number;
    pending: number;
    running: number;
    batch_submitted: number;
    checking_batch: number;
    completed: number;
    completed_with_failures: number;
    failed: number;
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

    if (summary.running > 1) {
        // A parallel level runs several at once; naming one implies it is alone.
        parts.push(`${summary.running} running`);
    } else if (liveActionName) {
        parts.push(liveActionName);
    } else if (status === 'batch_submitted' || status === 'checking_batch') {
        parts.push('awaiting batch');
    } else if (summary.failed > 0) {
        parts.push(`${summary.failed} failed`);
    } else if (summary.interrupted > 0) {
        parts.push(`${summary.interrupted} interrupted`);
    } else if (summary.skipped > 0) {
        parts.push(`${summary.skipped} skipped`);
    }

    return parts.join(' \u00B7 ');
}
