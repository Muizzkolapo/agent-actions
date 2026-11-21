/**
 * YAML Workflow Config Parser
 *
 * Reads an agent_config file and parses it. A file that is not plain YAML (a workflow
 * that uses Jinja) is rendered by the language server, which runs the same render as agac.
 */

import * as vscode from 'vscode';
import { ParsedWorkflowConfig } from './types';
import { localActionLines, parseWorkflowText, RenderedWorkflowResult } from './workflowText';

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
    const fallbackName = fallbackWorkflowName(uri);

    try {
        return parseWorkflowText(content, fallbackName);
    } catch (rawError) {
        const rawMessage = rawError instanceof Error ? rawError.message : String(rawError);
        if (!renderViaLsp) {
            throw new Error(rawMessage);
        }
        const rendered = await renderViaLsp(uri.toString());
        if (!rendered) {
            throw new Error(`Not plain YAML, and the language server is not running: ${rawMessage}`);
        }
        if (rendered.text === null) {
            throw new Error(rendered.error ?? 'The language server has no project for this file');
        }
        const parsed = parseWorkflowText(rendered.text, fallbackName);
        if (parsed) {
            parsed.actionLocations = localActionLines(rendered.actionSources, uri.toString());
        }
        return parsed;
    }
}
