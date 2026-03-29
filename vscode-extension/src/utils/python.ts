import * as vscode from 'vscode';

export async function resolvePythonPath(): Promise<string> {
    const config = vscode.workspace.getConfiguration('agentActions');
    const configuredPath = config.get<string>('pythonPath')?.trim();
    if (configuredPath) {
        return configuredPath;
    }

    const pythonExt = vscode.extensions.getExtension('ms-python.python');
    if (pythonExt) {
        if (!pythonExt.isActive) {
            await pythonExt.activate();
        }
        const pythonApi = pythonExt.exports as {
            environments?: {
                getActiveEnvironmentPath?: () => { path?: string };
            };
        };
        const envPath = pythonApi?.environments?.getActiveEnvironmentPath?.();
        if (envPath?.path) {
            return envPath.path;
        }
    }

    const pythonConfig = vscode.workspace.getConfiguration('python');
    const defaultInterpreterPath = pythonConfig.get<string>('defaultInterpreterPath');
    if (defaultInterpreterPath) {
        return defaultInterpreterPath;
    }

    return 'python3';
}
