/**
 * Query Results Panel
 *
 * Displays action data as an HTML table in a webview editor tab.
 * Uses WebviewPanel (same proven pattern as DagWebview).
 */

import * as vscode from 'vscode';
import { PreviewResult } from '../utils/storageReader';

/** Pagination state persisted across renders. */
interface PaginationState {
    actionName: string;
    workflowPath: string;
    workflowName: string;
    limit: number;
    offset: number;
    totalCount: number;
}

type ViewMode = 'table' | 'json';

export class QueryResultsPanel implements vscode.Disposable {
    private panel: vscode.WebviewPanel | undefined;
    private pagination: PaginationState | undefined;
    private viewMode: ViewMode;
    private lastResult: PreviewResult | undefined;
    private readonly disposables: vscode.Disposable[] = [];
    private readonly workspaceState: vscode.Memento;

    constructor(
        private readonly extensionUri: vscode.Uri,
        context: vscode.ExtensionContext
    ) {
        this.workspaceState = context.workspaceState;
        // Load saved view mode preference, default to 'table'
        this.viewMode = this.workspaceState.get<ViewMode>('queryResultsViewMode', 'table');
    }

    dispose(): void {
        this.panel?.dispose();
        this.disposables.forEach((d) => d.dispose());
        // Clear all state to prevent memory leaks
        this.panel = undefined;
        this.pagination = undefined;
        this.lastResult = undefined;
    }

    /** Get current pagination state (used by pagination commands). */
    getPagination(): PaginationState | undefined {
        return this.pagination;
    }

    /** Display data results as a table. */
    showResults(
        result: PreviewResult,
        actionName: string,
        workflowPath: string,
        workflowName: string,
        limit: number,
        offset: number
    ): void {
        this.lastResult = result;
        this.pagination = {
            actionName,
            workflowPath,
            workflowName,
            limit,
            offset,
            totalCount: result.totalCount,
        };

        const webview = this.ensurePanel(actionName).webview;

        if (result.records.length === 0) {
            this.renderEmpty(webview, actionName);
            return;
        }

        this.render(webview, result, actionName, limit, offset);
    }

    /** Refresh the current view after toggling modes. */
    private refresh(): void {
        if (!this.panel || !this.lastResult || !this.pagination) {
            return;
        }
        const { actionName, limit, offset } = this.pagination;
        this.render(this.panel.webview, this.lastResult, actionName, limit, offset);
    }

    /** Render based on current view mode. */
    private render(
        webview: vscode.Webview,
        result: PreviewResult,
        actionName: string,
        limit: number,
        offset: number
    ): void {
        if (this.viewMode === 'table') {
            this.renderTable(webview, result, actionName, limit, offset);
        } else {
            this.renderJSON(webview, result, actionName, limit, offset);
        }
    }

    /** Display an error message in the panel. */
    showError(actionName: string, error: string, details?: string): void {
        this.pagination = undefined;
        const webview = this.ensurePanel(actionName).webview;
        this.renderError(webview, actionName, error, details);
    }

    /**
     * Create or reveal the webview panel.
     */
    private ensurePanel(actionName: string): vscode.WebviewPanel {
        if (this.panel) {
            this.panel.title = `Query Results: ${actionName}`;
            this.panel.reveal(vscode.ViewColumn.Beside, true);
            return this.panel;
        }

        this.panel = vscode.window.createWebviewPanel(
            'agentActionsQueryResults',
            `Query Results: ${actionName}`,
            { viewColumn: vscode.ViewColumn.Beside, preserveFocus: true },
            {
                enableScripts: true,
                retainContextWhenHidden: true,
                localResourceRoots: [this.extensionUri],
            }
        );

        this.panel.onDidDispose(() => {
            this.panel = undefined;
            this.pagination = undefined;
        }, null, this.disposables);

        // Handle messages from webview (pagination buttons, view toggle)
        this.panel.webview.onDidReceiveMessage(
            (message) => {
                if (message.type === 'paginate') {
                    vscode.commands.executeCommand(
                        message.direction === 'next'
                            ? 'agentActions.nextPage'
                            : 'agentActions.previousPage'
                    );
                } else if (message.type === 'toggleView') {
                    // Validate view mode before setting
                    if (message.mode === 'table' || message.mode === 'json') {
                        this.viewMode = message.mode;
                        // Persist view mode preference
                        this.workspaceState.update('queryResultsViewMode', this.viewMode);
                        this.refresh();
                    }
                }
            },
            null,
            this.disposables
        );

        return this.panel;
    }

