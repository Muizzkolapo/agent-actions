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
        // Auto-update when model changes
        this.disposables.push(
            this.model.onDidChange(() => {
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
        this.panel.webview.html = this.renderHtml(this.panel.webview, diagram, workflow.name);
    }

    private buildMermaidDiagram(actions: ActionInfo[], direction: string): string {
        if (actions.length === 0) {
            return `flowchart ${direction}\n  empty["No actions detected"]`;
        }

        const lines: string[] = [`flowchart ${direction}`];

        // Define nodes with status styling
        for (const action of actions) {
            const nodeId = this.sanitizeId(action.name);
            const label = `${action.name}`;
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

    private renderHtml(webview: vscode.Webview, diagram: string, workflowName: string): string {
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
    <title>${workflowName} - Workflow DAG</title>
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
        /* Make nodes clickable */
        .node { cursor: pointer; }
        .node:hover rect, .node:hover polygon {
            filter: brightness(1.2);
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>${workflowName}</h1>
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
            theme: 'dark',
            flowchart: {
                curve: 'basis',
                htmlLabels: false,  // Disable HTML labels for security
                padding: 15
            },
            securityLevel: 'strict'
        });

        // Handle click events - Mermaid will call this via the callback mechanism
        // With securityLevel: 'strict', we use mermaid's built-in click handler
        window.callback = function(actionName) {
            // Validate actionName contains only safe characters
            if (/^[a-zA-Z0-9_-]+$/.test(actionName)) {
                vscode.postMessage({ type: 'openAction', actionName });
            }
        };
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
}
