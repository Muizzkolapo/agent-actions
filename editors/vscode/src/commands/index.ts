/**
 * Command Registration
 *
 * Centralizes all command registration following PR #822's pattern.
 * Commands combine best approaches from all PRs:
 * - PR #820: openFolder with URI handling
 * - PR #821: openConfig with range reveal
 * - PR #823: viewOutput with smart file opening
 */

import * as vscode from 'vscode';
import { ActionInfo } from '../model/types';
import { WorkflowModel } from '../model/workflowModel';
import { DagWebview } from '../views/dagWebview';

interface CommandContext {
    context: vscode.ExtensionContext;
    model: WorkflowModel;
    dagWebview: DagWebview;
}

/**
 * Register all workflow navigator commands
 */
export function registerCommands({ context, model, dagWebview }: CommandContext): void {
    context.subscriptions.push(
        // Open action folder in VS Code Explorer sidebar
        vscode.commands.registerCommand('agentActions.openFolder', openFolder),

        // Open action config and navigate to definition
        vscode.commands.registerCommand('agentActions.openConfig', openConfig),

        // View action output (opens first file in output folder)
        vscode.commands.registerCommand('agentActions.viewOutput', viewOutput),

        // Quick pick to jump to any action
        vscode.commands.registerCommand('agentActions.goToAction', () => goToAction(model)),

        // Show DAG panel
        vscode.commands.registerCommand('agentActions.showDAG', () => dagWebview.show()),

        // Refresh workflow data
        vscode.commands.registerCommand('agentActions.refresh', () => model.refresh()),

        // Focus the workflow tree view
        vscode.commands.registerCommand('agentActions.showWorkflowTree', showWorkflowTree),
    );
}

/**
 * Open folder in VS Code's Explorer sidebar (not system file manager)
 */
async function openFolder(folderPath: string): Promise<void> {
    if (!folderPath) {
        vscode.window.showWarningMessage('No folder path provided.');
        return;
    }

    const uri = vscode.Uri.file(folderPath);

    try {
        // Check if folder exists
        await vscode.workspace.fs.stat(uri);
        // Reveal in VS Code's Explorer sidebar
        await vscode.commands.executeCommand('revealInExplorer', uri);
    } catch {
        // Folder doesn't exist yet
        vscode.window.showInformationMessage(`Folder not yet created: ${folderPath}`);
    }
}

/**
 * Open config file and navigate to action definition
 */
async function openConfig(action: ActionInfo): Promise<void> {
    if (!action?.configLocation) {
        vscode.window.showWarningMessage('Action configuration location not available.');
        return;
    }

    const document = await vscode.workspace.openTextDocument(action.configLocation.uri);
    const editor = await vscode.window.showTextDocument(document, { preview: false });

    const position = action.configLocation.range.start;
    const range = new vscode.Range(position, position);

    editor.revealRange(range, vscode.TextEditorRevealType.InCenter);
    editor.selection = new vscode.Selection(position, position);
}

/**
 * View action output - opens first file in output folder
 */
async function viewOutput(action: ActionInfo): Promise<void> {
    if (!action) {
        vscode.window.showWarningMessage('No action provided.');
        return;
    }

    const uri = vscode.Uri.file(action.folderPath);

    try {
        const entries = await vscode.workspace.fs.readDirectory(uri);

        // Find first file (not directory)
        const fileEntry = entries.find(([, type]) => type === vscode.FileType.File);

        if (fileEntry) {
            const fileUri = vscode.Uri.joinPath(uri, fileEntry[0]);
            const document = await vscode.workspace.openTextDocument(fileUri);
            await vscode.window.showTextDocument(document, { preview: true });
            return;
        }

        // No files found, reveal folder in VS Code Explorer
        await vscode.commands.executeCommand('revealInExplorer', uri);
    } catch {
        // Folder doesn't exist
        vscode.window.showInformationMessage(
            `Output folder not yet created: ${action.folderPath}`
        );
    }
}

/**
 * Quick pick to jump to any action
 */
async function goToAction(model: WorkflowModel): Promise<void> {
    const workflows = model.getWorkflows();

    if (workflows.length === 0) {
        vscode.window.showInformationMessage('No Agent Actions workflows detected.');
        return;
    }

    // Build quick pick items
    const items = workflows.flatMap((workflow) =>
        workflow.actions.map((action) => ({
            label: `[${action.index}] ${action.name}`,
            description: `${action.status} | ${workflow.name}`,
            detail: action.dependencies.length
                ? `Dependencies: ${action.dependencies.join(', ')}`
                : 'No dependencies (source action)',
            action,
        }))
    );

    const selected = await vscode.window.showQuickPick(items, {
        title: 'Go to Action',
        placeHolder: 'Select an action to navigate to',
        matchOnDescription: true,
        matchOnDetail: true,
    });

    if (selected) {
        await openConfig(selected.action);
    }
}

/**
 * Focus the workflow tree view in explorer
 */
async function showWorkflowTree(): Promise<void> {
    await vscode.commands.executeCommand('workbench.view.explorer');
    await vscode.commands.executeCommand('agentActionsWorkflow.focus');
}
