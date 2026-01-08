import * as vscode from 'vscode';
import {
    LanguageClient,
    LanguageClientOptions,
    ServerOptions,
} from 'vscode-languageclient/node';

let client: LanguageClient;

async function getPythonPath(): Promise<string> {
    // Try to get Python path from VS Code's Python extension
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

    // Fallback: check config, then common paths
    const config = vscode.workspace.getConfiguration('agentActions');
    const configPath = config.get<string>('pythonPath');
    if (configPath) {
        return configPath;
    }

    // Default to python3 (more reliable on macOS/Linux)
    return 'python3';
}

export async function activate(_context: vscode.ExtensionContext) {
    const pythonPath = await getPythonPath();

    // Server options - run the LSP server
    const serverOptions: ServerOptions = {
        command: pythonPath,
        args: ['-m', 'agent_actions.lsp.server', '--stdio'],
    };

    console.log(`Starting Agent Actions LSP server with: ${pythonPath} -m agent_actions.lsp.server --stdio`);

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
