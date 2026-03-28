/**
 * File Decoration Provider
 *
 * Adds badges and colors to action folders in the file explorer.
 *
 * Combines best approaches:
 * - PR #820: Badge with index, tooltip with details
 * - PR #821: Status colors using git decoration colors
 * - PR #823: Chart colors for better visibility
 */

import * as path from 'path';
import * as vscode from 'vscode';
import { ActionStatus } from '../model/types';
import { WorkflowModel } from '../model/workflowModel';

/**
 * Status colors using VS Code theme colors
 */
const STATUS_COLORS: Record<ActionStatus, vscode.ThemeColor> = {
    completed: new vscode.ThemeColor('gitDecoration.addedResourceForeground'),
    running: new vscode.ThemeColor('gitDecoration.modifiedResourceForeground'),
    failed: new vscode.ThemeColor('gitDecoration.deletedResourceForeground'),
    pending: new vscode.ThemeColor('gitDecoration.ignoredResourceForeground'),
    skipped: new vscode.ThemeColor('gitDecoration.untrackedResourceForeground'),
};

export class ActionDecorationProvider implements vscode.FileDecorationProvider, vscode.Disposable {
    private readonly _onDidChangeFileDecorations = new vscode.EventEmitter<vscode.Uri | vscode.Uri[] | undefined>();
    readonly onDidChangeFileDecorations = this._onDidChangeFileDecorations.event;
    private readonly modelListener: vscode.Disposable;

    constructor(private readonly model: WorkflowModel) {
        this.modelListener = this.model.onDidChange(() => this._onDidChangeFileDecorations.fire(undefined));
    }

    dispose(): void {
        this._onDidChangeFileDecorations.dispose();
        this.modelListener.dispose();
    }

    provideFileDecoration(uri: vscode.Uri): vscode.FileDecoration | undefined {
        // Check if decorations are enabled
        const config = vscode.workspace.getConfiguration('agentActions');
        if (!config.get<boolean>('showFileDecorations', true)) {
            return undefined;
        }

        // Only decorate files in agent_io/target
        if (!uri.fsPath.includes(`${path.sep}agent_io${path.sep}target${path.sep}`)) {
            return undefined;
        }

        // Find matching action
        const action = this.model.getActionByPath(uri.fsPath);
        if (!action) {
            return undefined;
        }

        // Build tooltip
        const tooltip = this.buildTooltip(action.index, action.name, action.status, action.recordCount);

        return {
            badge: String(action.index),
            tooltip,
            color: STATUS_COLORS[action.status] ?? STATUS_COLORS.pending,
        };
    }

    private buildTooltip(index: number, name: string, status: ActionStatus, recordCount?: number | null): string {
        const lines = [
            `Action #${index}: ${name}`,
            `Status: ${status}`,
        ];

        if (recordCount != null) {
            lines.push(`Records: ${recordCount.toLocaleString()}`);
        }

        return lines.join('\n');
    }
}
