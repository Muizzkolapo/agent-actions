/**
 * Agent Actions VS Code Extension
 *
 * Provides language support (LSP) and workflow navigation for Agent Actions projects.
 * Combines the old extension's full UX with the new lifecycle serialization.
 */

import * as vscode from 'vscode';
import {
    LanguageClient,
    LanguageClientOptions,
    ServerOptions,
    TransportKind,
} from 'vscode-languageclient/node';
import { PythonExtension } from '@vscode/python-extension';
import { logger, initializeLogger } from './utils/logger';

// Model
import { WorkflowModel } from './model/workflowModel';

// Providers
import { WorkflowTreeProvider } from './providers/treeViewProvider';
import { WorkflowCodeLensProvider } from './providers/codeLensProvider';
import { ActionDecorationProvider } from './providers/decorationProvider';
import { WorkflowStatusBar } from './providers/statusBarProvider';
import { DataPreviewProvider, DATA_PREVIEW_SCHEME } from './providers/dataPreviewProvider';
import { ExtensionInfoProvider } from './providers/extensionInfoProvider';
import { HelpProvider } from './providers/helpProvider';

// Views
import { DagWebview } from './views/dagWebview';
import { QueryResultsPanel } from './views/queryResultsPanel';

// Commands
import { registerCommands } from './commands/index';

let client: LanguageClient | undefined;
let outputChannel: vscode.OutputChannel;

// Lifecycle serialization — prevents concurrent start/stop cycles
let lifecycleQueue: Promise<void> = Promise.resolve();
let lifecyclePending = 0;
let disposed = false;

// Debounce for Python interpreter change events
let debounceTimer: ReturnType<typeof setTimeout> | undefined;
const DEBOUNCE_MS = 300;
const ACTIVATION_TIMEOUT_MS = 10_000;
const MODULE_ARGS = ['-m', 'agent_actions.tooling.lsp.server', '--stdio'];

// ── LSP lifecycle (from PR #44) ──────────────────────────────────────

async function getPythonPath(): Promise<string | undefined> {
    try {
        const api = await PythonExtension.api();
        const envPath = api.environments.getActiveEnvironmentPath();
        if (!envPath) return undefined;
        const env = await api.environments.resolveEnvironment(envPath);
        return env?.executable.uri?.fsPath;
    } catch {
        outputChannel.appendLine('Python extension not available; skipping interpreter discovery.');
        return undefined;
    }
}

async function resolveServerOptions(): Promise<ServerOptions> {
    const config = vscode.workspace.getConfiguration('agentActions');

    // 1. Explicit serverPath override
    const serverPath: string = config.get('serverPath') || '';
    if (serverPath && serverPath !== 'agac-lsp') {
        outputChannel.appendLine(`Using explicit server path: ${serverPath}`);
        return { command: serverPath, args: ['--stdio'], transport: TransportKind.stdio };
    }

    // 2. Explicit interpreter setting
    const interpreter: string[] = config.get('interpreter') || [];
    if (interpreter.length > 0) {
        outputChannel.appendLine(`Using interpreter from setting: ${interpreter[0]}`);
        return { command: interpreter[0], args: MODULE_ARGS, transport: TransportKind.stdio };
    }

    // 3. Legacy pythonPath setting
    const pythonPath = config.get<string>('pythonPath')?.trim();
    if (pythonPath) {
        outputChannel.appendLine(`Using Python from setting: ${pythonPath}`);
        return { command: pythonPath, args: MODULE_ARGS, transport: TransportKind.stdio };
    }

    // 4. Python extension API
    const extensionPath = await getPythonPath();
    if (extensionPath) {
        outputChannel.appendLine(`Using Python from extension: ${extensionPath}`);
        return { command: extensionPath, args: MODULE_ARGS, transport: TransportKind.stdio };
    }

    // 5. Fall back to agac-lsp on PATH
    outputChannel.appendLine('Falling back to agac-lsp on PATH');
    return { command: 'agac-lsp', args: ['--stdio'], transport: TransportKind.stdio };
}

async function startClient(context: vscode.ExtensionContext): Promise<void> {
    const serverOptions = await resolveServerOptions();

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
        outputChannel,
    };

    client = new LanguageClient('agentActionsLsp', 'Agent Actions LSP', serverOptions, clientOptions);

    const startPromise = client.start();
    let timer: NodeJS.Timeout | undefined;
    const timeoutPromise = new Promise<never>((_, reject) => {
        timer = setTimeout(
            () => reject(new Error(`LSP server did not respond within ${ACTIVATION_TIMEOUT_MS / 1000}s`)),
            ACTIVATION_TIMEOUT_MS
        );
    });

    try {
        await Promise.race([startPromise, timeoutPromise]);
        outputChannel.appendLine('LSP server started successfully.');
    } catch (err) {
        client.stop().catch((e) => outputChannel.appendLine(`Stop error: ${e}`));
        client = undefined;
        throw err;
    } finally {
        if (timer) clearTimeout(timer);
    }
}

