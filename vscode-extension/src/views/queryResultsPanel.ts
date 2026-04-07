/**
 * Query Results Panel
 *
 * Displays action data in a webview with three view modes:
 * - Cards (default): classified fields with identity header, content body, metadata drawer
 * - Table: traditional grid view
 * - JSON: raw formatted output
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

type ViewMode = 'card' | 'table' | 'json';

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
        this.viewMode = this.workspaceState.get<ViewMode>('queryResultsViewMode', 'card');
    }

    dispose(): void {
        this.panel?.dispose();
        this.disposables.forEach((d) => d.dispose());
        this.panel = undefined;
        this.pagination = undefined;
        this.lastResult = undefined;
    }

    /** Get current pagination state (used by pagination commands). */
    getPagination(): PaginationState | undefined {
        return this.pagination;
    }

    /** Display data results. */
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

    private refresh(): void {
        if (!this.panel || !this.lastResult || !this.pagination) {
            return;
        }
        const { actionName, limit, offset } = this.pagination;
        this.render(this.panel.webview, this.lastResult, actionName, limit, offset);
    }

    private render(
        webview: vscode.Webview,
        result: PreviewResult,
        actionName: string,
        limit: number,
        offset: number
    ): void {
        if (this.viewMode === 'card') {
            this.renderCards(webview, result, actionName, limit, offset);
        } else if (this.viewMode === 'table') {
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

        this.panel.webview.onDidReceiveMessage(
            (message) => {
                if (message.type === 'paginate') {
                    vscode.commands.executeCommand(
                        message.direction === 'next'
                            ? 'agentActions.nextPage'
                            : 'agentActions.previousPage'
                    );
                } else if (message.type === 'toggleView') {
                    if (message.mode === 'card' || message.mode === 'table' || message.mode === 'json') {
                        this.viewMode = message.mode;
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

    // ── Card view ─────────────────────────────────────────────────────

    private renderCards(
        webview: vscode.Webview,
        result: PreviewResult,
        actionName: string,
        limit: number,
        offset: number
    ): void {
        const nonce = getNonce();
        const { from, to, hasPrev, hasNext } = paginationVars(offset, limit, result.totalCount);
        const recordsJson = JSON.stringify(result.records);

        const toolbar = buildToolbar({
            actionName, meta: `rows ${from}&ndash;${to} of ${result.totalCount}`,
            backendType: result.backendType, activeMode: 'card', hasPrev, hasNext,
        });

        const cardScript = `
        const vscode = acquireVsCodeApi();
        const records = JSON.parse(${JSON.stringify(recordsJson)});
        const offset = ${offset};

        // ── Field classification (ported from data-card-utils.ts) ──
        const METADATA_KEYS = new Set([
            'source_guid','lineage','node_id','metadata','target_id',
            'parent_target_id','root_target_id','chunk_info',
            '_recovery','_unprocessed','_file','_trace'
        ]);
        const IDENTITY_KEYS = new Set(['source_guid','target_id']);
        const LONG_FORM_HINTS = new Set([
            'reasoning','classification_reasoning','description',
            'summary','explanation','rationale','comment','notes'
        ]);

        function classifyField(key) {
            if (IDENTITY_KEYS.has(key)) return 'identity';
            if (METADATA_KEYS.has(key)) return 'metadata';
            return 'content';
        }
        function isLongForm(key) {
            const lower = key.toLowerCase();
            for (const hint of LONG_FORM_HINTS) {
                if (lower === hint || lower.endsWith('_' + hint)) return true;
            }
            return false;
        }
        function isShort(value) {
            if (typeof value !== 'string') return typeof value !== 'object' || value === null;
            return value.length <= 80;
        }
        function isInlineArray(value) {
            if (!Array.isArray(value)) return false;
            if (value.length === 0 || value.length > 3) return false;
            return value.every(v => typeof v === 'string' || typeof v === 'number');
        }
        function humanize(key) {
            return key.replace(/_/g, ' ').replace(/([a-z])([A-Z])/g, '$1 $2').replace(/\\b\\w/g, c => c.toUpperCase());
        }
        function esc(str) {
            return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
        }
        function fmt(value, max) {
            if (value === null || value === undefined) return 'null';
            if (typeof value === 'boolean') return String(value);
            if (typeof value === 'number') return value.toLocaleString();
            if (typeof value === 'object') {
                const s = JSON.stringify(value);
                return max > 0 && s.length > max ? s.slice(0, max) + '\\u2026' : s;
            }
            const s = String(value);
            return max > 0 && s.length > max ? s.slice(0, max) + '\\u2026' : s;
        }

        // ── Render cards ──
        function renderValue(key, value) {
            if (value === null || value === undefined) {
                return '<span class="val-null">null</span>';
            }
            if (typeof value === 'boolean') {
                return '<span class="badge ' + (value ? 'badge-true' : 'badge-false') + '">' + String(value) + '</span>';
            }
            if (typeof value === 'number') {
                return '<span class="val-number">' + value.toLocaleString() + '</span>';
            }
            if (isInlineArray(value)) {
                return value.map(v => '<span class="pill">' + esc(String(v)) + '</span>').join(' ');
            }
            if (typeof value === 'object') {
                return '<pre class="code-block">' + esc(JSON.stringify(value, null, 2)) + '</pre>';
            }
            const str = String(value);
            if (isLongForm(key) && str.length > 80) {
                return '<p class="prose clamped">' + esc(str) + '</p>'
                    + '<button class="expand-btn">Show more</button>';
            }
            if (str.length > 120) {
                return '<p class="prose clamped">' + esc(str) + '</p>'
                    + '<button class="expand-btn">Show more</button>';
            }
            return '<span class="val-string">' + esc(str) + '</span>';
        }

        function buildCard(record, index) {
            const identity = [];
            const content = [];
            const meta = [];

            // Unwrap content wrapper if present
            let displayRecord = record;
            if (record.content && typeof record.content === 'object' && !Array.isArray(record.content)) {
                displayRecord = record.content;
            }

            for (const [key, value] of Object.entries(record)) {
                const role = classifyField(key);
                if (role === 'identity') identity.push({ key, value });
                else if (role === 'metadata') meta.push({ key, value });
            }
            for (const [key, value] of Object.entries(displayRecord)) {
                if (classifyField(key) === 'content') {
                    content.push({ key, value });
                }
            }

            // Header
            let header = '<span class="card-index">#' + (index + 1) + '</span>';
            for (const f of identity) {
                const truncated = fmt(f.value, 24);
                header += ' <span class="card-id" title="' + esc(fmt(f.value, 0)) + '">' + esc(truncated) + '</span>';
            }

            // Body
            let body = '';
            if (content.length === 0) {
                body = '<div class="card-empty">No content fields</div>';
            } else {
                for (const f of content) {
                    const short = isShort(f.value) && !isLongForm(f.key);
                    if (short) {
                        body += '<div class="field-row field-inline">'
                            + '<span class="field-label">' + esc(humanize(f.key)) + '</span>'
                            + '<div class="field-value">' + renderValue(f.key, f.value) + '</div>'
                            + '</div>';
                    } else {
                        body += '<div class="field-row field-block">'
                            + '<span class="field-label">' + esc(humanize(f.key)) + '</span>'
                            + '<div class="field-value">' + renderValue(f.key, f.value) + '</div>'
                            + '</div>';
                    }
                }
            }

            // Metadata drawer
            let drawer = '';
            if (meta.length > 0) {
                let metaRows = '';
                for (const f of meta) {
                    metaRows += '<div class="meta-row">'
                        + '<span class="meta-key">' + esc(humanize(f.key)) + '</span>'
                        + '<span class="meta-val">' + esc(fmt(f.value, 120)) + '</span>'
                        + '</div>';
                }
                drawer = '<div class="card-meta">'
                    + '<button class="meta-toggle">&#9656; Metadata (' + meta.length + ' fields)</button>'
                    + '<div class="meta-content" hidden>' + metaRows + '</div>'
                    + '</div>';
            }

            // Prompt Trace drawer
            var traceDrawer = '';
            var trace = record._trace;
            if (trace && typeof trace === 'object' && !Array.isArray(trace)) {
                var modelLabel = esc(String(trace.model_name || 'unknown'));
                var modeLabel = esc(String(trace.run_mode || 'online'));
                var batchClass = modeLabel === 'batch' ? ' batch' : '';
                var promptLen = typeof trace.prompt_length === 'number' ? trace.prompt_length.toLocaleString() + ' chars' : '';
                var responseLen = typeof trace.response_length === 'number' ? trace.response_length.toLocaleString() + ' chars' : '';
                var promptText = esc(String(trace.compiled_prompt || ''));
                var responseText = trace.response_text ? esc(String(trace.response_text)) : '<span class="val-null">Response pending</span>';

                traceDrawer = '<div class="card-trace">'
                    + '<button class="trace-toggle">'
                    + '&#9656; Prompt Trace'
                    + ' <span class="trace-badges">'
                    + '<span class="trace-badge trace-model">' + modelLabel + '</span>'
                    + '<span class="trace-badge trace-mode' + batchClass + '">' + modeLabel + '</span>'
                    + '</span>'
                    + '</button>'
                    + '<div class="trace-panels-wrap" hidden>'
                    + '<div class="trace-panel prompt">'
                    + '<div class="trace-panel-hdr"><span>Compiled Prompt</span>' + (promptLen ? '<span class="trace-size">' + promptLen + '</span>' : '') + '</div>'
                    + '<pre class="trace-panel-body">' + promptText + '</pre>'
                    + '</div>'
                    + '<div class="trace-panel response">'
                    + '<div class="trace-panel-hdr"><span>LLM Response</span>' + (responseLen ? '<span class="trace-size">' + responseLen + '</span>' : '') + '</div>'
                    + '<pre class="trace-panel-body response-body">' + responseText + '</pre>'
                    + '</div>'
                    + '</div>'
                    + '</div>';
            }

            return '<div class="card">'
                + '<div class="card-header">' + header + '</div>'
                + '<div class="card-body">' + body + '</div>'
                + drawer
                + traceDrawer
                + '</div>';
        }

        // Render all cards
        const container = document.getElementById('cardsContainer');
        let html = '';
        for (let i = 0; i < records.length; i++) {
            html += buildCard(records[i], offset + i);
        }
        container.innerHTML = html;

        // ── Event delegation ──
        document.addEventListener('click', function(e) {
            const target = e.target;

            // Expand/collapse prose
            if (target.classList && target.classList.contains('expand-btn')) {
                const prose = target.previousElementSibling;
                if (prose && prose.classList.contains('prose')) {
                    prose.classList.toggle('clamped');
                    target.textContent = prose.classList.contains('clamped') ? 'Show more' : 'Show less';
                }
                return;
            }

            // Trace drawer toggle
            if (target.classList && target.classList.contains('trace-toggle')) {
                var panels = target.nextElementSibling;
                if (panels) {
                    var wasHidden = panels.hasAttribute('hidden');
                    if (wasHidden) panels.removeAttribute('hidden');
                    else panels.setAttribute('hidden', '');
                    var badgesHtml = target.querySelector('.trace-badges');
                    target.innerHTML = (wasHidden ? '&#9662;' : '&#9656;') + ' Prompt Trace ' + (badgesHtml ? badgesHtml.outerHTML : '');
                }
                return;
            }

            // Metadata drawer toggle
            if (target.classList && target.classList.contains('meta-toggle')) {
                const content = target.nextElementSibling;
                if (content) {
                    const isHidden = content.hasAttribute('hidden');
                    if (isHidden) content.removeAttribute('hidden');
                    else content.setAttribute('hidden', '');
                    target.innerHTML = (isHidden ? '&#9662;' : '&#9656;') + ' Metadata (' + content.children.length + ' fields)';
                }
                return;
            }

            // Pagination
            if (target.id === 'prevBtn' || target.closest && target.closest('#prevBtn')) {
                vscode.postMessage({ type: 'paginate', direction: 'previous' });
                return;
            }
            if (target.id === 'nextBtn' || target.closest && target.closest('#nextBtn')) {
                vscode.postMessage({ type: 'paginate', direction: 'next' });
                return;
            }

            // View toggle
            const toggleBtn = target.closest ? target.closest('.view-toggle') : null;
            if (toggleBtn && toggleBtn.dataset.mode) {
                vscode.postMessage({ type: 'toggleView', mode: toggleBtn.dataset.mode });
                return;
            }
        });
        `;

        const body = toolbar + '\n    <div class="cards-wrap" id="cardsContainer"></div>';
        webview.html = buildPage(nonce, body, cardScript);
    }

    // ── Table view ────────────────────────────────────────────────────

    private renderTable(
        webview: vscode.Webview,
        result: PreviewResult,
        actionName: string,
        limit: number,
        offset: number
    ): void {
        const nonce = getNonce();
        const firstRecord = result.records[0];
        if (!firstRecord || typeof firstRecord !== 'object') {
            this.renderEmpty(webview, actionName);
            return;
        }

        const columns = Object.keys(firstRecord);
        const colCount = columns.length;
        const { from, to, hasPrev, hasNext } = paginationVars(offset, limit, result.totalCount);

        const headerCells = columns
            .map((col) => `<th role="columnheader">${escapeHtml(col)}</th>`)
            .join('');

        const bodyRows = result.records
            .map((record) => {
                const rec = record as Record<string, unknown>;
                const cells = columns
                    .map((col) => `<td role="gridcell">${escapeHtml(formatCell(rec[col]))}</td>`)
                    .join('');
                return `<tr role="row">${cells}</tr>`;
            })
            .join('');

        const toolbar = buildToolbar({
            actionName, meta: `${colCount} ${colCount === 1 ? 'column' : 'columns'} &middot; rows ${from}&ndash;${to} of ${result.totalCount}`,
            backendType: result.backendType, activeMode: 'table', hasPrev, hasNext,
        });
        const body = `${toolbar}
    <div class="table-wrap">
        <table role="grid" aria-label="Query results for ${escapeHtml(actionName)}">
            <thead><tr role="row">${headerCells}</tr></thead>
            <tbody>${bodyRows}</tbody>
        </table>
    </div>`;
        webview.html = buildPage(nonce, body, viewScript());
    }

    // ── JSON view ─────────────────────────────────────────────────────

    private renderJSON(
        webview: vscode.Webview,
        result: PreviewResult,
        actionName: string,
        limit: number,
        offset: number
    ): void {
        const nonce = getNonce();
        const { from, to, hasPrev, hasNext } = paginationVars(offset, limit, result.totalCount);

        const jsonData = {
            _metadata: {
                action: actionName,
                storage: { type: result.backendType, path: result.storagePath },
                pagination: { from, to, total: result.totalCount },
                files: result.files,
            },
            records: result.records,
        };

        const jsonString = JSON.stringify(jsonData, null, 2);

        const toolbar = buildToolbar({
            actionName, meta: `rows ${from}&ndash;${to} of ${result.totalCount}`,
            backendType: result.backendType, activeMode: 'json', hasPrev, hasNext,
        });
        const body = `${toolbar}
    <div class="json-wrap">
        <pre role="region" aria-label="JSON formatted data"><code>${escapeHtml(jsonString)}</code></pre>
    </div>`;
        webview.html = buildPage(nonce, body, viewScript());
    }

    // ── Error / Empty ─────────────────────────────────────────────────

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
    <style>${allStyles()}</style>
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
    <style>${allStyles()}</style>
</head>
<body>
    <div class="message empty">${title}</div>
</body>
</html>`;
    }
}

// ── Helpers ───────────────────────────────────────────────────────────

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
    if (value === null || value === undefined) return '';
    if (typeof value === 'object') return JSON.stringify(value);
    return String(value);
}

/** Compute common pagination display variables. */
function paginationVars(offset: number, limit: number, totalCount: number) {
    return {
        from: offset + 1,
        to: Math.min(offset + limit, totalCount),
        hasPrev: offset > 0,
        hasNext: offset + limit < totalCount,
    };
}

/** Build the toolbar HTML with view toggles and pagination. */
function buildToolbar(opts: {
    actionName: string;
    meta: string;
    backendType: string;
    activeMode: ViewMode;
    hasPrev: boolean;
    hasNext: boolean;
}): string {
    const modes: ViewMode[] = ['card', 'table', 'json'];
    const labels: Record<ViewMode, string> = { card: 'Cards', table: 'Table', json: 'JSON' };
    const toggles = modes.map((m) => {
        const active = m === opts.activeMode;
        return `<button class="view-toggle" data-mode="${m}" ${active ? 'disabled aria-pressed="true"' : 'aria-pressed="false"'}>${labels[m]}</button>`;
    }).join('');

    return `<div class="toolbar">
        <span class="action-name">${escapeHtml(opts.actionName)}</span>
        <span class="meta">${opts.meta}</span>
        <span class="meta secondary">${escapeHtml(opts.backendType)}</span>
        <span class="spacer"></span>
        ${toggles}
        <button class="nav-btn" id="prevBtn" ${opts.hasPrev ? '' : 'disabled'} title="Previous page">&larr; Prev</button>
        <button class="nav-btn" id="nextBtn" ${opts.hasNext ? '' : 'disabled'} title="Next page">Next &rarr;</button>
    </div>`;
}

/** Build the HTML document wrapper. */
function buildPage(nonce: string, body: string, script: string): string {
    return `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-${nonce}';">
    <title>Query Results</title>
    <style>${allStyles()}</style>
</head>
<body>
    ${body}
    <script nonce="${nonce}">${script}</script>
</body>
</html>`;
}

/** Shared script for table/JSON views (pagination + view toggle). */
function viewScript(): string {
    return `
        const vscode = acquireVsCodeApi();
        document.addEventListener('click', function(e) {
            var target = e.target;
            if (target.id === 'prevBtn' || (target.closest && target.closest('#prevBtn'))) {
                vscode.postMessage({ type: 'paginate', direction: 'previous' });
                return;
            }
            if (target.id === 'nextBtn' || (target.closest && target.closest('#nextBtn'))) {
                vscode.postMessage({ type: 'paginate', direction: 'next' });
                return;
            }
            var toggleBtn = target.closest ? target.closest('.view-toggle') : null;
            if (toggleBtn && toggleBtn.dataset.mode) {
                vscode.postMessage({ type: 'toggleView', mode: toggleBtn.dataset.mode });
            }
        });
    `;
}

/** All CSS styles — shared across card, table, JSON, error, and empty views. */
function allStyles(): string {
    return `
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: var(--vscode-font-family, sans-serif);
            font-size: var(--vscode-font-size, 13px);
            color: var(--vscode-foreground);
            background: var(--vscode-editor-background);
            height: 100vh;
            display: flex;
            flex-direction: column;
        }

        /* ── Toolbar ── */
        .toolbar {
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 6px 12px;
            border-bottom: 1px solid var(--vscode-panel-border);
            background: var(--vscode-editor-background);
            flex-shrink: 0;
        }
        .action-name { font-weight: 600; }
        .meta { opacity: 0.7; font-size: 0.9em; }
        .meta.secondary { opacity: 0.5; }
        .meta.error-label { color: var(--vscode-errorForeground); opacity: 1; }
        .spacer { flex: 1; }
        .view-toggle {
            padding: 2px 10px;
            font-size: 0.85em;
            border: 1px solid var(--vscode-panel-border);
            background: var(--vscode-button-secondaryBackground);
            color: var(--vscode-button-secondaryForeground);
            cursor: pointer;
            border-radius: 0;
        }
        .view-toggle:first-of-type { border-top-left-radius: 3px; border-bottom-left-radius: 3px; }
        .view-toggle:nth-of-type(3) { border-top-right-radius: 3px; border-bottom-right-radius: 3px; margin-right: 10px; }
        .view-toggle:hover:not(:disabled) { background: var(--vscode-button-secondaryHoverBackground); }
        .view-toggle:disabled {
            background: var(--vscode-button-background);
            color: var(--vscode-button-foreground);
            cursor: default;
        }
        .nav-btn {
            padding: 2px 8px;
            font-size: 0.85em;
            border: 1px solid var(--vscode-panel-border);
            border-radius: 3px;
            background: var(--vscode-button-secondaryBackground);
            color: var(--vscode-button-secondaryForeground);
            cursor: pointer;
        }
        .nav-btn:hover:not(:disabled) { background: var(--vscode-button-secondaryHoverBackground); }
        .nav-btn:disabled { opacity: 0.4; cursor: default; }

        /* ── Cards ── */
        .cards-wrap {
            flex: 1;
            overflow: auto;
            padding: 12px;
        }
        .card {
            border: 1px solid var(--vscode-panel-border);
            border-left: 4px solid #7F77DD;
            border-radius: 6px;
            background: var(--vscode-editor-background);
            margin-bottom: 10px;
            overflow: hidden;
            box-shadow: 0 1px 3px 0 rgb(0 0 0 / 0.2), 0 1px 2px -1px rgb(0 0 0 / 0.15);
            transition: transform 150ms ease, box-shadow 150ms ease;
        }
        .card:hover {
            transform: translateY(-1px);
            box-shadow: 0 4px 12px 0 rgb(0 0 0 / 0.35), 0 2px 4px -1px rgb(0 0 0 / 0.25);
        }
        .card-header {
            padding: 8px 12px;
            border-bottom: 1px solid var(--vscode-panel-border);
            font-family: var(--vscode-editor-font-family);
            font-size: 10px;
            color: var(--vscode-descriptionForeground);
            display: flex;
            align-items: center;
            gap: 8px;
            flex-wrap: wrap;
        }
        .card-index {
            font-weight: 600;
            color: var(--vscode-foreground);
            opacity: 0.4;
        }
        .card-id {
            opacity: 0.5;
            max-width: 160px;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        .card-body {
            padding: 10px 12px;
            display: flex;
            flex-direction: column;
            gap: 8px;
        }
        .card-empty {
            font-size: 0.85em;
            font-style: italic;
            color: var(--vscode-descriptionForeground);
            opacity: 0.6;
        }
        .field-row { min-width: 0; }
        .field-inline {
            display: flex;
            align-items: baseline;
            gap: 10px;
        }
        .field-block {
            display: flex;
            flex-direction: column;
            gap: 3px;
        }
        .field-label {
            font-size: 10px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            font-weight: 600;
            color: #AFA9EC;
            flex-shrink: 0;
            min-width: 80px;
        }
        .field-value {
            font-family: var(--vscode-editor-font-family);
            font-size: 0.92em;
            color: var(--vscode-editor-foreground);
            min-width: 0;
            flex: 1;
        }

        /* Value types */
        .val-null { font-size: 10px; font-style: italic; opacity: 0.4; }
        .val-number { font-variant-numeric: tabular-nums; }
        .val-string { word-break: break-word; }
        .badge {
            display: inline-block;
            padding: 1px 8px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 500;
        }
        .badge-true {
            background: color-mix(in srgb, var(--vscode-testing-iconPassed) 15%, transparent);
            color: var(--vscode-testing-iconPassed);
        }
        .badge-false {
            background: color-mix(in srgb, var(--vscode-testing-iconFailed) 15%, transparent);
            color: var(--vscode-testing-iconFailed);
        }
        .pill {
            display: inline-flex;
            align-items: center;
            padding: 1px 8px;
            border-radius: 6px;
            font-size: 11px;
            font-family: var(--vscode-editor-font-family);
            background: #3C3489;
            color: #CECBF6;
            border: 1px solid #3C3489;
            margin-right: 4px;
        }
        .prose {
            line-height: 1.5;
            white-space: pre-wrap;
            word-break: break-word;
            font-family: var(--vscode-font-family);
            font-size: 0.92em;
        }
        .prose.clamped {
            max-height: 4.5em;
            overflow: hidden;
        }
        .expand-btn {
            background: none;
            border: none;
            color: var(--vscode-textLink-foreground);
            cursor: pointer;
            font-size: 10px;
            padding: 0;
            margin-top: 2px;
        }
        .expand-btn:hover { text-decoration: underline; }
        .code-block {
            background: var(--vscode-textCodeBlock-background);
            border-radius: 4px;
            padding: 8px;
            font-family: var(--vscode-editor-font-family);
            font-size: 0.85em;
            line-height: 1.4;
            max-height: 300px;
            overflow: auto;
            white-space: pre-wrap;
            word-break: break-all;
        }

        /* Metadata drawer */
        .card-meta {
            border-top: 1px solid var(--vscode-panel-border);
        }
        .meta-toggle {
            display: flex;
            align-items: center;
            gap: 4px;
            width: 100%;
            padding: 6px 12px;
            background: none;
            border: none;
            color: var(--vscode-descriptionForeground);
            font-size: 10px;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            cursor: pointer;
        }
        .meta-toggle:hover { color: var(--vscode-foreground); }
        .meta-content {
            padding: 0 12px 8px;
            display: flex;
            flex-direction: column;
            gap: 3px;
        }
        .meta-content[hidden] { display: none; }
        .meta-row {
            display: flex;
            align-items: baseline;
            gap: 8px;
            min-width: 0;
        }
        .meta-key {
            font-size: 9px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            font-weight: 500;
            color: #AFA9EC;
            opacity: 0.6;
            flex-shrink: 0;
            min-width: 60px;
        }
        .meta-val {
            font-family: var(--vscode-editor-font-family);
            font-size: 11px;
            color: var(--vscode-descriptionForeground);
            word-break: break-all;
            min-width: 0;
        }

        /* ── Prompt Trace drawer ── */
        .card-trace {
            border-top: 1px solid color-mix(in srgb, #7F77DD 30%, var(--vscode-panel-border));
        }
        .trace-toggle {
            display: flex;
            align-items: center;
            gap: 4px;
            width: 100%;
            padding: 6px 12px;
            background: none;
            border: none;
            color: #AFA9EC;
            font-size: 10px;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            cursor: pointer;
        }
        .trace-toggle:hover { color: var(--vscode-foreground); }
        .trace-badges { display: inline-flex; gap: 4px; margin-left: auto; }
        .trace-badge {
            font-size: 9px;
            font-family: var(--vscode-editor-font-family);
            padding: 1px 6px;
            border-radius: 4px;
            font-weight: 500;
        }
        .trace-model {
            background: color-mix(in srgb, var(--vscode-foreground) 8%, transparent);
            color: var(--vscode-descriptionForeground);
            border: 1px solid color-mix(in srgb, var(--vscode-foreground) 12%, transparent);
        }
        .trace-mode {
            background: color-mix(in srgb, #2dd4bf 12%, transparent);
            color: #2dd4bf;
            border: 1px solid color-mix(in srgb, #2dd4bf 20%, transparent);
        }
        .trace-mode.batch {
            background: color-mix(in srgb, #f59e0b 12%, transparent);
            color: #f59e0b;
            border: 1px solid color-mix(in srgb, #f59e0b 20%, transparent);
        }
        .trace-panels-wrap {
            padding: 0 12px 10px;
            display: flex;
            flex-direction: column;
            gap: 8px;
        }
        .trace-panels-wrap[hidden] { display: none; }
        .trace-panel {
            border-radius: 4px;
            border: 1px solid var(--vscode-panel-border);
            overflow: hidden;
        }
        .trace-panel-hdr {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 4px 10px;
            font-size: 9px;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            font-weight: 600;
        }
        .trace-size {
            font-family: var(--vscode-editor-font-family);
            font-weight: 400;
            letter-spacing: 0;
            text-transform: none;
            opacity: 0.5;
        }
        .trace-panel.prompt .trace-panel-hdr {
            background: color-mix(in srgb, #7F77DD 10%, var(--vscode-editor-background));
            color: #AFA9EC;
        }
        .trace-panel.response .trace-panel-hdr {
            background: color-mix(in srgb, #2dd4bf 8%, var(--vscode-editor-background));
            color: #2dd4bf;
        }
        .trace-panel-body {
            padding: 8px 10px;
            font-family: var(--vscode-editor-font-family);
            font-size: 11px;
            line-height: 1.6;
            color: var(--vscode-editor-foreground);
            opacity: 0.82;
            white-space: pre-wrap;
            word-break: break-word;
            max-height: 240px;
            overflow-y: auto;
            margin: 0;
            background: var(--vscode-textCodeBlock-background);
            border: none;
            border-radius: 0;
        }
        .trace-panel-body.response-body {
            font-size: 12px;
            max-height: 120px;
        }

        /* ── Table ── */
        .table-wrap { flex: 1; overflow: auto; }
        table { width: 100%; border-collapse: collapse; font-size: 0.92em; }
        thead { position: sticky; top: 0; z-index: 1; }
        th {
            background: var(--vscode-editorGroupHeader-tabsBackground);
            color: var(--vscode-foreground);
            font-weight: 600;
            text-align: left;
            padding: 5px 10px;
            border-bottom: 1px solid var(--vscode-panel-border);
            white-space: nowrap;
        }
        td {
            padding: 4px 10px;
            border-bottom: 1px solid var(--vscode-panel-border);
            white-space: nowrap;
            max-width: 400px;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        tr:hover td { background: var(--vscode-list-hoverBackground); }

        /* ── JSON ── */
        .json-wrap { flex: 1; overflow: auto; padding: 12px; }
        .json-wrap pre {
            margin: 0;
            font-family: var(--vscode-editor-font-family);
            font-size: 0.9em;
            line-height: 1.4;
        }
        .json-wrap code { color: var(--vscode-editor-foreground); }

        /* ── Messages ── */
        .message { padding: 24px; text-align: center; opacity: 0.7; }
        .message.error { color: var(--vscode-errorForeground); opacity: 1; text-align: left; }
        .message.error pre {
            margin-top: 12px;
            padding: 10px;
            background: var(--vscode-textCodeBlock-background);
            border-radius: 4px;
            overflow-x: auto;
            font-size: 0.85em;
            white-space: pre-wrap;
            max-height: 300px;
            overflow-y: auto;
        }
    `;
}
