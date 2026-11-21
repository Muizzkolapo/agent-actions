/**
 * The workflow entries of an agent_config file, as the nodes of its DAG.
 *
 * Free of `vscode` so it can be tested outside the editor host: the caller reads the
 * branch files and hands them in by name.
 */

import type { ParsedAction } from './types';

/** A parsed branch file (`branches/<name>.yml`) by branch name; undefined when it cannot be read. */
export type BranchLookup = (name: string) => unknown;

/** Every name an `include:` entry reads a branch file for. */
export function branchNames(entries: unknown): string[] {
    if (!Array.isArray(entries)) {
        return [];
    }
    const names = new Set<string>();
    for (const entry of entries) {
        const record = asRecord(entry);
        if (record && typeof record.include === 'string') {
            names.add(record.include);
        }
    }
    return [...names];
}

/**
 * The actions of *entries* in order: plain actions (versions expanded), the actions of each
 * `- include:` (renamed `<as>__<name>` under `as:`), and a node for each `- route:` and
 * `- join:`. The entry actions of each branch of a router depend on the router.
 */
export function parseEntries(entries: unknown[], branches: BranchLookup): ParsedAction[] {
    const actions: ParsedAction[] = [];
    const instances = new Map<string, Instance>();
    const routes: Array<{ router: string; targets: unknown[] }> = [];
    for (const entry of entries) {
        const record = asRecord(entry);
        if (!record) {
            continue;
        }
        if (typeof record.include === 'string') {
            const instance = includeInstance(record, branches);
            if (instance) {
                actions.push(...instance.actions);
                instances.set(instance.label, instance);
            }
        } else if (typeof record.route === 'string') {
            actions.push(routeNode(record.route, record.on));
            const cases = asRecord(record.cases) ?? {};
            routes.push({ router: record.route, targets: [...Object.values(cases), record.default] });
        } else if (typeof record.join === 'string') {
            actions.push({
                name: record.join,
                dependencies: joinSources(record.of, instances),
                type: 'join',
                outputFields: [],
            });
        } else {
            actions.push(...(parseActionEntry(record) ?? []));
        }
    }
    for (const { router, targets } of routes) {
        for (const target of targets) {
            for (const name of entryActions(target, instances)) {
                const action = actions.find((candidate) => candidate.name === name);
                if (action && !action.dependencies.includes(router)) {
                    action.dependencies = [...action.dependencies, router];
                }
            }
        }
    }
    return actions;
}

/** The line of each action, route, join and loop name, for CodeLens navigation. */
export function extractActionLocations(content: string): Map<string, number> {
    const locations = new Map<string, number>();
    const pattern = /^\s*-\s*(?:name|route|join|loop):\s*([^\s#]+)\s*$/gm;
    let match: RegExpExecArray | null;
    while ((match = pattern.exec(content)) !== null) {
        const name = match[1];
        const line = content.slice(0, match.index).split(/\r?\n/).length - 1;
        if (!locations.has(name)) {
            locations.set(name, line);
        }
    }
    return locations;
}

interface Instance {
    /** The `as:` name, or the branch name for an include without one. */
    label: string;
    actions: ParsedAction[];
    /** Branch name to final name. */
    names: Map<string, string>;
    outputs: string[];
}

function includeInstance(record: Record<string, unknown>, branches: BranchLookup): Instance | null {
    const branchName = record.include as string;
    const branch = asRecord(branches(branchName));
    if (!branch || !Array.isArray(branch.actions)) {
        return null;
    }
    const prefix = typeof record.as === 'string' ? record.as : undefined;
    const inputs = asRecord(record.inputs) ?? {};
    const removed = new Set(normalizeDependencies(record.remove));
    const own = branch.actions
        .map(asRecord)
        .filter((action): action is Record<string, unknown> => !!action && typeof action.name === 'string')
        .filter((action) => !removed.has(action.name as string));
    const names = new Map<string, string>();
    for (const action of own) {
        const local = action.name as string;
        names.set(local, prefix ? `${prefix}__${local}` : local);
    }
    const rename = (name: string): string => {
        const bound = inputs[name];
        if (typeof bound === 'string') {
            return bound;
        }
        return names.get(name) ?? name;
    };
    const actions: ParsedAction[] = [];
    for (const action of own) {
        for (const parsed of parseActionEntry(action) ?? []) {
            const base = parsed.baseName ?? (action.name as string);
            const final = names.get(base) ?? base;
            actions.push({
                ...parsed,
                name: parsed.version === undefined ? final : `${final}_${parsed.version}`,
                baseName: parsed.baseName === undefined ? undefined : final,
                dependencies: parsed.dependencies.map(rename),
            });
        }
    }
    const outputs = normalizeDependencies(branch.outputs).map((name) => names.get(name) ?? name);
    return { label: prefix ?? branchName, actions, names, outputs };
}

function routeNode(name: string, on: unknown): ParsedAction {
    const field = typeof on === 'string' ? on : '';
    const action = field.split('.', 1)[0];
    return {
        name,
        dependencies: action && action !== 'source' ? [action] : [],
        type: 'route',
        outputFields: ['case'],
    };
}

function joinSources(of: unknown, instances: Map<string, Instance>): string[] {
    const listed = typeof of === 'string' ? [of] : normalizeDependencies(of);
    return listed.flatMap((name) => {
        const instance = instances.get(name);
        return instance ? instance.outputs : [name];
    });
}

/** The actions a router case or default names: a list of actions, or an instance's entry actions. */
function entryActions(target: unknown, instances: Map<string, Instance>): string[] {
    if (Array.isArray(target)) {
        return target.map(String);
    }
    if (typeof target !== 'string' || target === 'filter') {
        return [];
    }
    const instance = instances.get(target);
    if (!instance) {
        return [];
    }
    const own = new Set(instance.names.values());
    return instance.actions
        .filter((action) => !action.dependencies.some((dep) => own.has(dep)))
        .map((action) => action.name);
}

/**
 * Parse a single action entry, expanding versions if present: an action with
 * `versions: {range: [1, 3]}` becomes action_1, action_2 and action_3.
 */
export function parseActionEntry(action: Record<string, unknown>): ParsedAction[] | null {
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

    let rangeValues: (number | string)[] = range;
    if (range.length === 2 && typeof range[0] === 'number' && typeof range[1] === 'number') {
        const [start, end] = range as [number, number];
        rangeValues = [];
        for (let v = start; v <= end; v++) {
            rangeValues.push(v);
        }
    }

    return rangeValues.map((version) => ({
        name: `${baseName}_${version}`,
        dependencies: baseDependencies,
        type,
        outputFields,
        baseName,
        version: version as number | string,
    }));
}

export function normalizeDependencies(value: unknown): string[] {
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

export function normalizeOutputFields(value: unknown): string[] {
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

function asRecord(value: unknown): Record<string, unknown> | null {
    return value && typeof value === 'object' && !Array.isArray(value)
        ? (value as Record<string, unknown>)
        : null;
}
