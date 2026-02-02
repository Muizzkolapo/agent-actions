/**
 * Workflow Tree View Provider
 *
 * Displays workflows and actions in the Explorer sidebar.
 *
 * Combines best approaches:
 * - PR #820: WorkflowProjectNode, ActionNode classes
 * - PR #821: Version folders support, action versions
 * - PR #823: Multi-workflow support, status icons
 */

import * as vscode from 'vscode';
import { ActionInfo, ActionStatus, WorkflowInfo } from '../model/types';
import { WorkflowModel } from '../model/workflowModel';

/**
 * Tree node types
 */
type TreeNode = WorkflowNode | ActionNode | ActionGroupNode | DataPreviewNode;

/**
 * Workflow root node
 */
class WorkflowNode extends vscode.TreeItem {
    constructor(public readonly workflow: WorkflowInfo) {
        super(workflow.name, vscode.TreeItemCollapsibleState.Expanded);
        this.contextValue = 'agentActions.workflow';
        this.description = `${workflow.statusSummary.completed}/${workflow.statusSummary.total} completed`;
        this.tooltip = this.buildTooltip();
        this.iconPath = new vscode.ThemeIcon('graph');
    }

    private buildTooltip(): string {
        const s = this.workflow.statusSummary;
        return [
            `Workflow: ${this.workflow.name}`,
            `Path: ${this.workflow.rootPath}`,
            ``,
            `Status:`,
            `  Completed: ${s.completed}`,
            `  Running: ${s.running}`,
            `  Failed: ${s.failed}`,
            `  Pending: ${s.pending}`,
            `  Skipped: ${s.skipped}`,
        ].join('\n');
    }
}

/**
 * Action node with status icon
 */
class ActionNode extends vscode.TreeItem {
    constructor(public readonly action: ActionInfo) {
        super(
            `[${action.index}] ${action.name}`,
            vscode.TreeItemCollapsibleState.Collapsed
        );
        this.contextValue = 'agentActions.action';
        this.description = this.formatDescription();
        this.tooltip = this.buildTooltip();
        this.iconPath = getStatusIcon(action.status);
        this.command = {
            command: 'agentActions.openConfig',
            title: 'Open Action Config',
            arguments: [action],
        };
    }

    private formatDescription(): string {
        const statusLabel = getStatusLabel(this.action.status);
        return `${statusLabel} L${this.action.level}`;
    }

    private buildTooltip(): string {
        const deps = this.action.dependencies.length
            ? this.action.dependencies.join(', ')
            : 'None';
        const outputs = this.action.outputFields.length
            ? this.action.outputFields.join(', ')
            : 'None';
        const recordCount = this.action.recordCount != null
            ? `\nRecords: ${this.action.recordCount.toLocaleString()}`
            : '';

        return [
            `Action #${this.action.index}: ${this.action.name}`,
            `Type: ${this.action.type}`,
            `Status: ${this.action.status}`,
            `Level: ${this.action.level}`,
            `Dependencies: ${deps}`,
            `Outputs: ${outputs}`,
            recordCount,
        ].filter(Boolean).join('\n');
    }
}

/**
 * Action group node for versioned actions
 * Groups actions like extract_raw_qa_1, extract_raw_qa_2 under "extract_raw_qa"
 */
class ActionGroupNode extends vscode.TreeItem {
    constructor(
        public readonly baseName: string,
        public readonly actions: ActionInfo[]
    ) {
        super(baseName, vscode.TreeItemCollapsibleState.Collapsed);
        this.contextValue = 'agentActions.actionGroup';
        this.description = `${actions.length} versions`;
        this.iconPath = new vscode.ThemeIcon('versions');
        this.tooltip = `Versioned action: ${baseName}\n${actions.length} versions`;
    }
}

/**
 * Data preview node for viewing storage backend data
 */
class DataPreviewNode extends vscode.TreeItem {
    constructor(public readonly action: ActionInfo) {
        super('Preview Data', vscode.TreeItemCollapsibleState.None);
        this.contextValue = 'agentActions.dataPreview';
        this.iconPath = new vscode.ThemeIcon('database');
        this.tooltip = `Preview data from storage backend for ${action.name}`;
        this.command = {
            command: 'agentActions.previewData',
            title: 'Preview Data',
            arguments: [action],
        };
    }
}

