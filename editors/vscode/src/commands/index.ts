/**
 * Command Registration
 *
 * Centralizes all command registration following PR #822's pattern.
 * Commands combine best approaches from all PRs:
 * - PR #821: openConfig with range reveal
 * - Data preview with storage backend
 */

import * as vscode from 'vscode';
import { ActionInfo } from '../model/types';
import { WorkflowModel } from '../model/workflowModel';
import { DagWebview } from '../views/dagWebview';
import { DataPreviewProvider, openDataPreview, DATA_PREVIEW_SCHEME, createPreviewUri } from '../providers/dataPreviewProvider';

interface CommandContext {
    context: vscode.ExtensionContext;
    model: WorkflowModel;
    dagWebview: DagWebview;
    dataPreviewProvider: DataPreviewProvider;
}

/**
 * Register all workflow navigator commands
 */
export function registerCommands({ context, model, dagWebview, dataPreviewProvider }: CommandContext): void {
    context.subscriptions.push(
        // Open action config and navigate to definition
        vscode.commands.registerCommand('agentActions.openConfig', openConfig),

        // Preview action data from storage backend
        vscode.commands.registerCommand('agentActions.previewData', (action: ActionInfo) =>
            previewData(model, action)
        ),

        // Quick pick to jump to any action
        vscode.commands.registerCommand('agentActions.goToAction', () => goToAction(model)),

        // Show DAG panel
        vscode.commands.registerCommand('agentActions.showDAG', () => dagWebview.show()),

        // Refresh workflow data
        vscode.commands.registerCommand('agentActions.refresh', () => model.refresh()),

        // Focus the workflow tree view
        vscode.commands.registerCommand('agentActions.showWorkflowTree', showWorkflowTree),

        // Pagination commands for data preview
        vscode.commands.registerCommand('agentActions.nextPage', () =>
            navigatePreviewPage(model, 'next')
        ),
        vscode.commands.registerCommand('agentActions.previousPage', () =>
            navigatePreviewPage(model, 'previous')
        ),
    );
}

/**
 * Open config file and navigate to action definition
 *
 * Note: When called from context menu, VS Code passes the TreeItem (ActionNode),
 * not the ActionInfo directly. We handle both cases.
 */
async function openConfig(arg: ActionInfo | { action: ActionInfo }): Promise<void> {
    // Handle both ActionInfo and ActionNode (which has an 'action' property)
    const action: ActionInfo | undefined = 'action' in arg ? arg.action : arg;

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

/**
 * Navigate to next or previous page in data preview
 */
async function navigatePreviewPage(model: WorkflowModel, direction: 'next' | 'previous'): Promise<void> {
    const editor = vscode.window.activeTextEditor;
    if (!editor) {
        vscode.window.showInformationMessage('No active preview document');
        return;
    }

    const uri = editor.document.uri;
    if (uri.scheme !== DATA_PREVIEW_SCHEME) {
        vscode.window.showInformationMessage('This command only works in data preview documents');
        return;
    }

    // Parse current parameters from URI
    const params = new URLSearchParams(uri.query);
    const workflowPath = params.get('workflowPath') || '';
    const workflowName = params.get('workflowName') || '';
    const actionName = uri.path.replace(/^\//, '').replace(/\.json$/, '');
    const limit = parseInt(params.get('limit') || '50', 10);
    const currentOffset = parseInt(params.get('offset') || '0', 10);

    // Calculate new offset
    const newOffset = direction === 'next'
        ? currentOffset + limit
        : Math.max(0, currentOffset - limit);

    if (direction === 'previous' && currentOffset === 0) {
        vscode.window.showInformationMessage('Already at the first page');
        return;
    }

    // Find workflow and action to create new URI
    const workflows = model.getWorkflows();
    const workflow = workflows.find((w) => w.name === workflowName && w.rootPath === workflowPath);
    const action = workflow?.actions.find((a) => a.name === actionName);

    if (!workflow || !action) {
        vscode.window.showErrorMessage(`Could not find workflow or action for pagination`);
        return;
    }

    // Open new preview with updated offset
    await openDataPreview(workflow, action, limit, newOffset);
}

/**
 * Preview action data from storage backend
 *
 * Note: When called from context menu, VS Code passes the TreeItem (ActionNode),
 * not the ActionInfo directly. We handle both cases.
 */
async function previewData(model: WorkflowModel, arg: ActionInfo | { action: ActionInfo }): Promise<void> {
    // Handle both ActionInfo and ActionNode (which has an 'action' property)
    const action: ActionInfo | undefined = 'action' in arg ? arg.action : arg;

    if (!action) {
        vscode.window.showWarningMessage('No action provided.');
        return;
    }

    // Find the workflow this action belongs to
    const workflows = model.getWorkflows();
    const workflow = workflows.find((w) =>
        w.actions.some((a) => a.name === action.name)
    );

    if (!workflow) {
        vscode.window.showErrorMessage(`Could not find workflow for action ${action.name}`);
        return;
    }

    // Open the data preview
    await openDataPreview(workflow, action);
}
