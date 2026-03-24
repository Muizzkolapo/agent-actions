/**
 * Workflow Model
 *
 * Central model that combines the best approaches from all PRs:
 * - PR #820: Multi-project support (getProjects), buildExecutionPlan
 * - PR #821: Clean event emitter pattern, getActionByName/getActionByPath
 * - PR #822: registerCommands pattern, hasAgentProject helper
 * - PR #823: agent_status.json reading, statusSummary, polling with debounce
 *
 * This is the single source of truth for workflow state in the extension.
 */

import * as path from 'path';
import * as vscode from 'vscode';
import {
    ActionInfo,
    ActionStatus,
    ActionType,
    AgentStatusData,
    ManifestData,
    ParsedWorkflowConfig,
    StatusSummary,
    WorkflowInfo,
} from './types';
import { readManifest, readAgentStatus } from './manifestReader';
import { parseWorkflowConfig } from './yamlParser';

const CONFIG_GLOB = '**/agent_config/**/*.{yml,yaml}';
const MANIFEST_GLOB = '**/agent_io/target/.manifest.json';
const AGENT_STATUS_GLOB = '**/agent_io/.agent_status.json';

/** Minimum polling interval to prevent excessive refreshes */
const MIN_POLL_INTERVAL_MS = 1000;

/** Debounce delay for file watcher events */
const DEBOUNCE_MS = 250;

/**
 * Convert raw status string to ActionStatus enum
 */
function toActionStatus(status: string | undefined): ActionStatus {
    const normalized = (status ?? '').toLowerCase();
    if (['pending', 'running', 'completed', 'failed', 'skipped'].includes(normalized)) {
        return normalized as ActionStatus;
    }
    if (normalized === 'success') {
        return 'completed';
    }
    if (normalized === 'error') {
        return 'failed';
    }
    return 'pending';
}

/**
 * Infer action type from dependencies and configuration
 */
function toActionType(typeHint: string | undefined, dependencies: string[]): ActionType {
    if (typeHint) {
        const normalized = typeHint.toLowerCase();
        if (['source', 'transform', 'merge', 'parallel', 'output'].includes(normalized)) {
            return normalized as ActionType;
        }
    }

    if (dependencies.length === 0) {
        return 'source';
    }
    if (dependencies.length > 1) {
        return 'merge';
    }
    return 'transform';
}

/**
 * Get project root from config path (parent of agent_config)
 */
function getProjectRoot(configPath: string): string {
    const segments = configPath.split(path.sep);
    const agentConfigIndex = segments.lastIndexOf('agent_config');
    if (agentConfigIndex > 0) {
        return segments.slice(0, agentConfigIndex).join(path.sep);
    }
    return path.dirname(configPath);
}

/**
 * Resolve action status from manifest and agent_status.json
 * Agent status takes precedence as it's more up-to-date during execution
 */
function resolveActionStatus(
    manifest: ManifestData | null,
    agentStatus: AgentStatusData | null,
    actionName: string
): ActionStatus {
    // Check agent_status.json first (live runtime status)
    if (agentStatus) {
        const statusEntry = agentStatus[actionName];
        if (typeof statusEntry === 'string') {
            return toActionStatus(statusEntry);
        }
        if (typeof statusEntry === 'object' && statusEntry !== null) {
            const statusValue = (statusEntry as Record<string, unknown>).status;
            if (typeof statusValue === 'string') {
                return toActionStatus(statusValue);
            }
        }
    }

    // Fall back to manifest status
    const manifestStatus = manifest?.actions?.[actionName]?.status;
    if (manifestStatus) {
        return toActionStatus(manifestStatus);
    }

    return 'pending';
}

/**
 * Compute execution levels using topological sort
 */
