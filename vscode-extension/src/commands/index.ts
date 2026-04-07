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
import { QueryResultsPanel } from '../views/queryResultsPanel';
import { createStorageReader, isPreviewError, StorageReader, type PreviewResult } from '../utils/storageReader';

interface CommandContext {
    context: vscode.ExtensionContext;
    model: WorkflowModel;
    dagWebview: DagWebview;
    queryResultsPanel: QueryResultsPanel;
}

/**
 * Register all workflow navigator commands
 */
export function registerCommands({ context, model, dagWebview, queryResultsPanel }: CommandContext): void {
    context.subscriptions.push(
        // Open action config and navigate to definition
        vscode.commands.registerCommand('agentActions.openConfig', openConfig),

        // Preview action data from storage backend (renders in Query Results panel)
        vscode.commands.registerCommand('agentActions.previewData', (action: ActionInfo) =>
            previewData(model, queryResultsPanel, action)
        ),

        // Quick pick to jump to any action
        vscode.commands.registerCommand('agentActions.goToAction', () => goToAction(model)),

        // Show DAG panel
        vscode.commands.registerCommand('agentActions.showDAG', () => dagWebview.show()),

        // Refresh workflow data
        vscode.commands.registerCommand('agentActions.refresh', () => model.refresh()),

        // Focus the workflow tree view
        vscode.commands.registerCommand('agentActions.showWorkflowTree', showWorkflowTree),

        // Open documentation in browser
        vscode.commands.registerCommand('agentActions.openDocs', openDocs),

        // Open extension settings
        vscode.commands.registerCommand('agentActions.openSettings', openSettings),

        // Pagination commands for data preview
        vscode.commands.registerCommand('agentActions.nextPage', () =>
            navigatePreviewPage(model, queryResultsPanel, 'next')
        ),
        vscode.commands.registerCommand('agentActions.previousPage', () =>
            navigatePreviewPage(model, queryResultsPanel, 'previous')
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
 * Focus the workflow tree view in the Agent Actions sidebar
 */
async function showWorkflowTree(): Promise<void> {
    await vscode.commands.executeCommand('workbench.view.extension.agentActions');
}

/**
 * Open Agent Actions documentation in the browser
 */
async function openDocs(): Promise<void> {
    await vscode.env.openExternal(
        vscode.Uri.parse('https://docs.runagac.com'),
    );
}

/**
 * Open Agent Actions extension settings
 */
async function openSettings(): Promise<void> {
    await vscode.commands.executeCommand('workbench.action.openSettings', 'agentActions');
}

/**
 * Navigate to next or previous page in data preview (Query Results panel)
 */
async function navigatePreviewPage(
    model: WorkflowModel,
    panel: QueryResultsPanel,
    direction: 'next' | 'previous'
): Promise<void> {
    const pagination = panel.getPagination();
    if (!pagination) {
        vscode.window.showInformationMessage('No active preview to paginate');
        return;
    }

    const { actionName, workflowPath, workflowName, limit, offset, totalCount } = pagination;

    // Calculate new offset
    const newOffset = direction === 'next'
        ? offset + limit
        : Math.max(0, offset - limit);

    if (direction === 'previous' && offset === 0) {
        vscode.window.showInformationMessage('Already at the first page');
        return;
    }

    if (direction === 'next' && offset + limit >= totalCount) {
        vscode.window.showInformationMessage('Already at the last page');
        return;
    }

    const reader = createStorageReader(workflowPath, workflowName);
    const result = await reader.previewAction(actionName, limit, newOffset);

    if (!result) {
        panel.showError(actionName, 'Failed to load data from storage backend');
        return;
    }

    if (isPreviewError(result)) {
        panel.showError(actionName, result.error, result.traceback ?? result.stderr);
        return;
    }

    await attachTracesToRecords(reader, actionName, result);
    panel.showResults(result, actionName, workflowPath, workflowName, limit, newOffset);
}

/**
 * Attach prompt traces to preview records by source_guid.
 * Fetches traces from the storage backend and merges them in-place.
 */
async function attachTracesToRecords(
    reader: StorageReader,
    actionName: string,
    result: PreviewResult
): Promise<void> {
    try {
        const traceMap = await reader.previewTraces(actionName);
        if (traceMap.size === 0) return;

        for (const record of result.records) {
            const rec = record as Record<string, unknown>;
            const guid = rec.source_guid;
            if (typeof guid === 'string' && traceMap.has(guid)) {
                rec._trace = traceMap.get(guid);
            }
        }
    } catch {
        // Traces are optional — don't fail the preview if trace fetch fails
    }
}

/**
 * Preview action data from storage backend
 *
 * Fetches data directly via StorageReader and renders it in the
 * Query Results bottom panel as an HTML table.
 *
 * Note: When called from context menu, VS Code passes the TreeItem (ActionNode),
 * not the ActionInfo directly. We handle both cases.
 */
async function previewData(
    model: WorkflowModel,
    panel: QueryResultsPanel,
    arg: ActionInfo | { action: ActionInfo }
): Promise<void> {
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

    const config = vscode.workspace.getConfiguration('agentActions');
    const limit = config.get<number>('previewPageSize', 50);
    const offset = 0;

    const reader = createStorageReader(workflow.rootPath, workflow.name);
    const result = await reader.previewAction(action.name, limit, offset);

    if (!result) {
        panel.showError(action.name, 'Failed to load data from storage backend');
        return;
    }

    if (isPreviewError(result)) {
        panel.showError(action.name, result.error, result.traceback ?? result.stderr);
        return;
    }

    await attachTracesToRecords(reader, action.name, result);
    panel.showResults(result, action.name, workflow.rootPath, workflow.name, limit, offset);
}
