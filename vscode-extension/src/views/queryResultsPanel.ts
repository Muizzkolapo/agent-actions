/**
 * Query Results Panel
 *
 * Hosts a React webview that renders preview records using the same DataCard
 * component as the docs UI. The host's only job is to ship records into the
 * webview, react to pagination/copy messages, and keep the panel alive.
 */

import * as vscode from 'vscode';
import { PreviewResult } from '../utils/storageReader';

interface PaginationState {
    actionName: string;
    workflowPath: string;
    workflowName: string;
    limit: number;
    offset: number;
    totalCount: number;
}

interface PreviewPayload {
    records: unknown[];
    totalCount: number;
    nodeName: string;
    files: string[];
    storagePath: string;
    backendType: string;
    workflowName: string;
    workflowPath: string;
    limit: number;
    offset: number;
    /** Set when the storage backend's totalCount disagrees with the actual
     * records length on this page. The backend's `record_count` column can
     * go stale relative to the JSON `data` array; we surface the lie so
     * the user can see when storage is misreporting. */
    countDrift?: { reported: number; actual: number };
}

export class QueryResultsPanel implements vscode.Disposable {
    private panel: vscode.WebviewPanel | undefined;
    private pagination: PaginationState | undefined;
    private webviewReady = false;
    private pendingPayload: PreviewPayload | undefined;
    private readonly disposables: vscode.Disposable[] = [];

    constructor(private readonly extensionUri: vscode.Uri, _context: vscode.ExtensionContext) {}

    dispose(): void {
        this.panel?.dispose();
        this.disposables.forEach((d) => d.dispose());
        this.panel = undefined;
        this.pagination = undefined;
    }

    getPagination(): PaginationState | undefined {
        return this.pagination;
    }

    showResults(
        result: PreviewResult,
        actionName: string,
        workflowPath: string,
        workflowName: string,
        limit: number,
        offset: number
    ): void {
        this.pagination = {
            actionName,
            workflowPath,
            workflowName,
            limit,
            offset,
            totalCount: result.totalCount,
        };

        const panel = this.ensurePanel(actionName);
        const payload = this.buildPayload(result, actionName, workflowPath, workflowName, limit, offset);
        this.send(panel, payload);
    }

    showError(actionName: string, error: string, details?: string): void {
        this.pagination = undefined;
        const panel = this.ensurePanel(actionName);
        panel.webview.html = renderErrorHtml(actionName, error, details);
        this.webviewReady = false;
        this.pendingPayload = undefined;
    }

    private buildPayload(
        result: PreviewResult,
        actionName: string,
        workflowPath: string,
        workflowName: string,
        limit: number,
        offset: number
    ): PreviewPayload {
        // Surface count drift in either direction:
        //   • actual > totalCount → backend under-counted (typical: stale
        //     `record_count` on target_data rows).
        //   • actual < totalCount-offset on a non-final page → backend
        //     truncated; records silently lost.
        // Display-time only; we don't try to repair.
        const actual = offset + result.records.length;
        const expectedRemaining = Math.max(0, result.totalCount - offset);
        const drift =
            actual > result.totalCount ||
            (result.records.length < expectedRemaining && result.records.length < limit)
                ? { reported: result.totalCount, actual }
                : undefined;
        return {
            records: result.records,
            totalCount: result.totalCount,
            nodeName: result.nodeName || actionName,
            files: result.files,
            storagePath: result.storagePath,
            backendType: result.backendType,
            workflowName,
            workflowPath,
            limit,
            offset,
            countDrift: drift,
        };
    }

    private send(panel: vscode.WebviewPanel, payload: PreviewPayload): void {
        if (this.webviewReady) {
            panel.webview.postMessage({ type: 'preview:update', payload });
            this.pendingPayload = undefined;
        } else {
            // Webview hasn't signaled ready — render the shell with payload inlined
            this.pendingPayload = payload;
            panel.webview.html = renderAppHtml(panel.webview, this.extensionUri, payload);
        }
    }

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

        this.panel.onDidDispose(
            () => {
                this.panel = undefined;
                this.pagination = undefined;
                this.webviewReady = false;
                this.pendingPayload = undefined;
            },
            null,
            this.disposables
        );

        this.panel.webview.onDidReceiveMessage(
            (message) => {
                if (!this.panel || !message || typeof message !== 'object') return;
                if (message.type === 'ready') {
                    // Latest pendingPayload wins if showResults fires
                    // multiple times before the webview signals ready.
                    this.webviewReady = true;
                    if (this.pendingPayload) {
                        this.panel.webview.postMessage({
                            type: 'preview:update',
                            payload: this.pendingPayload,
                        });
                        this.pendingPayload = undefined;
                    }
                } else if (message.type === 'paginate') {
                    if (message.direction === 'next') {
                        vscode.commands.executeCommand('agentActions.nextPage');
                    } else if (message.direction === 'previous') {
                        vscode.commands.executeCommand('agentActions.previousPage');
                    }
                    // Unknown directions are dropped silently rather than
                    // defaulting to one or the other.
                } else if (message.type === 'copy' && typeof message.text === 'string') {
                    // Cap clipboard payload to a sane upper bound so a
                    // malformed message can't lock up the system clipboard.
                    const MAX_COPY_BYTES = 4 * 1024 * 1024;
                    const text = message.text.length > MAX_COPY_BYTES
                        ? message.text.slice(0, MAX_COPY_BYTES)
                        : message.text;
                    vscode.env.clipboard.writeText(text);
                }
            },
            null,
            this.disposables
        );

        return this.panel;
    }
}

// ── HTML rendering ────────────────────────────────────────────────────────

function renderAppHtml(
    webview: vscode.Webview,
    extensionUri: vscode.Uri,
    payload: PreviewPayload
): string {
    const nonce = getNonce();
    const scriptUri = webview.asWebviewUri(vscode.Uri.joinPath(extensionUri, 'out', 'webview.js'));
    const styleUri = webview.asWebviewUri(vscode.Uri.joinPath(extensionUri, 'out', 'webview.css'));
    const csp = [
        `default-src 'none'`,
        `style-src ${webview.cspSource} 'unsafe-inline'`,
        `script-src 'nonce-${nonce}'`,
        `img-src ${webview.cspSource} data:`,
        `font-src ${webview.cspSource}`,
    ].join('; ');

    const initialJson = JSON.stringify(payload).replace(/</g, '\\u003c');
    return `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta http-equiv="Content-Security-Policy" content="${csp}">
    <link rel="stylesheet" href="${styleUri}">
    <title>Query Results</title>
</head>
<body>
    <div id="root"></div>
    <script nonce="${nonce}">window.__INITIAL_PREVIEW__ = ${initialJson};</script>
    <script nonce="${nonce}" src="${scriptUri}"></script>
</body>
</html>`;
}

function renderErrorHtml(actionName: string, error: string, details?: string): string {
    const nonce = getNonce();
    return `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-${nonce}';">
    <style>
        body { font-family: var(--vscode-font-family); color: var(--vscode-errorForeground); padding: 24px; }
        h2 { margin-top: 0; font-size: 14px; font-weight: 600; }
        pre { background: var(--vscode-textCodeBlock-background); padding: 12px; border-radius: 6px; white-space: pre-wrap; font-size: 12px; }
    </style>
</head>
<body>
    <h2>${escapeHtml(actionName)} — preview failed</h2>
    <p>${escapeHtml(error)}</p>
    ${details ? `<pre>${escapeHtml(details)}</pre>` : ''}
</body>
</html>`;
}

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

