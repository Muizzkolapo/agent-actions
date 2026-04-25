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
                } else if (message.type === 'copy') {
                    vscode.env.clipboard.writeText(message.text);
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
        var vscode = acquireVsCodeApi();
        var records = JSON.parse(${JSON.stringify(recordsJson)});
        var offset = ${offset};
        var actionName = ${JSON.stringify(actionName)};
        var copyTexts = [];

        var METADATA_KEYS = new Set(['source_guid','lineage','node_id','metadata','target_id','parent_target_id','root_target_id','chunk_info','_recovery','_unprocessed','_file','_trace']);
        var IDENTITY_KEYS = new Set(['source_guid','target_id']);
        var LONG_FORM_HINTS = new Set(['reasoning','classification_reasoning','description','summary','explanation','rationale','comment','notes','source_quote']);

        function classifyField(key) { if (IDENTITY_KEYS.has(key)) return 'identity'; if (METADATA_KEYS.has(key)) return 'metadata'; return 'content'; }
        function isLongForm(key) { var l = key.toLowerCase(); for (var h of LONG_FORM_HINTS) { if (l === h || l.endsWith('_' + h)) return true; } return false; }
        function isInlineArray(v) { if (!Array.isArray(v) || v.length === 0 || v.length > 3) return false; return v.every(function(x) { return typeof x === 'string' || typeof x === 'number'; }); }
        function esc(s) { return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
        function fmt(v, max) { if (v == null) return 'null'; if (typeof v === 'boolean') return String(v); if (typeof v === 'number') return v.toLocaleString(); if (typeof v === 'object') { var s = JSON.stringify(v); return max > 0 && s.length > max ? s.slice(0, max) + '\u2026' : s; } var s = String(v); return max > 0 && s.length > max ? s.slice(0, max) + '\u2026' : s; }
        function isArrayOfObjects(v) { if (!Array.isArray(v) || v.length === 0) return false; return v.every(function(x) { return typeof x === 'object' && x !== null && !Array.isArray(x); }); }
        function isSourceQuote(k) { return k.toLowerCase().indexOf('source_quote') >= 0; }
        function plural(n, word) { return n + ' ' + word + (n === 1 ? '' : 's'); }

        var MAX_TREE_DEPTH = 5;
        var MAX_ARRAY_ITEMS = 20;

        function highlightJson(raw) {
            var parsed; try { parsed = JSON.parse(raw); } catch(e) { return esc(raw); }
            var s = esc(JSON.stringify(parsed, null, 2));
            s = s.replace(/(&quot;(?:[^&]|&(?!quot;))*?&quot;)\s*:/g, '<span class="json-key">$1</span>:');
            s = s.replace(/:\s*(&quot;(?:[^&]|&(?!quot;))*?&quot;)/g, ': <span class="json-str">$1</span>');
            s = s.replace(/:\s*(\d+\.?\d*)/g, ': <span class="json-num">$1</span>');
            s = s.replace(/:\s*(true|false)/g, ': <span class="json-bool">$1</span>');
            s = s.replace(/:\s*(null)/g, ': <span class="json-null">$1</span>');
            return s;
        }

        function renderMarkdown(text) {
            var lines = esc(text).split('\\n');
            var html = '', inList = false;
            for (var i = 0; i < lines.length; i++) {
                var line = lines[i];
                var m;
                if ((m = line.match(/^###\\s+(.*)/))) { if (inList) { html += '</' + inList + '>'; inList = false; } html += '<h3 class="md-h3">' + m[1] + '</h3>'; continue; }
                if ((m = line.match(/^##\\s+(.*)/))) { if (inList) { html += '</' + inList + '>'; inList = false; } html += '<h2 class="md-h2">' + m[1] + '</h2>'; continue; }
                if ((m = line.match(/^#\\s+(.*)/))) { if (inList) { html += '</' + inList + '>'; inList = false; } html += '<h1 class="md-h1">' + m[1] + '</h1>'; continue; }
                if ((m = line.match(/^\\d+\\.\\s+(.*)/))) { if (!inList) { html += '<ol class="md-ol">'; inList = 'ol'; } html += '<li>' + m[1] + '</li>'; continue; }
                if ((m = line.match(/^[-]\\s+(.*)/))) { if (!inList) { html += '<ul class="md-ul">'; inList = 'ul'; } html += '<li>' + m[1] + '</li>'; continue; }
                if (inList) { html += '</' + inList + '>'; inList = false; }
                if (/^---+$/.test(line.trim())) { html += '<hr class="md-hr">'; continue; }
                if (line.trim() === '') { html += '<div class="md-spacer"></div>'; continue; }
                html += '<p class="md-p">' + line + '</p>';
            }
            if (inList) html += '</' + inList + '>';
            html = html.replace(/\\*\\*([^*]+)\\*\\*/g, '<strong>$1</strong>');
            return html;
        }

        function renderFieldValue(key, value) {
            if (value == null) return '<span class="t-null">null</span>';
            if (typeof value === 'boolean') return '<span class="badge ' + (value ? 'badge-true' : 'badge-false') + '">' + String(value) + '</span>';
            if (typeof value === 'number') return '<span class="t-val">' + value.toLocaleString() + '</span>';
            if (isInlineArray(value)) return value.map(function(x) { return '<span class="pill">' + esc(String(x)) + '</span>'; }).join(' ');
            if (isArrayOfObjects(value)) return renderArrayOfObjects(key, value);
            if (typeof value === 'object') return '<pre class="code-block json-highlight">' + highlightJson(JSON.stringify(value, null, 2)) + '</pre>';
            var str = String(value);
            if (isSourceQuote(key)) return '<div class="source-quote">' + esc(str) + '</div>';
            if (str.length > 80 || isLongForm(key)) return '<div class="tree-prose">' + esc(str) + '</div>';
            return '<span class="t-val">' + esc(str) + '</span>';
        }

        function renderTreeField(key, value, defaultOpen, depth) {
            if (depth === undefined) depth = 0;
            if (typeof value === 'object' && value !== null && !Array.isArray(value) && depth < MAX_TREE_DEPTH) {
                var keys = Object.keys(value);
                var childHtml = '';
                for (var i = 0; i < keys.length; i++) {
                    var ck = keys[i], cv = value[keys[i]];
                    if (isArrayOfObjects(cv)) childHtml += renderArrayOfObjects(ck, cv, depth + 1);
                    else childHtml += renderTreeField(ck, cv, false, depth + 1);
                }
                var valStr = JSON.stringify(value);
                var preview = valStr.length > 60 ? valStr.slice(0, 60) + '\u2026' : valStr;
                return '<div class="tree-field"><button class="tree-toggle" data-tree-toggle>'
                    + '<span class="tree-chevron">' + (defaultOpen ? '&#9660;' : '&#9654;') + '</span>'
                    + '<span class="t-key">' + esc(key) + '</span>'
                    + '<span class="t-type">' + esc(plural(keys.length, 'field')) + '</span>'
                    + (!defaultOpen ? '<span class="t-preview">' + esc(preview) + '</span>' : '')
                    + '</button><div class="tree-children"' + (defaultOpen ? '' : ' hidden') + '>'
                    + childHtml + '</div></div>';
            }
            var valStr = typeof value === 'string' ? value : typeof value === 'object' ? JSON.stringify(value) : String(value != null ? value : '');
            var preview = valStr.length > 60 ? valStr.slice(0, 60) + '\u2026' : valStr;
            return '<div class="tree-field"><button class="tree-toggle" data-tree-toggle>'
                + '<span class="tree-chevron">' + (defaultOpen ? '&#9660;' : '&#9654;') + '</span>'
                + '<span class="t-key">' + esc(key) + '</span>'
                + (!defaultOpen ? '<span class="t-preview">' + esc(preview) + '</span>' : '')
                + '</button><div class="tree-field-value"' + (defaultOpen ? '' : ' hidden') + '>'
                + renderFieldValue(key, value) + '</div></div>';
        }

        function renderTreeNode(label, badge, defaultOpen, childrenHtml) {
            return '<div class="tree-node"><button class="tree-toggle" data-tree-toggle>'
                + '<span class="tree-chevron">' + (defaultOpen ? '&#9660;' : '&#9654;') + '</span>'
                + '<span class="t-ns">' + esc(label) + '</span>'
                + (badge ? '<span class="t-type">' + esc(badge) + '</span>' : '')
                + '</button><div class="tree-children"' + (defaultOpen ? '' : ' hidden') + '>'
                + childrenHtml + '</div></div>';
        }

        function renderArrayOfObjects(fieldKey, items, depth) {
            if (depth === undefined) depth = 0;
            var maxItems = MAX_ARRAY_ITEMS;
            var displayItems = items.length > maxItems ? items.slice(0, maxItems) : items;
            var ch = '';
            for (var i = 0; i < displayItems.length; i++) {
                var item = displayItems[i], itemOpen = (i === 0), pText = plural(Object.keys(item).length, 'field');
                for (var ek of Object.keys(item)) { var ev = item[ek]; if (typeof ev === 'string' && ev.length > 10) { pText = ev.length > 80 ? ev.slice(0, 80) + '\u2026' : ev; break; } }
                var fh = ''; for (var fk of Object.keys(item)) fh += renderTreeField(fk, item[fk], true, depth + 1);
                ch += '<div class="array-item"><button class="tree-toggle" data-tree-toggle>'
                    + '<span class="tree-chevron">' + (itemOpen ? '&#9660;' : '&#9654;') + '</span>'
                    + '<span class="t-idx">[' + i + ']</span><span class="t-type">object</span>'
                    + (!itemOpen ? '<span class="t-preview">' + esc(pText) + '</span>' : '')
                    + '</button><div class="tree-children"' + (itemOpen ? '' : ' hidden') + '>' + fh + '</div></div>';
            }
            if (items.length > maxItems) {
                ch += '<div class="tree-more">' + (items.length - maxItems) + ' more items\u2026</div>';
            }
            return renderTreeNode(fieldKey, 'array[' + items.length + ']', true, ch);
        }

        function renderSection(label, hint, copyText, defaultOpen, contentHtml, badgesHtml) {
            if (!contentHtml) return '';
            var ci = copyTexts.length; copyTexts.push(copyText || '');
            return '<div class="card-section"><button class="section-toggle" data-section-toggle>'
                + '<span class="sec-chevron">' + (defaultOpen ? '&#9660;' : '&#9654;') + '</span>'
                + '<span class="section-label">' + esc(label) + '</span>'
                + (badgesHtml || '')
                + (hint ? '<span class="section-hint">' + esc(hint) + '</span>' : '')
                + (copyText ? '<span class="copy-btn" data-copy-idx="' + ci + '" title="Copy">&#128203;</span>' : '')
                + '</button><div class="section-content"' + (defaultOpen ? '' : ' hidden') + '>'
                + contentHtml + '</div></div>';
        }

        function buildCard(record, index) {
            var identity = [], meta = [], outputFields = [];
            var dr = record;
            var guardSkipped = false;
            var nsExtracted = false;
            if (record.content && typeof record.content === 'object' && !Array.isArray(record.content)) {
                var content = record.content;
                if (actionName && actionName in content) {
                    var actionNs = content[actionName];
                    if (actionNs == null) {
                        dr = {};
                        guardSkipped = true;
                    } else if (typeof actionNs === 'object' && !Array.isArray(actionNs)) {
                        dr = actionNs;
                        nsExtracted = true;
                    } else {
                        dr = {};
                        dr[actionName] = actionNs;
                        nsExtracted = true;
                    }
                } else if (actionName) {
                    // Action namespace not in content — record passed through without this action producing output
                    dr = {};
                    guardSkipped = true;
                } else {
                    dr = content;
                }
            }
            for (var k of Object.keys(record)) { var r = classifyField(k); if (r === 'identity') identity.push({key:k,value:record[k]}); else if (r === 'metadata') meta.push({key:k,value:record[k]}); }
            for (var k of Object.keys(dr)) { if (nsExtracted || classifyField(k) === 'content') outputFields.push({key:k,value:dr[k]}); }
            var trace = record._trace && typeof record._trace === 'object' && !Array.isArray(record._trace) ? record._trace : null;
            var recOpen = (index === offset);
            var inputData = null;
            if (trace && trace.llm_context) { try { var p = JSON.parse(trace.llm_context); if (typeof p === 'object' && p && !Array.isArray(p)) inputData = p; } catch(e) {} }

            var hdr = '<span class="rec-chevron">' + (recOpen ? '&#9660;' : '&#9654;') + '</span><span class="card-index">#' + (index + 1) + '</span>';
            for (var f of identity) hdr += ' <span class="card-id" title="' + esc(fmt(f.value, 0)) + '">' + esc(fmt(f.value, 24)) + '</span>';
            if (typeof record._file === 'string') hdr += ' <span class="card-id">' + esc(record._file) + '</span>';
            if (!recOpen) hdr += '<span class="rec-preview">' + (trace ? 'trace + ' : '') + (guardSkipped ? 'guard skipped' : plural(outputFields.length, 'field')) + '</span>';

            var s1 = ''; if (trace && trace.compiled_prompt) { var b = ''; if (trace.model_name) b += '<span class="trace-badge trace-model">' + esc(String(trace.model_name)) + '</span>'; if (trace.run_mode) b += '<span class="trace-badge trace-mode' + (trace.run_mode === 'batch' ? ' batch' : '') + '">' + esc(String(trace.run_mode)) + '</span>'; var ptBody; try { ptBody = renderMarkdown(String(trace.compiled_prompt)); } catch(e) { ptBody = esc(String(trace.compiled_prompt)); } s1 = renderSection('Prompt Trace', trace.prompt_length ? trace.prompt_length.toLocaleString() + ' chars' : '', trace.compiled_prompt, false, '<div class="trace-panel-body md-body">' + ptBody + '</div>', '<span class="section-badges">' + b + '</span>'); }
            var s2 = ''; if (inputData && Object.keys(inputData).length > 0) { var ih = ''; for (var ns of Object.keys(inputData)) { var nd = inputData[ns]; if (typeof nd !== 'object' || nd === null) ih += renderTreeField(ns, nd, true); else { var fh = ''; for (var fk of Object.keys(nd)) fh += renderTreeField(fk, nd[fk], true); ih += renderTreeNode(ns, plural(Object.keys(nd).length, 'field'), false, fh); } } s2 = renderSection('Input Data', plural(Object.keys(inputData).length, 'namespace'), JSON.stringify(inputData, null, 2), false, ih, ''); }
            var s3 = ''; if (trace && trace.response_text) { s3 = renderSection('Raw Response', trace.response_length ? trace.response_length.toLocaleString() + ' chars' : '', trace.response_text, false, '<pre class="trace-panel-body response-body">' + highlightJson(String(trace.response_text)) + '</pre>', ''); }
            var s4 = ''; if (outputFields.length > 0) { var oh = ''; for (var f of outputFields) { if (isArrayOfObjects(f.value)) oh += renderArrayOfObjects(f.key, f.value); else oh += renderTreeField(f.key, f.value, true); } s4 = renderSection('Action Output', plural(outputFields.length, 'field'), JSON.stringify(dr, null, 2), true, oh, ''); }
            var s5 = ''; if (meta.length > 0) { var mh = ''; for (var f of meta) mh += '<div class="meta-row"><span class="meta-key">' + esc(f.key) + '</span><span class="meta-val">' + esc(fmt(f.value, 120)) + '</span></div>'; s5 = renderSection('Metadata', plural(meta.length, 'field'), JSON.stringify(Object.fromEntries(meta.map(function(f){return[f.key,f.value]})), null, 2), false, mh, ''); }

            return '<div class="card" data-record-open="' + (recOpen ? 'true' : 'false') + '"><div class="card-header" data-rec-toggle>' + hdr + '</div><div class="card-body-wrap"' + (recOpen ? '' : ' hidden') + '>' + s1 + s2 + s3 + s4 + s5 + (guardSkipped ? '<div class="card-empty">Guard skipped \u2014 no output produced</div>' : (outputFields.length === 0 ? '<div class="card-empty">No content fields</div>' : '')) + '</div></div>';
        }

        var container = document.getElementById('cardsContainer');
        var html = ''; for (var i = 0; i < records.length; i++) html += buildCard(records[i], offset + i);
        container.innerHTML = html;

        document.addEventListener('click', function(e) {
            var target = e.target;
            var recT = target.closest ? target.closest('[data-rec-toggle]') : null;
            if (recT) { var card = recT.closest('.card'); if (card) { var w = card.querySelector('.card-body-wrap'); var h = w.hasAttribute('hidden'); if (h) w.removeAttribute('hidden'); else w.setAttribute('hidden',''); var c = recT.querySelector('.rec-chevron'); if (c) c.innerHTML = h ? '&#9660;' : '&#9654;'; var p = recT.querySelector('.rec-preview'); if (p) p.style.display = h ? 'none' : ''; } return; }
            var cpB = target.closest ? target.closest('.copy-btn') : null;
            if (cpB) { e.stopPropagation(); var idx = parseInt(cpB.dataset.copyIdx, 10); if (!isNaN(idx) && copyTexts[idx]) { vscode.postMessage({type:'copy',text:copyTexts[idx]}); cpB.innerHTML = '&#10003;'; setTimeout(function() { cpB.innerHTML = '&#128203;'; }, 1500); } return; }
            var secT = target.closest ? target.closest('[data-section-toggle]') : null;
            if (secT) { var ct = secT.nextElementSibling; if (ct) { var h = ct.hasAttribute('hidden'); if (h) ct.removeAttribute('hidden'); else ct.setAttribute('hidden',''); var c = secT.querySelector('.sec-chevron'); if (c) c.innerHTML = h ? '&#9660;' : '&#9654;'; } return; }
            var trT = target.closest ? target.closest('[data-tree-toggle]') : null;
            if (trT) { var sb = trT.nextElementSibling; if (sb) { var h = sb.hasAttribute('hidden'); if (h) sb.removeAttribute('hidden'); else sb.setAttribute('hidden',''); var c = trT.querySelector('.tree-chevron'); if (c) c.innerHTML = h ? '&#9660;' : '&#9654;'; var p = trT.querySelector('.t-preview'); if (p) p.style.display = h ? 'none' : ''; } return; }
            if (target.id === 'prevBtn' || (target.closest && target.closest('#prevBtn'))) { vscode.postMessage({type:'paginate',direction:'previous'}); return; }
            if (target.id === 'nextBtn' || (target.closest && target.closest('#nextBtn'))) { vscode.postMessage({type:'paginate',direction:'next'}); return; }
            var tB = target.closest ? target.closest('.view-toggle') : null;
            if (tB && tB.dataset.mode) { vscode.postMessage({type:'toggleView',mode:tB.dataset.mode}); return; }
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
    if (typeof value === 'object') {
        const str = JSON.stringify(value);
        return str.length > 80 ? str.slice(0, 80) + '\u2026' : str;
    }
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
        .cards-wrap { flex: 1; overflow: auto; padding: 0; }
        .card { border-bottom: 1px solid var(--vscode-panel-border); background: var(--vscode-editor-background); overflow: hidden; }
        .card-header { display: flex; align-items: center; gap: 8px; padding: 6px 12px; font-family: var(--vscode-editor-font-family); font-size: 10px; color: var(--vscode-descriptionForeground); flex-wrap: wrap; cursor: pointer; }
        .card-header:hover { background: var(--vscode-list-hoverBackground); }
        .card-index { font-weight: 600; opacity: 0.4; }
        .card-id { opacity: 0.4; max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .rec-chevron { color: var(--vscode-descriptionForeground); margin-right: 2px; font-size: 10px; }
        .rec-preview { font-size: 10px; color: var(--vscode-descriptionForeground); opacity: 0.5; margin-left: auto; }
        .card-body-wrap { padding-left: 16px; }
        .card-body-wrap[hidden] { display: none; }
        .card-empty { font-size: 0.85em; font-style: italic; color: var(--vscode-descriptionForeground); opacity: 0.6; padding: 8px 12px; }

        /* Sections */
        .card-section { border-top: 1px solid var(--vscode-panel-border); }
        .section-toggle { display: flex; align-items: center; gap: 6px; width: 100%; padding: 6px 12px; background: none; border: none; color: var(--vscode-foreground); font-size: 11px; cursor: pointer; text-align: left; }
        .section-toggle:hover { background: var(--vscode-list-hoverBackground); }
        .sec-chevron { color: var(--vscode-descriptionForeground); font-size: 10px; flex-shrink: 0; }
        .section-label { font-weight: 600; font-size: 11px; }
        .section-badges { display: inline-flex; gap: 4px; margin-left: 4px; }
        .section-hint { font-size: 10px; color: var(--vscode-descriptionForeground); opacity: 0.5; margin-left: auto; }
        .section-content { padding: 4px 4px 8px 16px; }
        .section-content[hidden] { display: none; }
        .copy-btn { background: none; border: none; cursor: pointer; font-size: 12px; opacity: 0.3; padding: 2px 4px; color: var(--vscode-foreground); margin-left: 4px; }
        .copy-btn:hover { opacity: 0.8; }

        /* Tree view — consistent 16px indent per level */
        .tree-node, .tree-field, .array-item { min-width: 0; }
        .tree-toggle { display: flex; align-items: center; gap: 6px; width: 100%; padding: 2px 8px 2px 16px; background: none; border: none; color: var(--vscode-foreground); font-size: 12px; cursor: pointer; text-align: left; }
        .tree-toggle:hover { background: var(--vscode-list-hoverBackground); border-radius: 3px; }
        .tree-chevron { font-size: 9px; color: var(--vscode-descriptionForeground); flex-shrink: 0; width: 10px; }
        .tree-children { padding-left: 16px; }
        .tree-children[hidden] { display: none; }
        .tree-field-value { padding: 2px 8px 4px 48px; }
        .tree-field-value[hidden] { display: none; }
        .tree-more { font-size: 11px; color: var(--vscode-descriptionForeground); font-style: italic; padding: 4px 16px; opacity: 0.6; }

        /* Token colors */
        .t-ns { color: #c084fc; font-family: var(--vscode-editor-font-family); font-weight: 600; font-size: 12px; }
        .t-key { color: #7dd3fc; font-family: var(--vscode-editor-font-family); font-size: 12px; }
        .t-val { color: #fdba74; font-family: var(--vscode-editor-font-family); font-size: 11px; word-break: break-word; }
        .t-type { color: #6ee7b7; font-family: var(--vscode-editor-font-family); font-size: 10px; }
        .t-idx { color: #7dd3fc; font-family: var(--vscode-editor-font-family); font-size: 11px; }
        .t-preview { color: #52525b; font-family: var(--vscode-editor-font-family); font-size: 11px; font-style: italic; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; min-width: 0; }
        .t-null { font-size: 10px; font-style: italic; opacity: 0.4; }

        /* Values */
        .badge { display: inline-block; padding: 1px 8px; border-radius: 4px; font-size: 11px; font-weight: 500; }
        .badge-true { background: color-mix(in srgb, var(--vscode-testing-iconPassed) 15%, transparent); color: var(--vscode-testing-iconPassed); }
        .badge-false { background: color-mix(in srgb, var(--vscode-testing-iconFailed) 15%, transparent); color: var(--vscode-testing-iconFailed); }
        .pill { display: inline-flex; align-items: center; padding: 1px 8px; border-radius: 6px; font-size: 11px; font-family: var(--vscode-editor-font-family); background: color-mix(in srgb, #7dd3fc 10%, transparent); color: #7dd3fc; border: 1px solid color-mix(in srgb, #7dd3fc 20%, transparent); margin-right: 4px; }
        .code-block { background: var(--vscode-textCodeBlock-background); border-radius: 4px; padding: 8px; font-family: var(--vscode-editor-font-family); font-size: 11px; line-height: 1.4; max-height: 300px; overflow: auto; white-space: pre-wrap; word-break: break-all; color: #a1a1aa; }
        .tree-prose { font-family: var(--vscode-font-family); font-size: 12px; line-height: 1.6; color: var(--vscode-editor-foreground); opacity: 0.85; padding: 6px 10px; border-radius: 4px; background: var(--vscode-textCodeBlock-background); white-space: pre-wrap; word-break: break-word; }
        .source-quote { font-family: var(--vscode-font-family); font-size: 12px; line-height: 1.5; color: var(--vscode-editor-foreground); opacity: 0.75; padding: 6px 10px; border-left: 3px solid #c084fc; background: color-mix(in srgb, #c084fc 5%, var(--vscode-textCodeBlock-background)); border-radius: 0 4px 4px 0; white-space: pre-wrap; word-break: break-word; }

        /* Metadata */
        .meta-row { display: flex; align-items: baseline; gap: 8px; min-width: 0; padding: 1px 0; }
        .meta-row:hover { background: var(--vscode-list-hoverBackground); }
        .meta-key { font-size: 10px; letter-spacing: 0.5px; font-weight: 500; color: #7dd3fc; opacity: 0.6; flex-shrink: 0; min-width: 60px; font-family: var(--vscode-editor-font-family); }
        .meta-val { font-family: var(--vscode-editor-font-family); font-size: 11px; color: var(--vscode-descriptionForeground); word-break: break-all; min-width: 0; }

        /* Trace badges */
        .trace-badge { font-size: 9px; font-family: var(--vscode-editor-font-family); padding: 1px 6px; border-radius: 3px; font-weight: 500; }
        .trace-model { background: color-mix(in srgb, var(--vscode-foreground) 8%, transparent); color: var(--vscode-descriptionForeground); border: 1px solid color-mix(in srgb, var(--vscode-foreground) 12%, transparent); }
        .trace-mode { background: color-mix(in srgb, #6ee7b7 10%, transparent); color: #6ee7b7; border: 1px solid color-mix(in srgb, #6ee7b7 18%, transparent); }
        .trace-mode.batch { background: color-mix(in srgb, #f59e0b 10%, transparent); color: #f59e0b; border: 1px solid color-mix(in srgb, #f59e0b 18%, transparent); }
        .trace-panel-body { padding: 8px 10px; font-family: var(--vscode-editor-font-family); font-size: 11px; line-height: 1.6; color: #a1a1aa; white-space: pre-wrap; word-break: break-word; max-height: 300px; overflow-y: auto; margin: 0; background: var(--vscode-textCodeBlock-background); border: none; border-radius: 4px; }
        .trace-panel-body.response-body { font-size: 12px; }

        /* JSON syntax highlighting */
        .json-key { color: #7dd3fc; }
        .json-str { color: #ce9178; }
        .json-num { color: #b5cea8; }
        .json-bool { color: #569cd6; }
        .json-null { color: #569cd6; font-style: italic; }

        /* Markdown rendering in prompt trace */
        .md-body { white-space: normal; }
        .md-h1 { font-size: 1.3em; font-weight: 700; color: var(--vscode-foreground); margin: 12px 0 6px; border-bottom: 1px solid var(--vscode-panel-border); padding-bottom: 4px; }
        .md-h2 { font-size: 1.1em; font-weight: 700; color: var(--vscode-foreground); margin: 10px 0 4px; }
        .md-h3 { font-size: 1em; font-weight: 600; color: var(--vscode-foreground); margin: 8px 0 4px; }
        .md-p { margin: 4px 0; line-height: 1.6; }
        .md-ol, .md-ul { margin: 4px 0 4px 20px; line-height: 1.6; }
        .md-ol li, .md-ul li { margin: 2px 0; }
        .md-hr { border: none; border-top: 1px solid var(--vscode-panel-border); margin: 8px 0; }
        .md-spacer { height: 6px; }
        .md-code { background: var(--vscode-textCodeBlock-background); padding: 1px 4px; border-radius: 3px; font-family: var(--vscode-editor-font-family); font-size: 0.95em; }
        .md-body strong { font-weight: 700; color: var(--vscode-foreground); }
        .md-body em { font-style: italic; }

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