    // ------------------------------------------------------------------ //
    //  HTML rendering
    // ------------------------------------------------------------------ //

    private renderTable(
        webview: vscode.Webview,
        result: PreviewResult,
        actionName: string,
        limit: number,
        offset: number
    ): void {
        const nonce = getNonce();

        // Defensive check: ensure records array is not empty
        const firstRecord = result.records[0];
        if (!firstRecord || typeof firstRecord !== 'object') {
            this.renderEmpty(webview, actionName);
            return;
        }

        // Extract column names from first record
        const columns = Object.keys(firstRecord);
        const colCount = columns.length;
        const from = offset + 1;
        const to = Math.min(offset + limit, result.totalCount);
        const hasPrev = offset > 0;
        const hasNext = offset + limit < result.totalCount;

        const headerCells = columns
            .map((col) => `<th role="columnheader">${escapeHtml(col)}</th>`)
            .join('');

        const bodyRows = result.records
            .map((record) => {
                // Type already validated in defensive check above
                const rec = record as Record<string, unknown>;
                const cells = columns
                    .map((col) => `<td role="gridcell">${escapeHtml(formatCell(rec[col]))}</td>`)
                    .join('');
                return `<tr role="row">${cells}</tr>`;
            })
            .join('');

        webview.html = `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-${nonce}';">
    <title>Query Results</title>
    <style>${tableStyles()}</style>
</head>
<body>
    <div class="toolbar">
        <span class="action-name">${escapeHtml(actionName)}</span>
        <span class="meta">${colCount} ${colCount === 1 ? 'column' : 'columns'} &middot; rows ${from}&ndash;${to} of ${result.totalCount}</span>
        <span class="meta secondary">${escapeHtml(result.backendType)}</span>
        <span class="spacer"></span>
        <button class="view-toggle" id="tableBtn" disabled aria-pressed="true" aria-label="Table view">Table</button>
        <button class="view-toggle" id="jsonBtn" aria-pressed="false" aria-label="JSON view">JSON</button>
        <button class="nav-btn" id="prevBtn" ${hasPrev ? '' : 'disabled'} ${hasPrev ? '' : 'aria-disabled="true"'} title="Previous page" aria-label="Go to previous page">&larr; Prev</button>
        <button class="nav-btn" id="nextBtn" ${hasNext ? '' : 'disabled'} ${hasNext ? '' : 'aria-disabled="true"'} title="Next page" aria-label="Go to next page">Next &rarr;</button>
    </div>
    <div class="table-wrap">
        <table role="grid" aria-label="Query results for ${escapeHtml(actionName)}">
            <thead><tr role="row">${headerCells}</tr></thead>
            <tbody>${bodyRows}</tbody>
        </table>
    </div>
    <script nonce="${nonce}">
        const vscode = acquireVsCodeApi();
        document.getElementById('prevBtn').addEventListener('click', () => {
            vscode.postMessage({ type: 'paginate', direction: 'previous' });
        });
        document.getElementById('nextBtn').addEventListener('click', () => {
            vscode.postMessage({ type: 'paginate', direction: 'next' });
        });
        document.getElementById('tableBtn').addEventListener('click', () => {
            vscode.postMessage({ type: 'toggleView', mode: 'table' });
        });
        document.getElementById('jsonBtn').addEventListener('click', () => {
            vscode.postMessage({ type: 'toggleView', mode: 'json' });
        });
    </script>
</body>
</html>`;
    }

