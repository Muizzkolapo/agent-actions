/**
 * CodeLens Provider for Workflow Actions
 *
 * Adds clickable links above action definitions in YAML files.
 *
 * Combines best approaches:
 * - PR #823: Status-aware CodeLens
 * - Data preview (storage backend)
 */

import * as path from 'path';
import * as vscode from 'vscode';
import { WorkflowModel } from '../model/workflowModel';

/** Factory function to avoid regex state sharing issues */
function createActionPattern(): RegExp {
    return /^\s*-\s*name:\s*([^\s#]+)/gm;
}

export class WorkflowCodeLensProvider implements vscode.CodeLensProvider, vscode.Disposable {
    private readonly _onDidChangeCodeLenses = new vscode.EventEmitter<void>();
    readonly onDidChangeCodeLenses = this._onDidChangeCodeLenses.event;
    private readonly modelListener: vscode.Disposable;

    constructor(private readonly model: WorkflowModel) {
        this.modelListener = this.model.onDidChange(() => this._onDidChangeCodeLenses.fire());
    }

    dispose(): void {
        this._onDidChangeCodeLenses.dispose();
        this.modelListener.dispose();
    }

    provideCodeLenses(document: vscode.TextDocument): vscode.CodeLens[] {
        // Check if CodeLens is enabled
        const config = vscode.workspace.getConfiguration('agentActions');
        if (!config.get<boolean>('showCodeLens', true)) {
            return [];
        }

        // Only show in agent_config files
        if (!document.uri.fsPath.includes(`${path.sep}agent_config${path.sep}`)) {
            return [];
        }

        const lenses: vscode.CodeLens[] = [];
        const text = document.getText();
        const actionPattern = createActionPattern();

        let match: RegExpExecArray | null;
        while ((match = actionPattern.exec(text)) !== null) {
            const line = document.positionAt(match.index).line;
            const range = new vscode.Range(line, 0, line, 0);
            const actionName = match[1];

            // Look up action for status info
            const action = this.model.getActionByName(actionName);
            const statusLabel = action ? this.getStatusEmoji(action.status) : '';

            if (action) {
                // Preview output (storage backend)
                lenses.push(
                    new vscode.CodeLens(range, {
                        title: '\uD83D\uDD0E Preview Output',
                        command: 'agentActions.previewData',
                        arguments: [action],
                        tooltip: 'Preview action output from storage backend',
                    })
                );
            }

            // Status indicator (if action found)
            if (action) {
                lenses.push(
                    new vscode.CodeLens(range, {
                        title: `${statusLabel} ${action.status}`,
                        command: 'agentActions.showDAG',
                        arguments: [],
                        tooltip: `Status: ${action.status}. Click to show DAG.`,
                    })
                );
            }
        }

        return lenses;
    }

    private getStatusEmoji(status: string): string {
        switch (status) {
            case 'completed':
                return '\u2705'; // ✅
            case 'running':
                return '\u23F3'; // ⏳
            case 'failed':
                return '\u274C'; // ❌
            case 'skipped':
                return '\u23ED'; // ⏭
            default:
                return '\u23F8'; // ⏸
        }
    }
}
