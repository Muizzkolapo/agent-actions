/**
 * Workflow text to actions, with no editor dependency, so it can be tested under node:test.
 */

import { parse } from 'yaml';
import type { ParsedWorkflowConfig, ParsedAction } from './types';
import {
    BranchLookup,
    branchNames,
    extractActionLocations,
    parseEntries,
} from './workflowEntries';

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

/**
 * Parse workflow YAML text. Throws on a YAML error, for example on raw Jinja.
 * Returns null when the document is not a mapping.
 */
export function parseWorkflowText(
    content: string,
    fallbackName: string,
    branches: BranchLookup = () => undefined
): ParsedWorkflowConfig | null {
    const doc = parseDocument(content);
    if (!doc) {
        return null;
    }

    const name = typeof doc.name === 'string' ? doc.name : fallbackName;
    return {
        name,
        actions: parseActions(doc, branches),
        actionLocations: extractActionLocations(content),
    };
}

/** The branch files that the workflow agac loads includes; none when it does not parse. */
export function loadedBranchNames(content: string, rendered: RenderedWorkflowResult | null): string[] {
    const text = rendered && !rendered.error && rendered.text !== null ? rendered.text : content;
    try {
        return branchNames(parseDocument(text)?.actions);
    } catch {
        return [];
    }
}

function parseDocument(content: string): Record<string, unknown> | null {
    // agac reads YAML with PyYAML, which keeps the last of two equal keys.
    const doc = parse(content, { uniqueKeys: false }) as Record<string, unknown> | undefined;
    return doc && typeof doc === 'object' ? doc : null;
}

/**
 * The workflow as agac loads it. The language server's render comes first, because raw
 * Jinja can still be valid YAML (`{{ branch('a') }}` under `actions:` parses as a key) and
 * would then show the wrong actions. With no render, the raw text is all there is.
 */
export function parseLoadedWorkflow(
    content: string,
    fallbackName: string,
    configUri: string,
    rendered: RenderedWorkflowResult | null,
    branches: BranchLookup = () => undefined
): ParsedWorkflowConfig | null {
    if (rendered?.error) {
        throw new Error(rendered.error);
    }
    if (rendered && rendered.text !== null) {
        const parsed = parseWorkflowText(rendered.text, fallbackName, branches);
        if (parsed) {
            parsed.actionLocations = localActionLines(rendered.actionSources, configUri);
        }
        return parsed;
    }
    try {
        return parseWorkflowText(content, fallbackName, branches);
    } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        throw new Error(`${message} (A workflow that uses Jinja loads only through the language server.)`);
    }
}

/** A name for a workflow that did not load, which never takes the place of one that did. */
export function uniqueWorkflowName(name: string, taken: ReadonlySet<string>, where: string): string {
    return taken.has(name) ? `${name} (${where})` : name;
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
function parseActions(doc: Record<string, unknown>, branches: BranchLookup): ParsedAction[] {
    const actionsValue = doc.actions;
    if (!Array.isArray(actionsValue)) {
        return [];
    }
    return parseEntries(actionsValue, branches);
}
