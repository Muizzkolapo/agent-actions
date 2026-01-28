/**
 * Status Bar Provider
 *
 * Shows workflow progress in the VS Code status bar.
 *
 * Combines best approaches:
 * - PR #820: Clean progress display with running action name
 * - PR #821: Spinning sync icon when running
 * - PR #823: Multi-workflow support, click to focus tree
 */

import * as vscode from 'vscode';
import { WorkflowModel } from '../model/workflowModel';

export class WorkflowStatusBar implements vscode.Disposable {
    private readonly statusBarItem: vscode.StatusBarItem;
    private readonly modelListener: vscode.Disposable;

    constructor(private readonly model: WorkflowModel) {
        this.statusBarItem = vscode.window.createStatusBarItem(
            vscode.StatusBarAlignment.Left,
            100
        );
        this.statusBarItem.command = 'agentActions.showWorkflowTree';
        this.statusBarItem.tooltip = 'Open Agent Actions Workflow Navigator';

        this.modelListener = this.model.onDidChange(() => this.update());
        this.update();
    }

    dispose(): void {
        this.statusBarItem.dispose();
        this.modelListener.dispose();
    }

    private update(): void {
        // Check if status bar is enabled
        const config = vscode.workspace.getConfiguration('agentActions');
        if (!config.get<boolean>('showStatusBar', true)) {
            this.statusBarItem.hide();
            return;
        }

        const workflows = this.model.getWorkflows();
        if (workflows.length === 0) {
            this.statusBarItem.hide();
            return;
        }

        // Use first workflow (most common case)
        const workflow = workflows[0];
        const summary = workflow.statusSummary;

        // Find running action
        const runningAction = workflow.actions.find((a) => a.status === 'running');

        // Build status text
        let icon = '$(graph)';
        let runningLabel = '';

        if (runningAction) {
            icon = '$(sync~spin)';
            runningLabel = ` | [${runningAction.index}] ${runningAction.name}`;
        } else if (summary.failed > 0) {
            icon = '$(error)';
        } else if (summary.completed === summary.total) {
            icon = '$(check-all)';
        }

        this.statusBarItem.text = `${icon} ${workflow.name}: ${summary.completed}/${summary.total}${runningLabel}`;

        // Update tooltip with full status
        this.statusBarItem.tooltip = this.buildTooltip(workflow.name, summary, runningAction?.name);

        this.statusBarItem.show();
    }

    private buildTooltip(
        workflowName: string,
        summary: { completed: number; running: number; failed: number; pending: number; skipped: number; total: number },
        runningActionName?: string
    ): string {
        const lines = [
            `Workflow: ${workflowName}`,
            ``,
            `Progress: ${summary.completed}/${summary.total} completed`,
        ];

        if (runningActionName) {
            lines.push(`Running: ${runningActionName}`);
        }

        if (summary.failed > 0) {
            lines.push(`Failed: ${summary.failed}`);
        }

        lines.push('', 'Click to open Workflow Navigator');

        return lines.join('\n');
    }
}