function computeLevels(actions: { name: string; dependencies: string[] }[]): Map<string, number> {
    const levels = new Map<string, number>();
    const actionMap = new Map(actions.map((a) => [a.name, a]));

    const visit = (name: string, stack: Set<string>): number => {
        if (levels.has(name)) {
            return levels.get(name)!;
        }
        if (stack.has(name)) {
            return 0; // Cycle detected
        }

        stack.add(name);
        const action = actionMap.get(name);
        const deps = action?.dependencies ?? [];

        let level = 0;
        for (const dep of deps) {
            level = Math.max(level, visit(dep, stack) + 1);
        }

        stack.delete(name);
        levels.set(name, level);
        return level;
    };

    for (const action of actions) {
        visit(action.name, new Set());
    }

    return levels;
}

/**
 * Topological sort for execution order
 */
function topoSort(actions: { name: string; dependencies: string[] }[]): string[] {
    const inDegree = new Map<string, number>();
    const edges = new Map<string, Set<string>>();

    // Initialize
    actions.forEach((action) => {
        inDegree.set(action.name, 0);
        edges.set(action.name, new Set());
    });

    // Build graph
    actions.forEach((action) => {
        action.dependencies.forEach((dep) => {
            if (!edges.has(dep)) {
                edges.set(dep, new Set());
                inDegree.set(dep, 0);
            }
            edges.get(dep)!.add(action.name);
            inDegree.set(action.name, (inDegree.get(action.name) ?? 0) + 1);
        });
    });

    // Kahn's algorithm
    const queue = Array.from(inDegree.entries())
        .filter(([, degree]) => degree === 0)
        .map(([name]) => name);
    const ordered: string[] = [];

    while (queue.length > 0) {
        const current = queue.shift()!;
        ordered.push(current);

        edges.get(current)?.forEach((neighbor) => {
            const nextDegree = (inDegree.get(neighbor) ?? 0) - 1;
            inDegree.set(neighbor, nextDegree);
            if (nextDegree === 0) {
                queue.push(neighbor);
            }
        });
    }

    // Add any remaining actions (handles cycles) - use Set for O(1) lookup
    const orderedSet = new Set(ordered);
    const remaining = actions
        .map((a) => a.name)
        .filter((name) => !orderedSet.has(name));

    return ordered.concat(remaining);
}

/**
 * Central workflow model that manages all workflow data
 */
export class WorkflowModel implements vscode.Disposable {
    private workflows = new Map<string, WorkflowInfo>();
    private readonly _onDidChange = new vscode.EventEmitter<void>();
    private readonly watchers: vscode.FileSystemWatcher[] = [];
    private refreshTimeout: NodeJS.Timeout | undefined;
    private pollingTimer: NodeJS.Timeout | undefined;
    private configListener: vscode.Disposable | undefined;
    private refreshInProgress = false;
    private pendingRefresh = false;

    readonly onDidChange = this._onDidChange.event;

    constructor() {
        // Set up file watchers
        this.watchers.push(
            vscode.workspace.createFileSystemWatcher(CONFIG_GLOB),
            vscode.workspace.createFileSystemWatcher(MANIFEST_GLOB),
            vscode.workspace.createFileSystemWatcher(AGENT_STATUS_GLOB)
        );

        this.watchers.forEach((watcher) => {
            watcher.onDidChange(() => this.scheduleRefresh());
            watcher.onDidCreate(() => this.scheduleRefresh());
            watcher.onDidDelete(() => this.scheduleRefresh());
        });

        // Watch for config changes
        this.configListener = vscode.workspace.onDidChangeConfiguration((event) => {
            if (event.affectsConfiguration('agentActions.refreshInterval')) {
                this.configurePolling();
            }
        });

        // Initial load and polling setup
        this.scheduleRefresh();
        this.configurePolling();
    }

    dispose(): void {
        this.watchers.forEach((w) => w.dispose());
        this._onDidChange.dispose();
        this.configListener?.dispose();
        if (this.refreshTimeout) {
            clearTimeout(this.refreshTimeout);
        }
        if (this.pollingTimer) {
            clearInterval(this.pollingTimer);
        }
    }

    /**
     * Get all workflows (multi-project support from PR #820)
     */
    getWorkflows(): WorkflowInfo[] {
        return Array.from(this.workflows.values());
    }

    /**
     * Check if any agent project is detected (from PR #822)
     */
    hasAgentProject(): boolean {
        return this.workflows.size > 0;
    }