/**
 * Get status icon for action
 */
function getStatusIcon(status: ActionStatus): vscode.ThemeIcon {
    switch (status) {
        case 'completed':
            return new vscode.ThemeIcon('check', new vscode.ThemeColor('charts.green'));
        case 'running':
            return new vscode.ThemeIcon('sync~spin', new vscode.ThemeColor('charts.yellow'));
        case 'failed':
            return new vscode.ThemeIcon('error', new vscode.ThemeColor('charts.red'));
        case 'skipped':
            return new vscode.ThemeIcon('circle-slash', new vscode.ThemeColor('charts.gray'));
        default:
            return new vscode.ThemeIcon('circle-outline', new vscode.ThemeColor('charts.gray'));
    }
}

/**
 * Get status label for description
 */
function getStatusLabel(status: ActionStatus): string {
    switch (status) {
        case 'completed':
            return '\u2713'; // ✓
        case 'running':
            return '\u21BB'; // ↻
        case 'failed':
            return '\u2717'; // ✗
        case 'skipped':
            return '\u2298'; // ⊘
        default:
            return '\u25CB'; // ○
    }
}

/**
 * Tree data provider for workflow navigator
 */
export class WorkflowTreeProvider implements vscode.TreeDataProvider<TreeNode>, vscode.Disposable {
    private readonly _onDidChangeTreeData = new vscode.EventEmitter<TreeNode | undefined>();
    readonly onDidChangeTreeData = this._onDidChangeTreeData.event;
    private readonly modelListener: vscode.Disposable;

    constructor(private readonly model: WorkflowModel) {
        this.modelListener = this.model.onDidChange(() => this._onDidChangeTreeData.fire(undefined));
    }

    dispose(): void {
        this._onDidChangeTreeData.dispose();
        this.modelListener.dispose();
    }

    getTreeItem(element: TreeNode): vscode.TreeItem {
        return element;
    }

    getChildren(element?: TreeNode): TreeNode[] {
        // Root level: show workflows
        if (!element) {
            const workflows = this.model.getWorkflows();
            if (workflows.length === 0) {
                return [];
            }
            // If single workflow, show actions directly
            if (workflows.length === 1) {
                return this.buildActionNodes(workflows[0].actions);
            }
            // Multiple workflows: show workflow nodes
            return workflows.map((w) => new WorkflowNode(w));
        }

        // Workflow level: show actions (with grouping)
        if (element instanceof WorkflowNode) {
            return this.buildActionNodes(element.workflow.actions);
        }

        // Action group level: show versioned actions
        if (element instanceof ActionGroupNode) {
            return element.actions.map((a) => new ActionNode(a));
        }

        // Action level: show data preview
        if (element instanceof ActionNode) {
            return [
                new DataPreviewNode(element.action),
            ];
        }

        return [];
    }

    /**
     * Build action nodes, grouping versioned actions under their base name
     */
    private buildActionNodes(actions: ActionInfo[]): TreeNode[] {
        const nodes: TreeNode[] = [];
        const groupedByBase = new Map<string, ActionInfo[]>();
        const standalone: ActionInfo[] = [];

        // Separate versioned and standalone actions
        for (const action of actions) {
            if (action.baseName) {
                const existing = groupedByBase.get(action.baseName) ?? [];
                existing.push(action);
                groupedByBase.set(action.baseName, existing);
            } else {
                standalone.push(action);
            }
        }

        // Add standalone actions
        for (const action of standalone) {
            nodes.push(new ActionNode(action));
        }

        // Add grouped actions
        for (const [baseName, versionedActions] of groupedByBase) {
            if (versionedActions.length === 1) {
                // Single version, show as standalone
                nodes.push(new ActionNode(versionedActions[0]));
            } else {
                // Multiple versions, group them
                nodes.push(new ActionGroupNode(baseName, versionedActions));
            }
        }

        // Sort by index
        nodes.sort((a, b) => {
            const indexA = a instanceof ActionNode ? a.action.index :
                a instanceof ActionGroupNode ? Math.min(...a.actions.map(act => act.index)) : 0;
            const indexB = b instanceof ActionNode ? b.action.index :
                b instanceof ActionGroupNode ? Math.min(...b.actions.map(act => act.index)) : 0;
            return indexA - indexB;
        });

        return nodes;
    }
}
