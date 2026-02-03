/**
 * Data Preview Provider
 *
 * Provides a virtual document view for previewing action output data
 * from any storage backend (SQLite, S3, DuckDB, etc.)
 */

import * as vscode from 'vscode';
import { createStorageReader, PreviewError, PreviewResult } from '../utils/storageReader';
import { ActionInfo, WorkflowInfo } from '../model/types';

/**
 * URI scheme for data preview documents
 */
export const DATA_PREVIEW_SCHEME = 'agent-actions-data';

/**
 * Data Preview Provider
 *
 * Implements TextDocumentContentProvider to show data as virtual documents.
 */
export class DataPreviewProvider implements vscode.TextDocumentContentProvider, vscode.Disposable {
    private readonly _onDidChange = new vscode.EventEmitter<vscode.Uri>();
    readonly onDidChange = this._onDidChange.event;

    private readonly cache = new Map<string, { content: string; timestamp: number }>();

    private get cacheTTL(): number {
        return vscode.workspace.getConfiguration('agentActions').get<number>('previewCacheTTL', 5000);
    }

    dispose(): void {
        this._onDidChange.dispose();
        this.cache.clear();
    }

    /**
     * Provide document content for a data preview URI
     */
    async provideTextDocumentContent(uri: vscode.Uri): Promise<string> {
        // Parse URI: agent-actions-data:/workflow/action?limit=50&offset=0
        const params = new URLSearchParams(uri.query);
        const workflowPath = params.get('workflowPath') || '';
        const workflowName = params.get('workflowName') || '';
        const actionName = uri.path.replace(/^\//, '').replace(/\.json$/, '');
        const limit = parseInt(params.get('limit') || '50', 10);
        const offset = parseInt(params.get('offset') || '0', 10);

        // Check cache
        const cacheKey = uri.toString();
        const cached = this.cache.get(cacheKey);
        if (cached && Date.now() - cached.timestamp < this.cacheTTL) {
            return cached.content;
        }

        // Fetch data from storage backend
        const reader = createStorageReader(workflowPath, workflowName);
        const result = await reader.previewAction(actionName, limit, offset);

        if (!result) {
            return this.formatError(actionName, 'Failed to load data from storage backend');
        }

        if (this.isPreviewError(result)) {
            return this.formatError(actionName, result.error, result.traceback ?? result.stderr);
        }

        if (result.records.length === 0) {
            return this.formatEmpty(actionName);
        }

        const content = this.formatPreviewResult(result, limit, offset);

        // Cache the result
        this.cache.set(cacheKey, { content, timestamp: Date.now() });

        return content;
    }

    /**
     * Format preview result as readable JSON with embedded metadata
     */
    private formatPreviewResult(result: PreviewResult, limit: number, offset: number): string {
        const output = {
            _metadata: {
                action: result.nodeName,
                storage: {
                    type: result.backendType,
                    path: result.storagePath,
                },
                pagination: {
                    from: offset + 1,
                    to: Math.min(offset + limit, result.totalCount),
                    total: result.totalCount,
                    hint: 'Use Ctrl+Shift+P > "Agent Actions: Next Page" to see more records',
                },
                files: result.files,
            },
            records: result.records,
        };

        return JSON.stringify(output, null, 2);
    }

    /**
     * Format error message as JSON
     */
    private formatError(actionName: string, error: string, details?: string): string {
        const output = {
            _metadata: {
                action: actionName,
                error: true,
            },
            error: {
                message: error,
                details: details || null,
                possibleCauses: [
                    'No data has been generated yet (run the workflow first)',
                    'Python interpreter not found (set agentActions.pythonPath)',
                    'agent_actions module not found (set agentActions.modulePath)',
                    'Database file is missing or corrupted',
                ],
            },
            records: [],
        };

        return JSON.stringify(output, null, 2);
    }

    /**
     * Format empty result as JSON
     */
    private formatEmpty(actionName: string): string {
        const output = {
            _metadata: {
                action: actionName,
                empty: true,
                hint: 'This action has not generated any output yet. Run the workflow to generate data.',
            },
            records: [],
        };

        return JSON.stringify(output, null, 2);
    }

    private isPreviewError(result: PreviewResult | PreviewError): result is PreviewError {
        return 'error' in result;
    }

    /**
     * Refresh a preview document
     */
    refresh(uri: vscode.Uri): void {
        this.cache.delete(uri.toString());
        this._onDidChange.fire(uri);
    }

    /**
     * Clear the cache
     */
    clearCache(): void {
        this.cache.clear();
    }
}

/**
 * Create a preview URI for an action
 */
export function createPreviewUri(
    workflow: WorkflowInfo,
    action: ActionInfo,
    limit: number = 50,
    offset: number = 0
): vscode.Uri {
    const query = new URLSearchParams({
        workflowPath: workflow.rootPath,
        workflowName: workflow.name,
        limit: limit.toString(),
        offset: offset.toString(),
    });

    return vscode.Uri.parse(
        `${DATA_PREVIEW_SCHEME}:/${action.name}.json?${query.toString()}`
    );
}

/**
 * Open a data preview for an action
 */
export async function openDataPreview(
    workflow: WorkflowInfo,
    action: ActionInfo,
    limit: number = 50,
    offset: number = 0
): Promise<void> {
    const uri = createPreviewUri(workflow, action, limit, offset);

    try {
        const doc = await vscode.workspace.openTextDocument(uri);
        await vscode.window.showTextDocument(doc, {
            preview: true,
            viewColumn: vscode.ViewColumn.Beside,
        });
    } catch (error) {
        vscode.window.showErrorMessage(
            `Failed to preview data for ${action.name}: ${error}`
        );
    }
}