    /**
     * Get workflow by name
     */
    getWorkflowByName(name: string): WorkflowInfo | undefined {
        return this.workflows.get(name);
    }

    /**
     * Get action by name (searches all workflows)
     */
    getActionByName(actionName: string): ActionInfo | undefined {
        for (const workflow of this.workflows.values()) {
            const action = workflow.actions.find((a) => a.name === actionName);
            if (action) {
                return action;
            }
        }
        return undefined;
    }

    /**
     * Get action by file path (for file decorations)
     */
    getActionByPath(filePath: string): ActionInfo | undefined {
        const normalized = path.normalize(filePath);
        for (const workflow of this.workflows.values()) {
            const action = workflow.actions.find((a) =>
                normalized.startsWith(path.normalize(a.folderPath))
            );
            if (action) {
                return action;
            }
        }
        return undefined;
    }

    /**
     * Refresh all workflow data
     */
    async refresh(): Promise<void> {
        // Prevent concurrent refreshes (race condition guard)
        // Queue a pending refresh if one is already in progress
        if (this.refreshInProgress) {
            this.pendingRefresh = true;
            return;
        }
        this.refreshInProgress = true;

        try {
            const configFiles = await vscode.workspace.findFiles(CONFIG_GLOB, '**/node_modules/**');
            const workflows = new Map<string, WorkflowInfo>();

            for (const configUri of configFiles) {
                const parsedConfig = await parseWorkflowConfig(configUri);
                if (!parsedConfig || parsedConfig.actions.length === 0) {
                    continue;
                }

                const workflow = await this.buildWorkflow(configUri, parsedConfig);
                workflows.set(workflow.name, workflow);
            }

            this.workflows = workflows;

            // Update context for keybindings
            await vscode.commands.executeCommand(
                'setContext',
                'agentActions.isAgentProject',
                workflows.size > 0
            );

            this._onDidChange.fire();
        } finally {
            this.refreshInProgress = false;

            // Process pending refresh if one was queued
            if (this.pendingRefresh) {
                this.pendingRefresh = false;
                void this.refresh();
            }
        }
    }

    /**
     * Schedule a debounced refresh
     */
    private scheduleRefresh(): void {
        if (this.refreshTimeout) {
            clearTimeout(this.refreshTimeout);
        }
        this.refreshTimeout = setTimeout(() => void this.refresh(), DEBOUNCE_MS);
    }

    /**
     * Configure polling interval from settings
     */
    private configurePolling(): void {
        if (this.pollingTimer) {
            clearInterval(this.pollingTimer);
            this.pollingTimer = undefined;
        }

        const config = vscode.workspace.getConfiguration('agentActions');
        const configuredInterval = config.get<number>('refreshInterval', 0);

        // Enforce minimum polling interval to prevent excessive refreshes
        const interval = configuredInterval > 0
            ? Math.max(configuredInterval, MIN_POLL_INTERVAL_MS)
            : 0;

        if (interval > 0) {
            this.pollingTimer = setInterval(() => void this.refresh(), interval);
        }
    }

