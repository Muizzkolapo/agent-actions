/**
 * DAG Webview
 *
 * Displays a Mermaid-based visual DAG of the workflow.
 *
 * Combines best approaches:
 * - PR #820: Layout configuration (vertical/horizontal)
 * - PR #821: Click-to-navigate callbacks
 * - PR #823: Status-colored nodes, multi-workflow support
 */

import * as vscode from 'vscode';
import { ActionInfo, ActionStatus, WorkflowInfo } from '../model/types';
import { WorkflowModel } from '../model/workflowModel';

export class DagWebview implements vscode.Disposable {
    private panel: vscode.WebviewPanel | undefined;
    private readonly disposables: vscode.Disposable[] = [];
    private currentWorkflowName: string | undefined;

    constructor(
        private readonly context: vscode.ExtensionContext,
        private readonly model: WorkflowModel
    ) {
        // Auto-update when model changes or theme switches
        this.disposables.push(
            this.model.onDidChange(() => {
                if (this.panel) {
                    this.update();
                }
            }),
            vscode.window.onDidChangeActiveColorTheme(() => {
                if (this.panel) {
                    this.update();
                }
            })
        );
    }

    dispose(): void {
        this.panel?.dispose();
        this.disposables.forEach((d) => d.dispose());
    }

    /**
     * Show the DAG panel
     */
    async show(): Promise<void> {
        const workflows = this.model.getWorkflows();

        if (workflows.length === 0) {
            vscode.window.showInformationMessage('No Agent Actions workflow detected.');
            return;
        }

        // If multiple workflows, let user select
        let workflow: WorkflowInfo;
        if (workflows.length === 1) {
            workflow = workflows[0];
        } else {
            const pick = await vscode.window.showQuickPick(
                workflows.map((w) => ({
                    label: w.name,
                    description: `${w.statusSummary.completed}/${w.statusSummary.total} completed`,
                    workflow: w,
                })),
                { title: 'Select Workflow' }
            );
            if (!pick) {
                return;
            }
            workflow = pick.workflow;
        }

        this.showWorkflow(workflow);
    }

    /**
     * Show DAG for a specific workflow
     */
    showWorkflow(workflow: WorkflowInfo): void {
        // Track which workflow we're showing
        this.currentWorkflowName = workflow.name;

        if (this.panel) {
            this.panel.reveal();
        } else {
            this.panel = vscode.window.createWebviewPanel(
                'agentActionsDag',
                `${workflow.name} - Workflow DAG`,
                vscode.ViewColumn.Beside,
                {
                    enableScripts: true,
                    retainContextWhenHidden: true,
                    localResourceRoots: [
                        vscode.Uri.joinPath(this.context.extensionUri, 'media')
                    ],
                }
            );

            this.panel.onDidDispose(() => {
                this.panel = undefined;
                this.currentWorkflowName = undefined;
            }, null, this.disposables);

            // Handle messages from webview
            this.panel.webview.onDidReceiveMessage(
                (message) => {
                    if (message.type === 'openAction') {
                        const action = this.model.getActionByName(message.actionName);
                        if (action) {
                            vscode.commands.executeCommand('agentActions.openConfig', action);
                        } else {
                            vscode.window.showWarningMessage(`Action "${message.actionName}" not found`);
                        }
                    }
                },
                null,
                this.disposables
            );
        }

        this.panel.title = `${workflow.name} - Workflow DAG`;
        this.update();
    }

    private update(): void {
        if (!this.panel) {
            return;
        }

        // Find the workflow we're currently showing (not just the first one)
        const workflows = this.model.getWorkflows();
        const workflow = this.currentWorkflowName
            ? workflows.find((w) => w.name === this.currentWorkflowName) ?? workflows[0]
            : workflows[0];

        if (!workflow) {
            return;
        }

        const config = vscode.workspace.getConfiguration('agentActions');
        const layout = config.get<string>('dagLayout', 'vertical');
        const direction = layout === 'horizontal' ? 'LR' : 'TD';

        const diagram = this.buildMermaidDiagram(workflow.actions, direction);
        const isDark = vscode.window.activeColorTheme.kind === vscode.ColorThemeKind.Dark ||
                       vscode.window.activeColorTheme.kind === vscode.ColorThemeKind.HighContrast;
        this.panel.webview.html = this.renderHtml(this.panel.webview, diagram, workflow.name, isDark);
    }

