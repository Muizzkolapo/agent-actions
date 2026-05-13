/**
 * DAG Webview
 *
 * Renders the workflow dependency graph in a VS Code webview. When
 * `agentActions.dagRenderer` is `reactflow`, the panel loads a React bundle that
 * shares the docs DAG transformer. When set to `mermaid`, the legacy Mermaid
 * diagram is used instead.
 */

import * as vscode from 'vscode';
import { ActionInfo, ActionStatus, WorkflowInfo } from '../model/types';
import { WorkflowModel } from '../model/workflowModel';
import { logger } from '../utils/logger';

type DagRendererMode = 'reactflow' | 'mermaid';

/** Host → webview payload for React Flow mode (mirrors contract). */
export interface DagUpdatePayload {
    workflowName: string;
    layout: 'vertical' | 'horizontal';
    actions: Array<{
        name: string;
        deps: string[];
        kind: 'llm' | 'tool' | 'unknown';
        status?: ActionInfo['status'];
        model?: string;
        impl?: string;
        intent?: string;
        inputs?: string[];
        observe?: string[];
        outputs?: string[];
        outputFields?: string[];
        drops?: string[];
    }>;
}

export class DagWebview implements vscode.Disposable {
    private panel: vscode.WebviewPanel | undefined;
    private readonly disposables: vscode.Disposable[] = [];
    private currentWorkflowName: string | undefined;
    private webviewReady = false;
    private pendingReactPayload: DagUpdatePayload | undefined;
    private activeMode: DagRendererMode | undefined;

