/**
 * YAML Workflow Config Parser
 *
 * Reads an agent_config file and parses the text the language server renders from it,
 * with the same Jinja step as agac. With no server running, it parses the raw text.
 */

import * as vscode from 'vscode';
import { ParsedWorkflowConfig } from './types';
import { parseLoadedWorkflow, RenderedWorkflowResult } from './workflowText';

export type RenderViaLsp = (uri: string) => Promise<RenderedWorkflowResult | null>;

/** The workflow name a config file gets when it names none. */
export function fallbackWorkflowName(uri: vscode.Uri): string {
    return uri.path.split('/').pop()?.replace(/\.(ya?ml)$/, '') ?? 'workflow';
}

/**
 * Parse a workflow config file. Returns null when the file is not a mapping.
 * Throws with a readable message when the workflow cannot load.
 */
export async function parseWorkflowConfig(
    uri: vscode.Uri,
    renderViaLsp?: RenderViaLsp
): Promise<ParsedWorkflowConfig | null> {
    const contentBytes = await vscode.workspace.fs.readFile(uri);
    const content = Buffer.from(contentBytes).toString('utf8');
    const rendered = renderViaLsp ? await renderViaLsp(uri.toString()) : null;
    return parseLoadedWorkflow(content, fallbackWorkflowName(uri), uri.toString(), rendered);
}
