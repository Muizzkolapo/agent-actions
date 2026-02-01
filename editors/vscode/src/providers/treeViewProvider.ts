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

import * as path from 'path';
import * as vscode from 'vscode';
import { ActionInfo, ActionStatus, WorkflowInfo } from '../model/types';
import { WorkflowModel } from '../model/workflowModel';

/**
 * Tree node types
 */
type TreeNode = WorkflowNode | ActionNode | FolderNode | DataPreviewNode;

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
 * Folder node for action output
 */
class FolderNode extends vscode.TreeItem {
    constructor(
        public readonly action: ActionInfo,
        label: string,
        folderPath: string
    ) {
        super(label, vscode.TreeItemCollapsibleState.None);
        this.contextValue = 'agentActions.folder';
        this.iconPath = new vscode.ThemeIcon('folder-opened');
        this.tooltip = folderPath;
        this.command = {
            command: 'agentActions.openFolder',
            title: 'Open Folder',
            arguments: [folderPath],
        };
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
                return workflows[0].actions.map((a) => new ActionNode(a));
            }
            // Multiple workflows: show workflow nodes
            return workflows.map((w) => new WorkflowNode(w));
        }

        // Workflow level: show actions
        if (element instanceof WorkflowNode) {
            return element.workflow.actions.map((a) => new ActionNode(a));
        }

        // Action level: show data preview and folder(s)
        if (element instanceof ActionNode) {
            const action = element.action;
            const nodes: (DataPreviewNode | FolderNode)[] = [];

            // Data preview node (for storage backend data)
            nodes.push(new DataPreviewNode(action));

            // Main output folder
            const outputDir = action.outputDir ?? action.name;
            nodes.push(new FolderNode(
                action,
                `\uD83D\uDCC1 target/${outputDir}/`,
                action.folderPath
            ));

            // Version folders if any
            if (action.versions?.length) {
                for (const versionPath of action.versions) {
                    const versionName = path.basename(versionPath);
                    nodes.push(new FolderNode(
                        action,
                        `\uD83D\uDCC1 ${versionName}/`,
                        versionPath
                    ));
                }
            }

            return nodes;
        }

        return [];
    }
}