    private buildMermaidDiagram(actions: ActionInfo[], direction: string): string {
        if (actions.length === 0) {
            return `flowchart ${direction}\n  empty["No actions detected"]`;
        }

        const lines: string[] = [`flowchart ${direction}`];

        // Define nodes with status styling
        for (const action of actions) {
            const nodeId = this.sanitizeId(action.name);
            const label = action.name.replace(/["\]\\]/g, '_');
            const statusClass = this.getStatusClass(action.status);

            lines.push(`  ${nodeId}["[${action.index}] ${label}"]:::${statusClass}`);
        }

        // Define edges
        for (const action of actions) {
            const nodeId = this.sanitizeId(action.name);
            for (const dep of action.dependencies) {
                const depId = this.sanitizeId(dep);
                lines.push(`  ${depId} --> ${nodeId}`);
            }
        }

        // Add click handlers using sanitized action names for security
        for (const action of actions) {
            const nodeId = this.sanitizeId(action.name);
            // Use sanitized name in callback to prevent XSS
            const sanitizedName = this.sanitizeForCallback(action.name);
            lines.push(`  click ${nodeId} callback "${sanitizedName}"`);
        }

        // Add style definitions
        lines.push('');
        lines.push('  classDef completed fill:#28a745,stroke:#1e7e34,color:#fff');
        lines.push('  classDef running fill:#ffc107,stroke:#e0a800,color:#000');
        lines.push('  classDef failed fill:#dc3545,stroke:#c82333,color:#fff');
        lines.push('  classDef pending fill:#6c757d,stroke:#545b62,color:#fff');
        lines.push('  classDef skipped fill:#17a2b8,stroke:#117a8b,color:#fff');

        return lines.join('\n');
    }

    private sanitizeId(name: string): string {
        return name.replace(/[^a-zA-Z0-9_]/g, '_');
    }

    /**
     * Sanitize action name for use in Mermaid callback to prevent XSS
     */
    private sanitizeForCallback(name: string): string {
        // Remove any characters that could break out of the string or execute code
        return name.replace(/[<>"'`\\]/g, '').replace(/\s+/g, '_');
    }

    private getStatusClass(status: ActionStatus): string {
        return status;
    }

    private renderHtml(webview: vscode.Webview, diagram: string, workflowName: string, isDark: boolean): string {
        const nonce = this.getNonce();

        // Use locally bundled Mermaid for security and offline support
        const mermaidUri = webview.asWebviewUri(
            vscode.Uri.joinPath(this.context.extensionUri, 'media', 'mermaid.min.js')
        );

        return `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src ${webview.cspSource} 'nonce-${nonce}'; style-src 'unsafe-inline';">
    <title>${this.escapeHtml(workflowName)} - Workflow DAG</title>
    <style>
        body {
            margin: 0;
            padding: 16px;
            background: var(--vscode-editor-background, #1e1e1e);
            color: var(--vscode-editor-foreground, #d4d4d4);
            font-family: var(--vscode-font-family, sans-serif);
        }
        .header {
            margin-bottom: 16px;
            padding-bottom: 8px;
            border-bottom: 1px solid var(--vscode-panel-border, #444);
        }
        .header h1 {
            margin: 0;
            font-size: 18px;
            font-weight: 500;
        }
        .legend {
            display: flex;
            gap: 16px;
            margin-top: 8px;
            font-size: 12px;
        }
        .legend-item {
            display: flex;
            align-items: center;
            gap: 4px;
        }
        .legend-dot {
            width: 12px;
            height: 12px;
            border-radius: 2px;
        }
        .legend-dot.completed { background: #28a745; }
        .legend-dot.running { background: #ffc107; }
        .legend-dot.failed { background: #dc3545; }
        .legend-dot.pending { background: #6c757d; }
        .legend-dot.skipped { background: #17a2b8; }
        .dag-container {
            position: relative;
            overflow: hidden;
            width: 100%;
            height: calc(100vh - 80px);
            border: 1px solid var(--vscode-panel-border, #444);
            border-radius: 4px;
        }
        .dag-viewport {
            transform-origin: 0 0;
            cursor: grab;
        }
        .dag-viewport.grabbing {
            cursor: grabbing;
        }
        .mermaid {
            display: inline-block;
            padding: 16px;
        }
        .mermaid svg {
            height: auto;
        }
        .zoom-controls {
            position: absolute;
            bottom: 12px;
            right: 12px;
            display: flex;
            flex-direction: column;
            gap: 4px;
            z-index: 10;
        }
        .zoom-controls button {
            width: 32px;
            height: 32px;
            border: 1px solid var(--vscode-panel-border, #444);
            background: var(--vscode-editor-background, #1e1e1e);
            color: var(--vscode-editor-foreground, #d4d4d4);
            border-radius: 4px;
            cursor: pointer;
            font-size: 16px;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .zoom-controls button:hover {
            background: var(--vscode-toolbar-hoverBackground, #333);
        }
        .zoom-level {
            text-align: center;
            font-size: 10px;
            color: var(--vscode-descriptionForeground, #888);
            padding: 2px 0;
        }
        /* Make nodes clickable */
        .node { cursor: pointer; }
        .node:hover rect, .node:hover polygon {
            filter: brightness(1.2);
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>${this.escapeHtml(workflowName)}</h1>
        <div class="legend">
            <div class="legend-item"><div class="legend-dot completed"></div> Completed</div>
            <div class="legend-item"><div class="legend-dot running"></div> Running</div>
            <div class="legend-item"><div class="legend-dot failed"></div> Failed</div>
            <div class="legend-item"><div class="legend-dot pending"></div> Pending</div>
            <div class="legend-item"><div class="legend-dot skipped"></div> Skipped</div>
        </div>
    </div>
    <div class="dag-container" id="dagContainer">
        <div class="dag-viewport" id="dagViewport">
            <div class="mermaid">
${diagram}
            </div>
        </div>
        <div class="zoom-controls">
            <button id="zoomIn" title="Zoom in">+</button>
            <div class="zoom-level" id="zoomLevel">100%</div>
            <button id="zoomOut" title="Zoom out">&minus;</button>
            <button id="zoomFit" title="Fit to view">&#8862;</button>
            <button id="zoomReset" title="Reset zoom">1:1</button>
        </div>
    </div>
    <script src="${mermaidUri}"></script>
    <script nonce="${nonce}">
        const vscode = acquireVsCodeApi();

        mermaid.initialize({
            startOnLoad: true,
            theme: '${isDark ? 'dark' : 'default'}',
            flowchart: {
                curve: 'basis',
                htmlLabels: false,
                padding: 15
            },
            securityLevel: 'strict'
        });

        // Handle click events — only navigate if the user didn't drag
        window.callback = function(actionName) {
            if (didDrag) return;
            if (/^[a-zA-Z0-9_-]+$/.test(actionName)) {
                vscode.postMessage({ type: 'openAction', actionName });
            }
        };

        // Pan and zoom
        const container = document.getElementById('dagContainer');
        const viewport = document.getElementById('dagViewport');
        const zoomLevelEl = document.getElementById('zoomLevel');

        let scale = 1;
        let panX = 0;
        let panY = 0;
        let isPanning = false;
        let didDrag = false;
        let startX = 0;
        let startY = 0;
        let downX = 0;
        let downY = 0;
        const DRAG_THRESHOLD = 5;

        const MIN_SCALE = 0.1;
        const MAX_SCALE = 5;
        const ZOOM_STEP = 0.15;

        function applyTransform() {
            viewport.style.transform = 'translate(' + panX + 'px, ' + panY + 'px) scale(' + scale + ')';
            zoomLevelEl.textContent = Math.round(scale * 100) + '%';
        }

        function zoomAtPoint(newScale, clientX, clientY) {
            newScale = Math.max(MIN_SCALE, Math.min(MAX_SCALE, newScale));
            const rect = container.getBoundingClientRect();
            const x = clientX - rect.left;
            const y = clientY - rect.top;
            panX = x - (x - panX) * (newScale / scale);
            panY = y - (y - panY) * (newScale / scale);
            scale = newScale;
            applyTransform();
        }

        function fitToView() {
            const svg = viewport.querySelector('svg');
            if (!svg) return;
            const cRect = container.getBoundingClientRect();
            // Use getBBox for intrinsic SVG size — immune to CSS transforms and overflow clipping
            const bbox = svg.getBBox();
            const sW = bbox.width;
            const sH = bbox.height;
            if (sW === 0 || sH === 0) return;
            const fitScale = Math.min(cRect.width / (sW + 32), cRect.height / (sH + 32), 2);
            scale = fitScale;
            panX = (cRect.width - sW * scale) / 2 - bbox.x * scale;
            panY = (cRect.height - sH * scale) / 2 - bbox.y * scale;
            applyTransform();
        }

        // Mouse wheel zoom
        container.addEventListener('wheel', function(e) {
            e.preventDefault();
            const delta = e.deltaY > 0 ? -ZOOM_STEP : ZOOM_STEP;
            zoomAtPoint(scale * (1 + delta), e.clientX, e.clientY);
        }, { passive: false });

        // Pan with mouse drag — track distance to distinguish click from drag
        container.addEventListener('mousedown', function(e) {
            if (e.button !== 0) return;
            isPanning = true;
            didDrag = false;
            startX = e.clientX - panX;
            startY = e.clientY - panY;
            downX = e.clientX;
            downY = e.clientY;
            viewport.classList.add('grabbing');
        });

        window.addEventListener('mousemove', function(e) {
            if (!isPanning) return;
            var dx = e.clientX - downX;
            var dy = e.clientY - downY;
            if (!didDrag && Math.abs(dx) + Math.abs(dy) > DRAG_THRESHOLD) {
                didDrag = true;
            }
            panX = e.clientX - startX;
            panY = e.clientY - startY;
            applyTransform();
        });

        window.addEventListener('mouseup', function() {
            isPanning = false;
            viewport.classList.remove('grabbing');
        });

        // Zoom buttons
        document.getElementById('zoomIn').addEventListener('click', function() {
            const rect = container.getBoundingClientRect();
            zoomAtPoint(scale * (1 + ZOOM_STEP), rect.left + rect.width / 2, rect.top + rect.height / 2);
        });

        document.getElementById('zoomOut').addEventListener('click', function() {
            const rect = container.getBoundingClientRect();
            zoomAtPoint(scale * (1 - ZOOM_STEP), rect.left + rect.width / 2, rect.top + rect.height / 2);
        });

        document.getElementById('zoomFit').addEventListener('click', fitToView);

        document.getElementById('zoomReset').addEventListener('click', function() {
            scale = 1;
            panX = 0;
            panY = 0;
            applyTransform();
        });

        // Auto-fit once mermaid finishes rendering the SVG
        var mermaidEl = document.querySelector('.mermaid');
        if (viewport.querySelector('svg')) {
            fitToView();
        } else {
            var fitObserver = new MutationObserver(function() {
                if (viewport.querySelector('svg')) {
                    fitObserver.disconnect();
                    fitToView();
                }
            });
            fitObserver.observe(mermaidEl, { childList: true, subtree: true });
        }
    </script>
</body>
</html>`;
    }

    private getNonce(): string {
        let text = '';
        const possible = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
        for (let i = 0; i < 32; i++) {
            text += possible.charAt(Math.floor(Math.random() * possible.length));
        }
        return text;
    }

    private escapeHtml(value: string): string {
        return value
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }
}
