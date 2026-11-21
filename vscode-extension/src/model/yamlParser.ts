/**
 * YAML Workflow Config Parser
 *
 * Parses agent_config YAML files to extract:
 * - Workflow name
 * - Actions with dependencies, with each include, route and join entry as nodes
 *   (workflowEntries.ts, which holds the logic free of `vscode`)
 * - Line numbers for navigation (CodeLens)
 *
 * Uses the 'yaml' library (from PR #820/#821) for robust parsing
 */

import * as vscode from 'vscode';
import { parse } from 'yaml';
import { ParsedWorkflowConfig, ParsedAction } from './types';
import { logger } from '../utils/logger';
import {
    branchNames,
    extractActionLocations,
    normalizeOutputFields,
    parseEntries,
} from './workflowEntries';

/**
 * Parse a workflow config file and extract action information
 */
export async function parseWorkflowConfig(uri: vscode.Uri): Promise<ParsedWorkflowConfig | null> {
    try {
        const contentBytes = await vscode.workspace.fs.readFile(uri);
        const content = Buffer.from(contentBytes).toString('utf8');

        const doc = parse(content) as Record<string, unknown> | undefined;
        if (!doc || typeof doc !== 'object') {
            return null;
        }

        const workflowName = typeof doc.name === 'string'
            ? doc.name
            : uri.path.split('/').pop()?.replace(/\.(ya?ml)$/, '') ?? 'workflow';

        const actionLocations = extractActionLocations(content);
        const branches = await readBranches(uri, branchNames(doc.actions));
        const actions = parseActions(doc, content, branches);

        return {
            name: workflowName,
            actions,
            actionLocations,
        };
    } catch (error) {
        logger.error('Failed to parse workflow config', error);
        return null;
    }
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

/**
 * Extract action definitions from the parsed YAML
 */
function parseActions(
    doc: Record<string, unknown>,
    content: string,
    branches: Map<string, unknown>
): ParsedAction[] {
    const actionsValue = doc.actions;
    if (!Array.isArray(actionsValue)) {
        // Try plan-based format (from PR #822)
        return parsePlanBasedActions(doc, content);
    }
    return parseEntries(actionsValue, (name) => branches.get(name));
}

/**
 * Parse plan-based workflow format (action <- dependency syntax)
 */
function parsePlanBasedActions(doc: Record<string, unknown>, content: string): ParsedAction[] {
    const plan = doc.plan;
    if (!Array.isArray(plan)) {
        return [];
    }

    const actions: ParsedAction[] = [];
    const actionDefs = doc.actions;
    const actionDefMap = new Map<string, Record<string, unknown>>();

    if (Array.isArray(actionDefs)) {
        for (const def of actionDefs) {
            if (def && typeof def === 'object' && typeof (def as Record<string, unknown>).name === 'string') {
                actionDefMap.set((def as Record<string, unknown>).name as string, def as Record<string, unknown>);
            }
        }
    }

    for (const entry of plan) {
        if (typeof entry !== 'string') {
            continue;
        }

        const parsed = parsePlanEntry(entry);
        if (!parsed) {
            continue;
        }

        const actionDef = actionDefMap.get(parsed.name);
        const outputFields = actionDef
            ? normalizeOutputFields(actionDef.schema ?? actionDef.output_fields)
            : [];

        actions.push({
            name: parsed.name,
            dependencies: parsed.dependencies,
            outputFields,
        });
    }

    return actions;
}

/**
 * Parse a plan entry like "action_name <- dep1, dep2"
 */
function parsePlanEntry(entry: string): { name: string; dependencies: string[] } | null {
    const [namePart, depsPart] = entry.split('<-').map((s) => s.trim());
    if (!namePart) {
        return null;
    }

    const dependencies = depsPart
        ? depsPart.split(',').map((d) => d.trim()).filter(Boolean)
        : [];

    return { name: namePart, dependencies };
}
