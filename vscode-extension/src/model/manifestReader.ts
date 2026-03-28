/**
 * Manifest and Agent Status Reader
 *
 * Reads runtime status from:
 * - agent_io/target/.manifest.json (execution plan and status)
 * - agent_io/.agent_status.json (live runtime status)
 */

import * as vscode from 'vscode';
import { ManifestData, AgentStatusData } from './types';

export async function readManifest(uri: vscode.Uri): Promise<ManifestData | null> {
    try {
        const contentBytes = await vscode.workspace.fs.readFile(uri);
        const content = Buffer.from(contentBytes).toString('utf8');
        return JSON.parse(content) as ManifestData;
    } catch {
        return null;
    }
}

export async function readAgentStatus(uri: vscode.Uri): Promise<AgentStatusData | null> {
    try {
        const contentBytes = await vscode.workspace.fs.readFile(uri);
        const content = Buffer.from(contentBytes).toString('utf8');
        return JSON.parse(content) as AgentStatusData;
    } catch {
        return null;
    }
}