    /**
     * Build a WorkflowInfo from parsed config and runtime data
     */
    private async buildWorkflow(
        configUri: vscode.Uri,
        parsedConfig: ParsedWorkflowConfig
    ): Promise<WorkflowInfo> {
        const configPath = configUri.fsPath;
        const rootPath = getProjectRoot(configPath);
        const agentIoPath = path.join(rootPath, 'agent_io');

        // Read runtime status files
        const manifestUri = vscode.Uri.file(path.join(agentIoPath, 'target', '.manifest.json'));
        const statusUri = vscode.Uri.file(path.join(agentIoPath, '.agent_status.json'));

        const [manifest, agentStatus] = await Promise.all([
            readManifest(manifestUri),
            readAgentStatus(statusUri),
        ]);

        // Build a map of base names → versioned action names so downstream
        // dependencies that reference the base name (e.g. "score_quality")
        // are expanded to all versioned names (e.g. ["score_quality_1", "score_quality_2", "score_quality_3"]).
        const versionedNames = new Map<string, string[]>();
        const allActionNames = new Set(parsedConfig.actions.map((a) => a.name));
        for (const action of parsedConfig.actions) {
            if (action.baseName) {
                const bucket = versionedNames.get(action.baseName) ?? [];
                bucket.push(action.name);
                versionedNames.set(action.baseName, bucket);
            }
        }

        /** Resolve dependencies: expand base names to versioned names */
        const resolveDeps = (deps: string[]): string[] => {
            const resolved: string[] = [];
            for (const dep of deps) {
                if (allActionNames.has(dep)) {
                    // Exact match — keep as-is
                    resolved.push(dep);
                } else if (versionedNames.has(dep)) {
                    // Base name of a versioned action — expand
                    resolved.push(...versionedNames.get(dep)!);
                } else {
                    // Unknown dep — keep as-is (may come from manifest)
                    resolved.push(dep);
                }
            }
            return resolved;
        };

        // Resolve dependencies on parsed actions before topo-sort so
        // execution order and level computation see the real graph.
        const resolvedActions = parsedConfig.actions.map((a) => ({
            ...a,
            dependencies: resolveDeps(a.dependencies),
        }));

        // Compute execution order (prefer manifest, fall back to computed)
        const executionOrder = manifest?.execution_order?.length
            ? manifest.execution_order
            : topoSort(resolvedActions);

        // Compute levels
        const computedLevels = computeLevels(resolvedActions);

        // Build action infos
        const actions: ActionInfo[] = resolvedActions.map((actionConfig) => {
            const manifestAction = manifest?.actions?.[actionConfig.name];
            const level = manifestAction?.level ?? computedLevels.get(actionConfig.name) ?? 0;
            const index = executionOrder.indexOf(actionConfig.name);
            const actionIndex = index >= 0 ? index + 1 : resolvedActions.indexOf(actionConfig) + 1;
            const outputDir = manifestAction?.output_dir ?? actionConfig.name;
            const folderPath = path.join(agentIoPath, 'target', outputDir);
            const status = resolveActionStatus(manifest, agentStatus, actionConfig.name);
            const type = toActionType(actionConfig.type, actionConfig.dependencies);
            // For versioned actions, use the base name's location
            const locationName = actionConfig.baseName ?? actionConfig.name;
            const line = parsedConfig.actionLocations.get(locationName) ?? 0;
            const configLocation = new vscode.Location(configUri, new vscode.Position(line, 0));

            return {
                name: actionConfig.name,
                index: actionIndex,
                level,
                status,
                type,
                folderPath,
                configLocation,
                dependencies: manifestAction?.dependencies ?? actionConfig.dependencies,
                outputFields: actionConfig.outputFields,
                outputDir,
                recordCount: manifestAction?.record_count ?? null,
                baseName: actionConfig.baseName,
                version: actionConfig.version,
            };
        });

        // Apply manifest levels if available
        if (manifest?.levels?.length) {
            manifest.levels.forEach((levelActions, levelIndex) => {
                levelActions.forEach((actionName) => {
                    const action = actions.find((a) => a.name === actionName);
                    if (action) {
                        action.level = levelIndex;
                        // Mark parallel actions
                        if (levelActions.length > 1) {
                            action.type = 'parallel';
                        }
                    }
                });
            });
        }

        // Build levels map
        const levelsMap = new Map<number, ActionInfo[]>();
        actions.forEach((action) => {
            const bucket = levelsMap.get(action.level) ?? [];
            bucket.push(action);
            levelsMap.set(action.level, bucket);
        });

        // Compute status summary
        const statusSummary = actions.reduce<StatusSummary>(
            (summary, action) => {
                summary.total += 1;
                summary[action.status] += 1;
                return summary;
            },
            { total: 0, completed: 0, running: 0, failed: 0, pending: 0, skipped: 0 }
        );

        // Sort by index
        actions.sort((a, b) => a.index - b.index);

        return {
            name: manifest?.workflow_name ?? parsedConfig.name,
            rootPath,
            configPath,
            actions,
            executionOrder,
            levels: levelsMap,
            statusSummary,
        };
    }
}
