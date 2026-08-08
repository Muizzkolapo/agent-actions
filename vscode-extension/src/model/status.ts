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
    | 'completed'
    | 'failed'
    | 'skipped'
    | 'interrupted';

const KNOWN_STATUSES: readonly string[] = [
    'pending',
    'running',
    'completed',
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
export function toActionStatus(status: string | undefined): ActionStatus {
    const normalized = (status ?? '').toLowerCase();
    if (KNOWN_STATUSES.includes(normalized)) {
        return normalized as ActionStatus;
    }
    if (normalized === 'success') {
        return 'completed';
    }
    if (normalized === 'error') {
        return 'failed';
    }
    return 'pending';
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
    const live = agentStatusFor(agentStatus, actionName);
    if (live !== undefined) {
        return toActionStatus(live);
    }

    const fromManifest = manifest?.actions?.[actionName]?.status;
    if (fromManifest) {
        return toActionStatus(fromManifest);
    }

    return 'pending';
}
