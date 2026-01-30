import * as vscode from 'vscode';

type LogLevel = 'debug' | 'info' | 'warn' | 'error';

const outputChannel = vscode.window.createOutputChannel('Agent Actions');
const logLevelOrder: Record<LogLevel, number> = {
    debug: 10,
    info: 20,
    warn: 30,
    error: 40,
};

let currentLogLevel: LogLevel = 'info';

function getConfiguredLogLevel(): LogLevel {
    const config = vscode.workspace.getConfiguration('agentActions');
    const level = config.get<LogLevel>('logLevel', 'info');
    return logLevelOrder[level] ? level : 'info';
}

function setLogLevelFromConfig(): void {
    currentLogLevel = getConfiguredLogLevel();
}

function shouldLog(level: LogLevel): boolean {
    return logLevelOrder[level] >= logLevelOrder[currentLogLevel];
}

function formatError(error?: unknown): string {
    if (!error) {
        return '';
    }
    if (error instanceof Error) {
        return ` ${error.message}`;
    }
    return ` ${String(error)}`;
}

function writeLog(level: LogLevel, message: string, error?: unknown): void {
    if (!shouldLog(level)) {
        return;
    }
    outputChannel.appendLine(`[${level.toUpperCase()}] ${message}${formatError(error)}`);
}

export const logger = {
    debug: (message: string, error?: unknown) => writeLog('debug', message, error),
    info: (message: string, error?: unknown) => writeLog('info', message, error),
    warn: (message: string, error?: unknown) => writeLog('warn', message, error),
    error: (message: string, error?: unknown) => writeLog('error', message, error),
};

export function registerLogger(context: vscode.ExtensionContext): void {
    setLogLevelFromConfig();
    context.subscriptions.push(outputChannel);
    context.subscriptions.push(
        vscode.workspace.onDidChangeConfiguration((event) => {
            if (event.affectsConfiguration('agentActions.logLevel')) {
                setLogLevelFromConfig();
            }
        })
    );
}