    private renderJSON(
        webview: vscode.Webview,
        result: PreviewResult,
        actionName: string,
        limit: number,
        offset: number
    ): void {
        const nonce = getNonce();
        const from = offset + 1;
        const to = Math.min(offset + limit, result.totalCount);
        const hasPrev = offset > 0;
        const hasNext = offset + limit < result.totalCount;

        const jsonData = {
            _metadata: {
                action: actionName,
                storage: {
                    type: result.backendType,
                    path: result.storagePath,
                },
                pagination: {
                    from,
                    to,
                    total: result.totalCount,
                },
                files: result.files,
            },
            records: result.records,
        };

        const jsonString = JSON.stringify(jsonData, null, 2);

        webview.html = `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-${nonce}';">
    <title>Query Results</title>
    <style>${tableStyles()}</style>
</head>
<body>
    <div class="toolbar">
        <span class="action-name">${escapeHtml(actionName)}</span>
        <span class="meta">rows ${from}&ndash;${to} of ${result.totalCount}</span>
        <span class="meta secondary">${escapeHtml(result.backendType)}</span>
        <span class="spacer"></span>
        <button class="view-toggle" id="tableBtn" aria-pressed="false" aria-label="Table view">Table</button>
        <button class="view-toggle" id="jsonBtn" disabled aria-pressed="true" aria-label="JSON view">JSON</button>
        <button class="nav-btn" id="prevBtn" ${hasPrev ? '' : 'disabled'} ${hasPrev ? '' : 'aria-disabled="true"'} title="Previous page" aria-label="Go to previous page">&larr; Prev</button>
        <button class="nav-btn" id="nextBtn" ${hasNext ? '' : 'disabled'} ${hasNext ? '' : 'aria-disabled="true"'} title="Next page" aria-label="Go to next page">Next &rarr;</button>
    </div>
    <div class="json-wrap">
        <pre role="region" aria-label="JSON formatted data"><code>${escapeHtml(jsonString)}</code></pre>
    </div>
    <script nonce="${nonce}">
        const vscode = acquireVsCodeApi();
        document.getElementById('prevBtn').addEventListener('click', () => {
            vscode.postMessage({ type: 'paginate', direction: 'previous' });
        });
        document.getElementById('nextBtn').addEventListener('click', () => {
            vscode.postMessage({ type: 'paginate', direction: 'next' });
        });
        document.getElementById('tableBtn').addEventListener('click', () => {
            vscode.postMessage({ type: 'toggleView', mode: 'table' });
        });
        document.getElementById('jsonBtn').addEventListener('click', () => {
            vscode.postMessage({ type: 'toggleView', mode: 'json' });
        });
    </script>
</body>
</html>`;
    }

    private renderError(
        webview: vscode.Webview,
        actionName: string,
        error: string,
        details?: string
    ): void {
        const nonce = getNonce();

        webview.html = `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-${nonce}';">
    <style>${tableStyles()}</style>
</head>
<body>
    <div class="toolbar">
        <span class="action-name">${escapeHtml(actionName)}</span>
        <span class="meta error-label">Error</span>
    </div>
    <div class="message error">
        <p>${escapeHtml(error)}</p>
        ${details ? `<pre>${escapeHtml(details)}</pre>` : ''}
    </div>
</body>
</html>`;
    }

    private renderEmpty(webview: vscode.Webview, actionName?: string): void {
        const nonce = getNonce();

        const title = actionName
            ? `No data for <strong>${escapeHtml(actionName)}</strong>.`
            : 'Click <strong>Preview Data</strong> on an action to view results here.';

        webview.html = `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-${nonce}';">
    <style>${tableStyles()}</style>
</head>
<body>
    <div class="message empty">${title}</div>
</body>
</html>`;
    }
}

// ------------------------------------------------------------------ //
//  Helpers
// ------------------------------------------------------------------ //

function getNonce(): string {
    let text = '';
    const possible = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
    for (let i = 0; i < 32; i++) {
        text += possible.charAt(Math.floor(Math.random() * possible.length));
    }
    return text;
}

