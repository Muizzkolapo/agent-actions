/**
 * Agent Actions VS Code Extension
 *
 * Provides language support (LSP) and workflow navigation for Agent Actions projects.
 *
 * This is a consolidated implementation combining the best approaches from PRs #820-823:
 * - PR #820: Multi-project support, comprehensive package.json contributions
 * - PR #821: Clean event patterns
 * - PR #822: Centralized command registration
 * - PR #823: agent_status.json support, polling, multi-workflow support
 */

import * as vscode from 'vscode';
import {
    LanguageClient,
    LanguageClientOptions,
    ServerOptions,
} from 'vscode-languageclient/node';
import { logger, initializeLogger } from './utils/logger';
import { resolvePythonPath } from './utils/python';

// Model
import { WorkflowModel } from './model/workflowModel';

// Providers
import { WorkflowTreeProvider } from './providers/treeViewProvider';
import { WorkflowCodeLensProvider } from './providers/codeLensProvider';
import { ActionDecorationProvider } from './providers/decorationProvider';
import { WorkflowStatusBar } from './providers/statusBarProvider';
import { DataPreviewProvider, DATA_PREVIEW_SCHEME } from './providers/dataPreviewProvider';

// Views
import { DagWebview } from './views/dagWebview';

// Commands
import { registerCommands } from './commands/index';

let client: LanguageClient;

/**
 * Activate the extension
 */
export async function activate(context: vscode.ExtensionContext): Promise<void> {
    initializeLogger(context);
    logger.info('Activating Agent Actions extension');

    // ========================================
    // 1. Initialize LSP Client
    // ========================================
    const pythonPath = await resolvePythonPath();

    const serverOptions: ServerOptions = {
        command: pythonPath,
        args: ['-m', 'agent_actions.tooling.lsp.server', '--stdio'],
    };

    logger.debug('Starting LSP server', { pythonPath, args: ['-m', 'agent_actions.tooling.lsp.server', '--stdio'] });

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

    // Data Preview Provider (for viewing storage backend data)
    const dataPreviewProvider = new DataPreviewProvider();
    context.subscriptions.push(
        dataPreviewProvider,
        vscode.workspace.registerTextDocumentContentProvider(DATA_PREVIEW_SCHEME, dataPreviewProvider)
    );

    // ========================================
    // 4. Register Commands
    // ========================================
    registerCommands({
        context,
        model: workflowModel,
        dagWebview,
        dataPreviewProvider,
    });

    logger.info('Agent Actions extension activated');
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
