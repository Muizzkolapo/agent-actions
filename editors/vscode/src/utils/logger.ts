/**
 * Centralized Logger for Agent Actions VS Code Extension
 *
 * Provides a unified logging interface that:
 * - Writes to VS Code's Output panel for user visibility
 * - Supports configurable log levels (debug, info, warn, error, off)
 * - Responds to runtime configuration changes
 * - Handles error formatting consistently across the extension
 * - Supports lazy initialization for cleaner module loading
 *
 * @example
 * ```typescript
 * import { logger } from './utils/logger';
 *
 * logger.info('Extension activated');
 * logger.debug('Processing file', { path: uri.fsPath });
 * logger.error('Failed to parse config', error);
 * ```
 */

import * as vscode from 'vscode';

// ============================================================================
// Types
// ============================================================================

/**
 * Available log levels in order of increasing severity.
 * - debug: Verbose output for development/troubleshooting
 * - info: General operational messages
 * - warn: Potential issues that don't prevent operation
 * - error: Failures that affect functionality
 * - off: Disable all logging
 */
export type LogLevel = 'debug' | 'info' | 'warn' | 'error' | 'off';

/** Numeric priority for log level comparison */
const LOG_LEVEL_PRIORITY: Readonly<Record<LogLevel, number>> = {
    debug: 0,
    info: 1,
    warn: 2,
    error: 3,
    off: 4,
};

/** Valid log levels that produce output (excludes 'off') */
type OutputLogLevel = Exclude<LogLevel, 'off'>;

// ============================================================================
// State
// ============================================================================

/** Lazily initialized output channel */
let outputChannel: vscode.OutputChannel | undefined;

/** Current log level threshold */
let currentLogLevel: LogLevel = 'info';

/** Disposable for configuration change listener */
let configChangeDisposable: vscode.Disposable | undefined;

// ============================================================================
// Internal Helpers
// ============================================================================

/**
 * Gets or creates the output channel (lazy initialization).
 * This avoids creating the channel at module load time, which can cause
 * issues if the module is imported before VS Code is fully initialized.
 * Returns undefined if VS Code APIs are not available.
 */
function getOutputChannel(): vscode.OutputChannel | undefined {
    if (!outputChannel) {
        try {
            outputChannel = vscode.window.createOutputChannel('Agent Actions');
        } catch {
            // VS Code not ready - fall through to return undefined
        }
    }
    return outputChannel;
}

/**
 * Reads the configured log level from VS Code settings.
 * Returns 'info' if the configured value is invalid or VS Code is not ready.
 */
function getConfiguredLogLevel(): LogLevel {
    try {
        const config = vscode.workspace.getConfiguration('agentActions');
        const level = config.get<string>('logLevel', 'info');

        // Validate the configured level
        if (level in LOG_LEVEL_PRIORITY) {
            return level as LogLevel;
        }
    } catch {
        // VS Code workspace not ready - use default
    }

    return 'info';
}

/**
 * Synchronizes the internal log level with the user's configuration.
 */
function syncLogLevelFromConfig(): void {
    const previousLevel = currentLogLevel;
    currentLogLevel = getConfiguredLogLevel();

    // Log level changes at info level so users see confirmation
    if (previousLevel !== currentLogLevel && currentLogLevel !== 'off') {
        writeLog('info', `Log level changed: ${previousLevel} → ${currentLogLevel}`);
    }
}

/**
 * Determines if a message at the given level should be logged
 * based on the current threshold.
 */
function shouldLog(level: OutputLogLevel): boolean {
    return LOG_LEVEL_PRIORITY[level] >= LOG_LEVEL_PRIORITY[currentLogLevel];
}

/**
 * Formats a timestamp for log entries.
 * Uses compact ISO format (date + time) for cross-day debugging.
 */
function formatTimestamp(): string {
    // Format: MM-DD HH:MM:SS (compact but includes date for multi-day debugging)
    const now = new Date();
    const month = String(now.getMonth() + 1).padStart(2, '0');
    const day = String(now.getDate()).padStart(2, '0');
    const time = now.toISOString().slice(11, 19);
    return `${month}-${day} ${time}`;
}

/**
 * Writes a formatted log entry to the output channel.
 * Falls back to console if OutputChannel is unavailable.
 */
function writeLog(level: OutputLogLevel, message: string, context?: unknown): void {
    if (!shouldLog(level)) {
        return;
    }

    const timestamp = formatTimestamp();
    const levelTag = level.toUpperCase().padEnd(5);
    const contextSuffix = context !== undefined ? ` ${formatContext(context)}` : '';
    const logLine = `[${timestamp}] [${levelTag}] ${message}${contextSuffix}`;

    const channel = getOutputChannel();
    if (channel) {
        channel.appendLine(logLine);
    } else {
        // Fallback to console if OutputChannel unavailable
        const consoleFn = level === 'error' ? console.error : level === 'warn' ? console.warn : console.log;
        consoleFn(`[Agent Actions] ${logLine}`);
    }
}

// ============================================================================
// Public API - Formatting Utilities
// ============================================================================

