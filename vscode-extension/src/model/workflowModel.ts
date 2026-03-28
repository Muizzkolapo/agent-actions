/**
 * Workflow Model
 *
 * Central model that manages all workflow data for the sidebar tree view.
 * Parses YAML configs and reads runtime status from manifest/agent_status files.
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

const DEBOUNCE_MS = 250;

function toActionStatus(status: string | undefined): ActionStatus {
    const normalized = (status ?? '').toLowerCase();
    if (['pending', 'running', 'completed', 'failed', 'skipped'].includes(normalized)) {
        return normalized as ActionStatus;
    }
    if (normalized === 'success') return 'completed';
    if (normalized === 'error') return 'failed';
    return 'pending';
}

function toActionType(typeHint: string | undefined, dependencies: string[]): ActionType {
    if (typeHint) {
        const normalized = typeHint.toLowerCase();
        if (['source', 'transform', 'merge', 'parallel', 'output'].includes(normalized)) {
            return normalized as ActionType;
        }
    }
    if (dependencies.length === 0) return 'source';
    if (dependencies.length > 1) return 'merge';
    return 'transform';
}

function getProjectRoot(configPath: string): string {
    const segments = configPath.split(path.sep);
    const agentConfigIndex = segments.lastIndexOf('agent_config');
    if (agentConfigIndex > 0) {
        return segments.slice(0, agentConfigIndex).join(path.sep);
    }
    return path.dirname(configPath);
}

function resolveActionStatus(
    manifest: ManifestData | null,
    agentStatus: AgentStatusData | null,
    actionName: string
): ActionStatus {
    if (agentStatus) {
        const statusEntry = agentStatus[actionName];
        if (typeof statusEntry === 'string') return toActionStatus(statusEntry);
        if (typeof statusEntry === 'object' && statusEntry !== null) {
            const statusValue = (statusEntry as Record<string, unknown>).status;
            if (typeof statusValue === 'string') return toActionStatus(statusValue);
        }
    }
    const manifestStatus = manifest?.actions?.[actionName]?.status;
    if (manifestStatus) return toActionStatus(manifestStatus);
    return 'pending';
}

function computeLevels(actions: { name: string; dependencies: string[] }[]): Map<string, number> {
    const levels = new Map<string, number>();
    const actionMap = new Map(actions.map((a) => [a.name, a]));

    const visit = (name: string, stack: Set<string>): number => {
        if (levels.has(name)) return levels.get(name)!;
        if (stack.has(name)) return 0;
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

function topoSort(actions: { name: string; dependencies: string[] }[]): string[] {
    const inDegree = new Map<string, number>();
    const edges = new Map<string, Set<string>>();

    actions.forEach((action) => {
        inDegree.set(action.name, 0);
        edges.set(action.name, new Set());
    });

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
            if (nextDegree === 0) queue.push(neighbor);
        });
    }

    const orderedSet = new Set(ordered);
    const remaining = actions.map((a) => a.name).filter((name) => !orderedSet.has(name));
    return ordered.concat(remaining);
}

export class WorkflowModel implements vscode.Disposable {
    private workflows = new Map<string, WorkflowInfo>();
    private readonly _onDidChange = new vscode.EventEmitter<void>();
    private readonly watchers: vscode.FileSystemWatcher[] = [];
    private refreshTimeout: NodeJS.Timeout | undefined;
    private refreshInProgress = false;
    private pendingRefresh = false;

    readonly onDidChange = this._onDidChange.event;

    constructor() {
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

        this.scheduleRefresh();
    }

    dispose(): void {
        this.watchers.forEach((w) => w.dispose());
        this._onDidChange.dispose();
        if (this.refreshTimeout) clearTimeout(this.refreshTimeout);
    }

    getWorkflows(): WorkflowInfo[] {
        return Array.from(this.workflows.values());
    }

    getActionByName(actionName: string): ActionInfo | undefined {
        for (const workflow of this.workflows.values()) {
            const action = workflow.actions.find((a) => a.name === actionName);
            if (action) return action;
        }
        return undefined;
    }

    async refresh(): Promise<void> {
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
                if (!parsedConfig || parsedConfig.actions.length === 0) continue;

                const workflow = await this.buildWorkflow(configUri, parsedConfig);
                workflows.set(workflow.name, workflow);
            }

            this.workflows = workflows;
            await vscode.commands.executeCommand(
                'setContext', 'agentActions.isAgentProject', workflows.size > 0
            );
            this._onDidChange.fire();
        } finally {
            this.refreshInProgress = false;
            if (this.pendingRefresh) {
                this.pendingRefresh = false;
                void this.refresh();
            }
        }
    }

    private scheduleRefresh(): void {
        if (this.refreshTimeout) clearTimeout(this.refreshTimeout);
        this.refreshTimeout = setTimeout(() => void this.refresh(), DEBOUNCE_MS);
    }

    private async buildWorkflow(
        configUri: vscode.Uri,
        parsedConfig: ParsedWorkflowConfig
    ): Promise<WorkflowInfo> {
        const configPath = configUri.fsPath;
        const rootPath = getProjectRoot(configPath);
        const agentIoPath = path.join(rootPath, 'agent_io');

        const manifestUri = vscode.Uri.file(path.join(agentIoPath, 'target', '.manifest.json'));
        const statusUri = vscode.Uri.file(path.join(agentIoPath, '.agent_status.json'));

        const [manifest, agentStatus] = await Promise.all([
            readManifest(manifestUri),
            readAgentStatus(statusUri),
        ]);

        const versionedNames = new Map<string, string[]>();
        const allActionNames = new Set(parsedConfig.actions.map((a) => a.name));
        for (const action of parsedConfig.actions) {
            if (action.baseName) {
                const bucket = versionedNames.get(action.baseName) ?? [];
                bucket.push(action.name);
                versionedNames.set(action.baseName, bucket);
            }
        }

        const resolveDeps = (deps: string[]): string[] => {
            const resolved: string[] = [];
            for (const dep of deps) {
                if (allActionNames.has(dep)) resolved.push(dep);
                else if (versionedNames.has(dep)) resolved.push(...versionedNames.get(dep)!);
                else resolved.push(dep);
            }
            return resolved;
        };

        const resolvedActions = parsedConfig.actions.map((a) => ({
            ...a,
            dependencies: resolveDeps(a.dependencies),
        }));

        const executionOrder = manifest?.execution_order?.length
            ? manifest.execution_order
            : topoSort(resolvedActions);

        const computedLevels = computeLevels(resolvedActions);

        const actions: ActionInfo[] = resolvedActions.map((actionConfig) => {
            const manifestAction = manifest?.actions?.[actionConfig.name];
            const level = manifestAction?.level ?? computedLevels.get(actionConfig.name) ?? 0;
            const index = executionOrder.indexOf(actionConfig.name);
            const actionIndex = index >= 0 ? index + 1 : resolvedActions.indexOf(actionConfig) + 1;
            const outputDir = manifestAction?.output_dir ?? actionConfig.name;
            const folderPath = path.join(agentIoPath, 'target', outputDir);
            const status = resolveActionStatus(manifest, agentStatus, actionConfig.name);
            const type = toActionType(actionConfig.type, actionConfig.dependencies);
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

        if (manifest?.levels?.length) {
            manifest.levels.forEach((levelActions, levelIndex) => {
                levelActions.forEach((actionName) => {
                    const action = actions.find((a) => a.name === actionName);
                    if (action) {
                        action.level = levelIndex;
                        if (levelActions.length > 1) action.type = 'parallel';
                    }
                });
            });
        }

        const levelsMap = new Map<number, ActionInfo[]>();
        actions.forEach((action) => {
            const bucket = levelsMap.get(action.level) ?? [];
            bucket.push(action);
            levelsMap.set(action.level, bucket);
        });

        const statusSummary = actions.reduce<StatusSummary>(
            (summary, action) => {
                summary.total += 1;
                summary[action.status] += 1;
                return summary;
            },
            { total: 0, completed: 0, running: 0, failed: 0, pending: 0, skipped: 0 }
        );

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
