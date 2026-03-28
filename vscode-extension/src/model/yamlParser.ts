/**
 * YAML Workflow Config Parser
 *
 * Parses agent_config YAML files to extract:
 * - Workflow name
 * - Actions with dependencies
 * - Line numbers for navigation
 */

import * as vscode from 'vscode';
import { parse } from 'yaml';
import { ParsedWorkflowConfig, ParsedAction } from './types';

function createActionNameRegex(): RegExp {
    return /^\s*-\s*name:\s*([^\s#]+)\s*$/gm;
}

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
        const actions = parseActions(doc);

        return { name: workflowName, actions, actionLocations };
    } catch {
        return null;
    }
}

function parseActions(doc: Record<string, unknown>): ParsedAction[] {
    const actionsValue = doc.actions;
    if (!Array.isArray(actionsValue)) {
        return [];
    }

    const actions: ParsedAction[] = [];
    for (const entry of actionsValue) {
        const expanded = parseActionEntry(entry);
        if (expanded) {
            actions.push(...expanded);
        }
    }
    return actions;
}

function parseActionEntry(entry: unknown): ParsedAction[] | null {
    if (!entry || typeof entry !== 'object') {
        return null;
    }

    const action = entry as Record<string, unknown>;
    const name = typeof action.name === 'string' ? action.name : undefined;
    if (!name) {
        return null;
    }

    const dependencies = normalizeDependencies(action.dependencies);
    const outputFields = normalizeOutputFields(action.schema ?? action.output_fields);
    const type = typeof action.kind === 'string' ? action.kind : undefined;

    const versions = action.versions as Record<string, unknown> | undefined;
    if (versions && typeof versions === 'object') {
        const expanded = expandVersions(name, versions, dependencies, outputFields, type);
        if (expanded.length > 0) {
            return expanded;
        }
    }

    return [{ name, dependencies, type, outputFields }];
}

function expandVersions(
    baseName: string,
    versions: Record<string, unknown>,
    baseDependencies: string[],
    outputFields: string[],
    type: string | undefined
): ParsedAction[] {
    const range = versions.range;
    if (!Array.isArray(range) || range.length === 0) {
        return [];
    }

    return range.map((version) => ({
        name: `${baseName}_${version}`,
        dependencies: baseDependencies,
        type,
        outputFields,
        baseName,
        version: version as number | string,
    }));
}

function extractActionLocations(content: string): Map<string, number> {
    const locations = new Map<string, number>();
    const actionNameRegex = createActionNameRegex();
    let match: RegExpExecArray | null;

    while ((match = actionNameRegex.exec(content)) !== null) {
        const actionName = match[1];
        const line = content.slice(0, match.index).split(/\r?\n/).length - 1;
        if (!locations.has(actionName)) {
            locations.set(actionName, line);
        }
    }

    return locations;
}

function normalizeDependencies(value: unknown): string[] {
    if (!value) return [];
    if (Array.isArray(value)) return value.map((d) => String(d)).filter(Boolean);
    if (typeof value === 'string' && value.trim()) return [value.trim()];
    return [];
}

function normalizeOutputFields(value: unknown): string[] {
    if (!value) return [];
    if (Array.isArray(value)) return value.map((f) => String(f)).filter(Boolean);
    if (typeof value === 'object') return Object.keys(value);
    return [];
}