function restartServer(context: vscode.ExtensionContext): Promise<void> {
    if (lifecyclePending > 0) {
        outputChannel.appendLine('LSP restart requested (queued behind in-flight cycle).');
    }
    lifecyclePending++;
    const cycle = lifecycleQueue.then(async () => {
        try {
            if (disposed) {
                outputChannel.appendLine('LSP lifecycle: skipped (extension disposing).');
                return;
            }
            outputChannel.appendLine('LSP lifecycle: starting...');
            if (client) {
                await client.stop();
                client = undefined;
            }
            await startClient(context);
            outputChannel.appendLine('LSP lifecycle: started.');
        } catch (err: unknown) {
            client = undefined;
            const msg = err instanceof Error ? err.message : String(err);
            outputChannel.appendLine(`LSP lifecycle: failed — ${msg}`);
            throw err;
        } finally {
            lifecyclePending--;
        }
    });

    lifecycleQueue = cycle.catch(() => {});
    return cycle;
}

// ── Activation ───────────────────────────────────────────────────────

export async function activate(context: vscode.ExtensionContext): Promise<void> {
    initializeLogger(context);
    outputChannel = vscode.window.createOutputChannel('Agent Actions');
    context.subscriptions.push(outputChannel);
    logger.info('Activating Agent Actions extension');

    // ── Interpreter change listener (debounced) ──
    try {
        const pythonApi = await PythonExtension.api();
        context.subscriptions.push(
            pythonApi.environments.onDidChangeActiveEnvironmentPath(() => {
                if (debounceTimer) clearTimeout(debounceTimer);
                debounceTimer = setTimeout(() => {
                    debounceTimer = undefined;
                    outputChannel.appendLine('Python interpreter changed; scheduling LSP restart...');
                    restartServer(context).catch((err: unknown) => {
                        const msg = err instanceof Error ? err.message : String(err);
                        outputChannel.appendLine(`Restart after interpreter change failed: ${msg}`);
                    });
                }, DEBOUNCE_MS);
            })
        );
    } catch {
        outputChannel.appendLine('Python extension not available; interpreter change detection disabled.');
    }

    // ── Workflow Model ──
    const workflowModel = new WorkflowModel();
    context.subscriptions.push(workflowModel);
    await workflowModel.refresh();

    // ── UI Providers ──

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

    // Query Results Panel
    const queryResultsPanel = new QueryResultsPanel(context.extensionUri, context);
    context.subscriptions.push(queryResultsPanel);

    // Data Preview Provider
    const dataPreviewProvider = new DataPreviewProvider();
    context.subscriptions.push(
        dataPreviewProvider,
        vscode.workspace.registerTextDocumentContentProvider(DATA_PREVIEW_SCHEME, dataPreviewProvider)
    );

    // Extension Info Panel (getter because client is nullable during restarts)
    const infoProvider = new ExtensionInfoProvider(() => client, context);
    context.subscriptions.push(
        infoProvider,
        vscode.window.registerTreeDataProvider('agentActionsInfo', infoProvider),
    );

    // Help Panel
    const helpProvider = new HelpProvider();
    context.subscriptions.push(
        vscode.window.registerTreeDataProvider('agentActionsHelp', helpProvider),
    );

    // ── Commands ──
    registerCommands({
        context,
        model: workflowModel,
        dagWebview,
        queryResultsPanel,
    });

    // Restart LSP command
    context.subscriptions.push(
        vscode.commands.registerCommand('agentActions.restartServer', async () => {
            try {
                await restartServer(context);
                vscode.window.showInformationMessage('Agent Actions LSP restarted.');
            } catch (err: unknown) {
                const msg = err instanceof Error ? err.message : String(err);
                vscode.window.showErrorMessage(`Agent Actions: restart failed — ${msg}`);
            }
        })
    );

    // ── Auto-reveal sidebar ──
    const config = vscode.workspace.getConfiguration('agentActions');
    if (config.get<boolean>('autoRevealSidebar', false) && workflowModel.hasAgentProject()) {
        vscode.commands.executeCommand('workbench.view.extension.agentActions');
    }

    // ── Start LSP ──
    try {
        await restartServer(context);
    } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : String(err);
        outputChannel.appendLine(`Activation error: ${msg}`);
        vscode.window.showErrorMessage(
            `Agent Actions LSP failed to start: ${msg}\n` +
            `Ensure agent-actions is installed (pip install agent-actions) ` +
            `and either the Python extension is active or agac-lsp is on your PATH.`
        );
    }

    logger.info('Agent Actions extension activated');
}

// ── Deactivation ─────────────────────────────────────────────────────

export function deactivate(): Thenable<void> | undefined {
    disposed = true;
    if (debounceTimer) {
        clearTimeout(debounceTimer);
        debounceTimer = undefined;
    }
    lifecycleQueue = lifecycleQueue.then(async () => {
        if (client) {
            try {
                await client.stop();
            } catch (err) {
                outputChannel.appendLine(`Shutdown error: ${err}`);
            }
            client = undefined;
        }
    });
    return lifecycleQueue;
}
