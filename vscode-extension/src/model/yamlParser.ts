/**
 * YAML Workflow Config Parser
 *
 * Reads an agent_config file and parses the text the language server renders from it,
 * with the same Jinja step as agac. With no server running, it parses the raw text.
 * Each include, route, join and loop entry becomes nodes (workflowEntries.ts).
 */

import * as vscode from 'vscode';
import { parse } from 'yaml';
import { ParsedWorkflowConfig } from './types';
import { loadedBranchNames, parseLoadedWorkflow, RenderedWorkflowResult } from './workflowText';

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
    const branches = await readBranches(uri, loadedBranchNames(content, rendered));
    return parseLoadedWorkflow(
        content,
        fallbackWorkflowName(uri),
        uri.toString(),
        rendered,
        (name) => branches.get(name)
    );
}

/**
 * The parsed branch files of *names*, from `<project>/branches/<name>.yml` (or `.yaml`),
 * the project being three folders above `agent_workflow/<workflow>/agent_config/`.
 * A file that cannot be read or parsed is left out; its include then shows no actions.
 */
async function readBranches(
    configUri: vscode.Uri,
    names: string[]
): Promise<Map<string, unknown>> {
    const branches = new Map<string, unknown>();
    const project = vscode.Uri.joinPath(configUri, '..', '..', '..', '..');
    for (const name of names) {
        for (const extension of ['yml', 'yaml']) {
            const branchUri = vscode.Uri.joinPath(project, 'branches', `${name}.${extension}`);
            try {
                const bytes = await vscode.workspace.fs.readFile(branchUri);
                branches.set(name, parse(Buffer.from(bytes).toString('utf8')));
                break;
            } catch {
                // Not there under this extension; try the next one.
            }
        }
    }
    return branches;
}