function escapeHtml(value: string): string {
    return value
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

function formatCell(value: unknown): string {
    if (value === null || value === undefined) {
        return '';
    }
    if (typeof value === 'object') {
        return JSON.stringify(value);
    }
    return String(value);
}

/** Shared CSS for all panel states. */
function tableStyles(): string {
    return `
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: var(--vscode-font-family, sans-serif);
            font-size: var(--vscode-font-size, 13px);
            color: var(--vscode-foreground, #ccc);
            background: var(--vscode-editor-background, #1e1e1e);
            height: 100vh;
            display: flex;
            flex-direction: column;
        }

        /* Toolbar */
        .toolbar {
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 6px 12px;
            border-bottom: 1px solid var(--vscode-panel-border, #444);
            background: var(--vscode-editor-background, #1e1e1e);
            flex-shrink: 0;
        }
        .action-name {
            font-weight: 600;
        }
        .meta {
            opacity: 0.7;
            font-size: 0.9em;
        }
        .meta.secondary {
            opacity: 0.5;
        }
        .meta.error-label {
            color: var(--vscode-errorForeground, #f44);
            opacity: 1;
        }
        .spacer { flex: 1; }
        .view-toggle {
            padding: 2px 10px;
            font-size: 0.85em;
            border: 1px solid var(--vscode-panel-border, #555);
            background: var(--vscode-button-secondaryBackground, #333);
            color: var(--vscode-button-secondaryForeground, #ccc);
            cursor: pointer;
            border-radius: 0;
        }
        .view-toggle:first-of-type {
            border-top-left-radius: 3px;
            border-bottom-left-radius: 3px;
        }
        .view-toggle:last-of-type {
            border-top-right-radius: 3px;
            border-bottom-right-radius: 3px;
            margin-right: 10px;
        }
        .view-toggle:hover:not(:disabled) {
            background: var(--vscode-button-secondaryHoverBackground, #444);
        }
        .view-toggle:disabled {
            background: var(--vscode-button-background, #007acc);
            color: var(--vscode-button-foreground, #fff);
            cursor: default;
        }
        .nav-btn {
            padding: 2px 8px;
            font-size: 0.85em;
            border: 1px solid var(--vscode-button-border, var(--vscode-panel-border, #555));
            border-radius: 3px;
            background: var(--vscode-button-secondaryBackground, #333);
            color: var(--vscode-button-secondaryForeground, #ccc);
            cursor: pointer;
        }
        .nav-btn:hover:not(:disabled) {
            background: var(--vscode-button-secondaryHoverBackground, #444);
        }
        .nav-btn:disabled {
            opacity: 0.4;
            cursor: default;
        }

        /* Table */
        .table-wrap {
            flex: 1;
            overflow: auto;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 0.92em;
        }
        thead {
            position: sticky;
            top: 0;
            z-index: 1;
        }
        th {
            background: var(--vscode-editorGroupHeader-tabsBackground, #252526);
            color: var(--vscode-foreground, #ccc);
            font-weight: 600;
            text-align: left;
            padding: 5px 10px;
            border-bottom: 1px solid var(--vscode-panel-border, #444);
            white-space: nowrap;
        }
        td {
            padding: 4px 10px;
            border-bottom: 1px solid var(--vscode-panel-border, rgba(255,255,255,0.06));
            white-space: nowrap;
            max-width: 400px;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        tr:hover td {
            background: var(--vscode-list-hoverBackground, rgba(255,255,255,0.04));
        }

        /* JSON view */
        .json-wrap {
            flex: 1;
            overflow: auto;
            padding: 12px;
        }
        .json-wrap pre {
            margin: 0;
            font-family: var(--vscode-editor-font-family, 'Menlo', 'Monaco', 'Courier New', monospace);
            font-size: 0.9em;
            line-height: 1.4;
        }
        .json-wrap code {
            color: var(--vscode-editor-foreground, #ccc);
        }

        /* Messages (empty / error) */
        .message {
            padding: 24px;
            text-align: center;
            opacity: 0.7;
        }
        .message.error {
            color: var(--vscode-errorForeground, #f44);
            opacity: 1;
            text-align: left;
        }
        .message.error pre {
            margin-top: 12px;
            padding: 10px;
            background: var(--vscode-textCodeBlock-background, #1a1a1a);
            border-radius: 4px;
            overflow-x: auto;
            font-size: 0.85em;
            white-space: pre-wrap;
            max-height: 300px;
            overflow-y: auto;
        }
    `;
}