/**
 * Formats an error or unknown value for logging.
 * Extracts the message from Error objects, or stringifies other values.
 *
 * @param error - The error or value to format
 * @returns A formatted string representation
 *
 * @example
 * ```typescript
 * try {
 *   await riskyOperation();
 * } catch (error) {
 *   logger.error(`Operation failed: ${formatError(error)}`);
 * }
 * ```
 */
export function formatError(error: unknown): string {
    if (error === null || error === undefined) {
        return 'Unknown error';
    }

    if (error instanceof Error) {
        // Include stack trace for better debugging (8 lines for async traces)
        if (error.stack) {
            const stackLines = error.stack.split('\n').slice(0, 8);
            return stackLines.join('\n');
        }
        return error.message;
    }

    if (typeof error === 'string') {
        return error;
    }

    try {
        return JSON.stringify(error);
    } catch {
        return String(error);
    }
}

/**
 * Formats contextual data for logging.
 * Handles objects, arrays, and primitives appropriately.
 */
function formatContext(context: unknown): string {
    if (context instanceof Error) {
        return `| ${formatError(context)}`;
    }

    if (typeof context === 'object' && context !== null) {
        try {
            return `| ${JSON.stringify(context)}`;
        } catch {
            return `| [Object]`;
        }
    }

    return `| ${String(context)}`;
}

// ============================================================================
// Public API - Logger Object
// ============================================================================

/**
 * The main logger interface for the extension.
 *
 * All methods accept a message and optional context (error or additional data).
 * Messages are filtered based on the configured log level.
 */
export const logger = {
    /**
     * Log a debug message. Use for verbose development/troubleshooting info.
     * Only visible when logLevel is set to 'debug'.
     */
    debug(message: string, context?: unknown): void {
        writeLog('debug', message, context);
    },

    /**
     * Log an informational message. Use for general operational messages.
     * Visible at 'debug' and 'info' levels.
     */
    info(message: string, context?: unknown): void {
        writeLog('info', message, context);
    },

    /**
     * Log a warning message. Use for potential issues that don't prevent operation.
     * Visible at 'debug', 'info', and 'warn' levels.
     */
    warn(message: string, context?: unknown): void {
        writeLog('warn', message, context);
    },

    /**
     * Log an error message. Use for failures that affect functionality.
     * Visible at all levels except 'off'.
     */
    error(message: string, context?: unknown): void {
        writeLog('error', message, context);
    },

    /**
     * Brings the Output panel to the foreground and focuses the Agent Actions channel.
     * Useful after logging important messages the user should see immediately.
     */
    show(): void {
        getOutputChannel()?.show(true);
    },

    /**
     * Clears all messages from the output channel.
     * Useful for starting fresh logging sessions.
     */
    clear(): void {
        getOutputChannel()?.clear();
    },
} as const;

// ============================================================================
// Public API - Lifecycle Management
// ============================================================================

/**
 * Initializes the logger and registers it for proper cleanup.
 *
 * This function should be called once during extension activation.
 * It sets up:
 * - Initial log level from configuration
 * - Configuration change listener for runtime updates
 * - Proper disposal when the extension deactivates
 *
 * @param context - The extension context for registering disposables
 *
 * @example
 * ```typescript
 * export async function activate(context: vscode.ExtensionContext) {
 *   initializeLogger(context);
 *   logger.info('Extension activated');
 * }
 * ```
 */
export function initializeLogger(context: vscode.ExtensionContext): void {
    // Set initial log level
    syncLogLevelFromConfig();

    // Listen for configuration changes
    configChangeDisposable = vscode.workspace.onDidChangeConfiguration((event) => {
        if (event.affectsConfiguration('agentActions.logLevel')) {
            syncLogLevelFromConfig();
        }
    });

    // Register all disposables for cleanup
    context.subscriptions.push({
        dispose: disposeLogger,
    });
}

/**
 * Cleans up logger resources.
 * Called automatically when the extension deactivates if initializeLogger was used.
 * Can also be called manually if needed.
 */
export function disposeLogger(): void {
    configChangeDisposable?.dispose();
    configChangeDisposable = undefined;

    outputChannel?.dispose();
    outputChannel = undefined;
}

/**
 * Programmatically sets the log level.
 * Useful for testing or temporary debugging sessions.
 *
 * Note: This does not persist to settings. The level will revert to
 * the configured value if settings change or the extension reloads.
 *
 * @param level - The log level to set
 * @throws Error if an invalid log level is provided
 */
export function setLogLevel(level: LogLevel): void {
    if (!(level in LOG_LEVEL_PRIORITY)) {
        throw new Error(`Invalid log level: ${level}. Valid levels: ${Object.keys(LOG_LEVEL_PRIORITY).join(', ')}`);
    }
    currentLogLevel = level;
}

/**
 * Returns the current effective log level.
 * Useful for conditional logic based on verbosity.
 *
 * @example
 * ```typescript
 * if (getLogLevel() === 'debug') {
 *   // Perform expensive debug-only operations
 * }
 * ```
 */
export function getLogLevel(): LogLevel {
    return currentLogLevel;
}
