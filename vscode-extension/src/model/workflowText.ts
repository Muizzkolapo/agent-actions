/**
 * Workflow text to actions, with no editor dependency, so it can be tested under node:test.
 */

import { parse } from 'yaml';
import type { ParsedWorkflowConfig, ParsedAction } from './types';

/** One action's source line, as the language server reports it. */
export interface ActionSource {
    uri: string;
    line: number;
}

/** Result of the `agentActions/renderedWorkflow` request. */
export interface RenderedWorkflowResult {
    text: string | null;
    error: string | null;
    actionSources: Record<string, ActionSource>;
}

/** Factory function to avoid regex state sharing issues */
function createActionNameRegex(): RegExp {
    return /^\s*-\s*name:\s*([^\s#]+)\s*$/gm;
}

/**
 * Parse workflow YAML text. Throws on a YAML error, for example on raw Jinja.
 * Returns null when the document is not a mapping.
 */
export function parseWorkflowText(content: string, fallbackName: string): ParsedWorkflowConfig | null {
    const doc = parse(content) as Record<string, unknown> | undefined;
    if (!doc || typeof doc !== 'object') {
        return null;
    }

    const name = typeof doc.name === 'string' ? doc.name : fallbackName;
    return {
        name,
        actions: parseActions(doc, content),
        actionLocations: extractActionLocations(content),
    };
}

/** The lines of the actions defined in the config file itself; macro actions live elsewhere. */
export function localActionLines(
    sources: Record<string, ActionSource>,
    configUri: string
): Map<string, number> {
    const lines = new Map<string, number>();
    const target = normalizeFileUri(configUri);
    for (const [name, source] of Object.entries(sources)) {
        if (normalizeFileUri(source.uri) === target) {
            lines.set(name, source.line);
        }
    }
    return lines;
}

/** Python and VS Code encode the same path differently (percent escapes, drive letter case). */
function normalizeFileUri(uri: string): string {
    return decodeURIComponent(uri).replace(/^file:\/\/\/([A-Za-z]):/, (_m, drive: string) => `file:///${drive.toLowerCase()}:`);
}

/**
 * Extract action definitions from the parsed YAML
 */
function parseActions(doc: Record<string, unknown>, content: string): ParsedAction[] {
    const actionsValue = doc.actions;
    if (!Array.isArray(actionsValue)) {
        // Try plan-based format (from PR #822)
        return parsePlanBasedActions(doc, content);
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

/**
 * Parse a single action entry from the YAML, expanding versions if present
 * Returns array to handle version expansion (e.g., action with versions: {range: [1,2,3]}
 * becomes action_1, action_2, action_3)
 */
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

    // Check for versions expansion
    const versions = action.versions as Record<string, unknown> | undefined;
    if (versions && typeof versions === 'object') {
        const expanded = expandVersions(name, versions, dependencies, outputFields, type);
        if (expanded.length > 0) {
            return expanded;
        }
    }

    return [{ name, dependencies, type, outputFields }];
}

/**
 * Expand a versioned action into multiple concrete actions.
 *
 * Supports two range formats (mirroring the core engine in expander.py):
 *   - Pair: [start, end] → expands to start..end inclusive
 *   - Explicit list: [1, 2, 3] → used as-is
 */
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

    // When range is a [start, end] pair, expand to the full sequence.
    // This matches the core engine: range(start, end + 1).
    let rangeValues: (number | string)[] = range;
    if (range.length === 2 && typeof range[0] === 'number' && typeof range[1] === 'number') {
        const [start, end] = range as [number, number];
        rangeValues = [];
        for (let v = start; v <= end; v++) {
            rangeValues.push(v);
        }
    }

    return rangeValues.map((version) => {
        const versionSuffix = `_${version}`;
        const versionedName = `${baseName}${versionSuffix}`;

        // Version dependencies: if base depends on "foo", versioned depends on "foo"
        // (the actual version resolution happens at runtime)
        return {
            name: versionedName,
            dependencies: baseDependencies,
            type,
            outputFields,
            baseName, // Track the base name for grouping
            version: version as number | string,
        };
    });
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

/**
 * Extract line numbers for each action (for CodeLens navigation)
 */
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

/**
 * Normalize dependencies to string array
 */
function normalizeDependencies(value: unknown): string[] {
    if (!value) {
        return [];
    }
    if (Array.isArray(value)) {
        return value.map((d) => String(d)).filter(Boolean);
    }
    if (typeof value === 'string' && value.trim()) {
        return [value.trim()];
    }
    return [];
}

/**
 * Normalize output fields from schema or output_fields
 */
function normalizeOutputFields(value: unknown): string[] {
    if (!value) {
        return [];
    }
    if (Array.isArray(value)) {
        return value.map((f) => String(f)).filter(Boolean);
    }
    if (typeof value === 'object') {
        return Object.keys(value);
    }
    return [];
}