    constructor(
        private readonly context: vscode.ExtensionContext,
        private readonly model: WorkflowModel
    ) {
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
            }),
            vscode.workspace.onDidChangeConfiguration((e) => {
                if (
                    this.panel &&
                    (e.affectsConfiguration('agentActions.dagLayout') ||
                        e.affectsConfiguration('agentActions.dagRenderer'))
                ) {
                    this.update();
                }
            })
        );
    }

    dispose(): void {
        this.panel?.dispose();
        this.disposables.forEach((d) => d.dispose());
    }

    async show(): Promise<void> {
        const workflows = this.model.getWorkflows();

        if (workflows.length === 0) {
            vscode.window.showInformationMessage('No Agent Actions workflow detected.');
            return;
        }

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

    showWorkflow(workflow: WorkflowInfo): void {
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
                    localResourceRoots: [this.context.extensionUri],
                }
            );

            this.panel.onDidDispose(() => {
                this.panel = undefined;
                this.currentWorkflowName = undefined;
                this.webviewReady = false;
                this.pendingReactPayload = undefined;
                this.activeMode = undefined;
            }, null, this.disposables);

            this.panel.webview.onDidReceiveMessage(
                (message) => {
                    if (!message || typeof message !== 'object') {
                        return;
                    }
                    if (message.type === 'ready') {
                        this.onWebviewReady();
                        return;
                    }
                    if (message.type === 'openAction') {
                        const actionName = message.actionName;
                        if (typeof actionName !== 'string' || actionName.length === 0) {
                            logger.warn('DAG webview: openAction ignored (invalid actionName)');
                            return;
                        }
                        const action = this.model.getActionByName(actionName);
                        if (action) {
                            vscode.commands.executeCommand('agentActions.openConfig', action);
                        } else {
                            logger.warn(`DAG webview: openAction for unknown action "${actionName}"`);
                            vscode.window.showWarningMessage(`Action "${actionName}" not found`);
                        }
                    }
                },
                null,
                this.disposables
            );

            logger.debug('DAG webview: panel created');
        }

        this.panel.title = `${workflow.name} - Workflow DAG`;
        this.update();
    }

    private getRendererMode(): DagRendererMode {
        const v = vscode.workspace
            .getConfiguration('agentActions')
            .get<string>('dagRenderer', 'reactflow');
        return v === 'mermaid' ? 'mermaid' : 'reactflow';
    }

    private onWebviewReady(): void {
        this.webviewReady = true;
        if (!this.panel) {
            return;
        }
        const payload = this.pendingReactPayload ?? this.buildReactPayload();
        this.pendingReactPayload = undefined;
        this.panel.webview.postMessage({ type: 'dag:update', payload });
        logger.debug(
            `DAG webview: ready → dag:update (${payload.workflowName}, ${payload.actions.length} actions)`
        );
    }

    private update(): void {
        if (!this.panel) {
            return;
        }

        const workflows = this.model.getWorkflows();
        const workflow = this.currentWorkflowName
            ? workflows.find((w) => w.name === this.currentWorkflowName) ?? workflows[0]
            : workflows[0];

        if (!workflow) {
            return;
        }

        const mode = this.getRendererMode();

        if (mode === 'mermaid') {
            this.webviewReady = false;
            this.pendingReactPayload = undefined;
            if (this.activeMode !== 'mermaid') {
                this.activeMode = 'mermaid';
            }
            const config = vscode.workspace.getConfiguration('agentActions');
            const layout = config.get<string>('dagLayout', 'vertical');
            const direction = layout === 'horizontal' ? 'LR' : 'TD';
            const diagram = this.buildMermaidDiagram(workflow.actions, direction);
            const isDark =
                vscode.window.activeColorTheme.kind === vscode.ColorThemeKind.Dark ||
                vscode.window.activeColorTheme.kind === vscode.ColorThemeKind.HighContrast;
            this.panel.webview.html = this.renderMermaidHtml(
                this.panel.webview,
                diagram,
                workflow.name,
                isDark
            );
            return;
        }

        // React Flow path
        if (this.activeMode !== 'reactflow') {
            this.activeMode = 'reactflow';
            this.webviewReady = false;
            this.pendingReactPayload = undefined;
            this.panel.webview.html = renderReactDagShell(this.panel.webview, this.context.extensionUri);
            logger.debug('DAG webview: React shell loaded');
        }

        const payload = this.buildReactPayload();
        if (this.webviewReady) {
            this.panel.webview.postMessage({ type: 'dag:update', payload });
            logger.debug(
                `DAG webview: dag:update (${payload.workflowName}, ${payload.actions.length} actions)`
            );
        } else {
            this.pendingReactPayload = payload;
        }
    }

    private buildReactPayload(): DagUpdatePayload {
        const workflows = this.model.getWorkflows();
        const workflow = this.currentWorkflowName
            ? workflows.find((w) => w.name === this.currentWorkflowName) ?? workflows[0]
            : workflows[0];
        if (!workflow) {
            return { workflowName: '', layout: 'vertical', actions: [] };
        }
        const config = vscode.workspace.getConfiguration('agentActions');
        const layout = config.get<string>('dagLayout', 'vertical') === 'horizontal' ? 'horizontal' : 'vertical';

        return {
            workflowName: workflow.name,
            layout,
            actions: workflow.actions.map((a) => ({
                name: a.name,
                deps: [...a.dependencies],
                kind: 'tool' as const,
                status: a.status,
                outputFields: [...a.outputFields],
            })),
        };
    }

    private buildMermaidDiagram(actions: ActionInfo[], direction: string): string {
        if (actions.length === 0) {
            return `flowchart ${direction}\n  empty["No actions detected"]`;
        }

        const lines: string[] = [`flowchart ${direction}`];

        for (const action of actions) {
            const nodeId = this.sanitizeId(action.name);
            const label = action.name.replace(/["\]\\]/g, '_');
            const statusClass = this.getStatusClass(action.status);

            lines.push(`  ${nodeId}["[${action.index}] ${label}"]:::${statusClass}`);
        }

        for (const action of actions) {
            const nodeId = this.sanitizeId(action.name);
            for (const dep of action.dependencies) {
                const depId = this.sanitizeId(dep);
                lines.push(`  ${depId} --> ${nodeId}`);
            }
        }

        for (const action of actions) {
            const nodeId = this.sanitizeId(action.name);
            const sanitizedName = this.sanitizeForCallback(action.name);
            lines.push(`  click ${nodeId} callback "${sanitizedName}"`);
        }

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

    private sanitizeForCallback(name: string): string {
        return name.replace(/[<>"'`\\]/g, '').replace(/\s+/g, '_');
    }

    private getStatusClass(status: ActionStatus): string {
        return status;
    }

    private renderMermaidHtml(
        webview: vscode.Webview,
        diagram: string,
        workflowName: string,
        isDark: boolean
    ): string {
        const nonce = getNonce();

        const mermaidUri = webview.asWebviewUri(
            vscode.Uri.joinPath(this.context.extensionUri, 'media', 'mermaid.min.js')
        );

        return `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src ${webview.cspSource} 'nonce-${nonce}'; style-src 'unsafe-inline';">
    <title>${escapeHtml(workflowName)} - Workflow DAG</title>
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
        .mermaid {
            display: flex;
            justify-content: center;
            padding: 16px;
        }
        .mermaid svg {
            max-width: 100%;
            height: auto;
        }
        .node { cursor: pointer; }
        .node:hover rect, .node:hover polygon {
            filter: brightness(1.2);
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>${escapeHtml(workflowName)}</h1>
        <div class="legend">
            <div class="legend-item"><div class="legend-dot completed"></div> Completed</div>
            <div class="legend-item"><div class="legend-dot running"></div> Running</div>
            <div class="legend-item"><div class="legend-dot failed"></div> Failed</div>
            <div class="legend-item"><div class="legend-dot pending"></div> Pending</div>
            <div class="legend-item"><div class="legend-dot skipped"></div> Skipped</div>
        </div>
    </div>
    <div class="mermaid">
${diagram}
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

        window.callback = function(actionName) {
            if (/^[a-zA-Z0-9_-]+$/.test(actionName)) {
                vscode.postMessage({ type: 'openAction', actionName });
            }
        };
    </script>
</body>
</html>`;
    }
}

function renderReactDagShell(webview: vscode.Webview, extensionUri: vscode.Uri): string {
    const nonce = getNonce();
    const scriptUri = webview.asWebviewUri(vscode.Uri.joinPath(extensionUri, 'out', 'dagWebview.js'));
    const styleBaseUri = webview.asWebviewUri(vscode.Uri.joinPath(extensionUri, 'out', 'webview.css'));
    const dagStyleUri = webview.asWebviewUri(vscode.Uri.joinPath(extensionUri, 'out', 'dagWebview.css'));
    const csp = [
        `default-src 'none'`,
        `style-src ${webview.cspSource} 'unsafe-inline'`,
        `script-src 'nonce-${nonce}' ${webview.cspSource}`,
        `img-src ${webview.cspSource} data:`,
        `font-src ${webview.cspSource}`,
    ].join('; ');

    return `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta http-equiv="Content-Security-Policy" content="${csp}">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link rel="stylesheet" href="${styleBaseUri}">
    <link rel="stylesheet" href="${dagStyleUri}">
    <title>Workflow DAG</title>
    <style>
        html, body { height: 100%; margin: 0; }
        #root { height: 100%; }
    </style>
</head>
<body>
    <div id="root"></div>
    <script nonce="${nonce}" src="${scriptUri}"></script>
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
