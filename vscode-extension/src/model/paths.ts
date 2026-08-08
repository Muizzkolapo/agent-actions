/**
 * Where the framework writes the runtime files the sidebar reads.
 *
 * Free of `vscode` imports so the location rules stay testable — getting one
 * of these wrong makes the extension silently fall back to guessing, which is
 * hard to notice and was the state of things before this module existed.
 */

import * as path from 'node:path';

export const MANIFEST_FILENAME = '.manifest.json';
export const AGENT_STATUS_FILENAME = '.agent_status.json';

/**
 * Manifest locations in preference order.
 *
 * The framework writes to `agent_io/logs/`. `agent_io/target/` is the
 * pre-migration location, retained for projects whose last run predates that
 * move — the same fallback `scan_runs` applies in
 * agent_actions/tooling/docs/scanner/data_scanners.py.
 */
export function manifestCandidatePaths(agentIoPath: string): string[] {
    return [
        path.join(agentIoPath, 'logs', MANIFEST_FILENAME),
        path.join(agentIoPath, 'target', MANIFEST_FILENAME),
    ];
}

/** The live per-action status file, written directly under agent_io/. */
export function agentStatusPath(agentIoPath: string): string {
    return path.join(agentIoPath, AGENT_STATUS_FILENAME);
}

/** Watch both manifest locations so the fallback still triggers a refresh. */
export const MANIFEST_GLOB = '**/agent_io/{logs,target}/.manifest.json';
export const AGENT_STATUS_GLOB = '**/agent_io/.agent_status.json';
