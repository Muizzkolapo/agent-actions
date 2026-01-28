/**
 * Agent Actions VS Code Extension
 *
 * Provides language support (LSP) and workflow navigation for Agent Actions projects.
 *
 * This is a consolidated implementation combining the best approaches from PRs #820-823:
 * - PR #820: Multi-project support, comprehensive package.json contributions
 * - PR #821: Clean event patterns, viewOutput command
 * - PR #822: Centralized command registration
 * - PR #823: agent_status.json support, polling, multi-workflow support
 */

import * as vscode from 'vscode';
import {
    LanguageClient,
    LanguageClientOptions,
    ServerOptions,
} from 'vscode-languageclient/node';

// Model
import { WorkflowModel } from './model/workflowModel';

// Providers
import { WorkflowTreeProvider } from './providers/treeViewProvider';
import { WorkflowCodeLensProvider } from './providers/codeLensProvider';
import { ActionDecorationProvider } from './providers/decorationProvider';
import { WorkflowStatusBar } from './providers/statusBarProvider';

// Views
import { DagWebview } from './views/dagWebview';

// Commands
import { registerCommands } from './commands/index';

let client: LanguageClient;

/**
 * Get Python interpreter path for LSP server
 */
async function getPythonPath(): Promise<string> {
    // Try VS Code Python extension first
    const pythonExt = vscode.extensions.getExtension('ms-python.python');
    if (pythonExt) {
        if (!pythonExt.isActive) {
            await pythonExt.activate();
        }
        const pythonApi = pythonExt.exports;
        const envPath = pythonApi?.environments?.getActiveEnvironmentPath?.();
        if (envPath?.path) {
            return envPath.path;
        }
    }

    // Check extension settings
    const config = vscode.workspace.getConfiguration('agentActions');
    const configPath = config.get<string>('pythonPath');
    if (configPath) {
        return configPath;
    }

    // Default to python3
    return 'python3';
}

/**
 * Activate the extension
 */
export async function activate(context: vscode.ExtensionContext): Promise<void> {
    console.log('Activating Agent Actions extension...');

    // ========================================
    // 1. Initialize LSP Client
    // ========================================
    const pythonPath = await getPythonPath();

    const serverOptions: ServerOptions = {
        command: pythonPath,
        args: ['-m', 'agent_actions.lsp.server', '--stdio'],
    };

    console.log(`Starting Agent Actions LSP server with: ${pythonPath} -m agent_actions.lsp.server --stdio`);

    const clientOptions: LanguageClientOptions = {
        documentSelector: [
            { scheme: 'file', language: 'yaml', pattern: '**/agent_config/**/*.yml' },
            { scheme: 'file', language: 'yaml', pattern: '**/agent_config/**/*.yaml' },
            { scheme: 'file', language: 'yaml', pattern: '**/agent_workflow/**/*.yml' },
            { scheme: 'file', language: 'markdown', pattern: '**/prompt_store/**/*.md' },
        ],
        synchronize: {
            fileEvents: [
                vscode.workspace.createFileSystemWatcher('**/agent_config/**/*.yml'),
                vscode.workspace.createFileSystemWatcher('**/agent_config/**/*.yaml'),
                vscode.workspace.createFileSystemWatcher('**/prompt_store/**/*.md'),
                vscode.workspace.createFileSystemWatcher('**/tools/**/*.py'),
                vscode.workspace.createFileSystemWatcher('**/schema/**/*.yml'),
            ],
        },
    };

    client = new LanguageClient(
        'agentActionsLsp',
        'Agent Actions LSP',
        serverOptions,
        clientOptions
    );

    // Add client to disposables to ensure proper cleanup
    context.subscriptions.push(client);
    client.start();

    // ========================================
    // 2. Initialize Workflow Model
    // ========================================
    const workflowModel = new WorkflowModel();
    context.subscriptions.push(workflowModel);

    // Initial refresh
    await workflowModel.refresh();

    // ========================================
    // 3. Initialize UI Providers
    // ========================================

    // Tree View
    const treeProvider = new WorkflowTreeProvider(workflowModel);
    const treeView = vscode.window.createTreeView('agentActionsWorkflow', {
        treeDataProvider: treeProvider,
        showCollapseAll: true,
    });
    context.subscriptions.push(treeProvider, treeView);

    // CodeLens
    const codeLensProvider = new WorkflowCodeLensProvider(workflowModel);
    const codeLensSelector: vscode.DocumentSelector = [
        { scheme: 'file', language: 'yaml', pattern: '**/agent_config/**/*.yml' },
        { scheme: 'file', language: 'yaml', pattern: '**/agent_config/**/*.yaml' },
    ];
    context.subscriptions.push(
        codeLensProvider,
        vscode.languages.registerCodeLensProvider(codeLensSelector, codeLensProvider)
    );

    // File Decorations
    const decorationProvider = new ActionDecorationProvider(workflowModel);
    context.subscriptions.push(
        decorationProvider,
        vscode.window.registerFileDecorationProvider(decorationProvider)
    );

    // Status Bar
    const statusBar = new WorkflowStatusBar(workflowModel);
    context.subscriptions.push(statusBar);

    // DAG Webview
    const dagWebview = new DagWebview(context, workflowModel);
    context.subscriptions.push(dagWebview);

    // ========================================
    // 4. Register Commands
    // ========================================
    registerCommands({
        context,
        model: workflowModel,
        dagWebview,
    });

    console.log('Agent Actions extension activated with Workflow Navigator');
}

/**
 * Deactivate the extension
 */
export function deactivate(): Thenable<void> | undefined {
    if (!client) {
        return undefined;
    }
    return client.stop();
}
