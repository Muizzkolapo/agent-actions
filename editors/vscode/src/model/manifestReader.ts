/**
 * Manifest and Agent Status Reader
 *
 * Reads runtime status from:
 * - agent_io/target/.manifest.json (execution plan and status)
 * - agent_io/.agent_status.json (live runtime status from PR #823)
 */

import * as vscode from 'vscode';
import { ManifestData, AgentStatusData } from './types';
import { logger } from '../utils/logger';

/**
 * Read and parse the workflow manifest file
 */
export async function readManifest(uri: vscode.Uri): Promise<ManifestData | null> {
    try {
        const contentBytes = await vscode.workspace.fs.readFile(uri);
        const content = Buffer.from(contentBytes).toString('utf8');
        return JSON.parse(content) as ManifestData;
    } catch (error) {
        // Debug logging for manifest parsing issues (file not found is expected)
        if (error instanceof Error && !error.message.includes('ENOENT')) {
            logger.debug('Failed to read manifest', { path: uri.fsPath, error });
        }
        return null;
    }
}

/**
 * Read and parse the agent status file (live runtime status)
 * This provides more up-to-date status than the manifest during execution
 */
export async function readAgentStatus(uri: vscode.Uri): Promise<AgentStatusData | null> {
    try {
        const contentBytes = await vscode.workspace.fs.readFile(uri);
        const content = Buffer.from(contentBytes).toString('utf8');
        return JSON.parse(content) as AgentStatusData;
    } catch (error) {
        // Debug logging for status parsing issues (file not found is expected)
        if (error instanceof Error && !error.message.includes('ENOENT')) {
            logger.debug('Failed to read agent status', { path: uri.fsPath, error });
        }
        return null;
    }
}
