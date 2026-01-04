import * as vscode from 'vscode';
import {
    LanguageClient,
    LanguageClientOptions,
    ServerOptions,
} from 'vscode-languageclient/node';

let client: LanguageClient;

export function activate(context: vscode.ExtensionContext) {
    // Server options - run the agac-lsp command directly
    // After `pip install agent-actions`, agac-lsp is in PATH
    const serverOptions: ServerOptions = {
        command: 'agac-lsp',
        args: ['--stdio'],
    };

    console.log('Starting Agent Actions LSP server with: agac-lsp --stdio');

    // Client options
    const clientOptions: LanguageClientOptions = {
        documentSelector: [
            { scheme: 'file', language: 'yaml', pattern: '**/agent_config/**/*.yml' },
            { scheme: 'file', language: 'yaml', pattern: '**/agent_workflow/**/*.yml' },
            { scheme: 'file', language: 'markdown', pattern: '**/prompt_store/**/*.md' }
        ],
        synchronize: {
            fileEvents: [
                vscode.workspace.createFileSystemWatcher('**/agent_config/**/*.yml'),
                vscode.workspace.createFileSystemWatcher('**/prompt_store/**/*.md'),
                vscode.workspace.createFileSystemWatcher('**/tools/**/*.py'),
                vscode.workspace.createFileSystemWatcher('**/schema/**/*.yml')
            ]
        }
    };

    // Create and start the client
    client = new LanguageClient(
        'agentActionsLsp',
        'Agent Actions LSP',
        serverOptions,
        clientOptions
    );

    // Start the client
    client.start();

    console.log('Agent Actions LSP extension activated');
}

export function deactivate(): Thenable<void> | undefined {
    if (!client) {
        return undefined;
    }
    return client.stop();
}
