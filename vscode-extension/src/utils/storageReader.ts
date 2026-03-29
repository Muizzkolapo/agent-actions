/**
 * Storage Backend Reader for Data Preview
 */

import * as vscode from 'vscode';
import { resolvePythonPath } from './python';
import { transformKeys, getString, getNumber, getObject } from './caseTransform';

/**
 * Preview result with pagination info
 */
export interface PreviewResult {
    records: unknown[];
    totalCount: number;
    nodeName: string;
    files: string[];
    storagePath: string;
    backendType: string;
}

/**
 * Preview error payload
 */
export interface PreviewError {
    error: string;
    traceback?: string;
    stderr?: string;
}

/**
 * Type guard to check if a result is a PreviewError
 */
export function isPreviewError(result: PreviewResult | PreviewError): result is PreviewError {
    return 'error' in result;
}

/**
 * Storage statistics
 */
export interface StorageStats {
    storagePath: string;
    backendType: string;
    dbSizeBytes: number;
    dbSizeHuman: string;
    sourceCount: number;
    targetCount: number;
    nodes: Map<string, number>;
}

interface StorageCommandSuccess {
    ok: true;
    output: string;
}

interface StorageCommandFailure {
    ok: false;
    error: string;
    stderr?: string;
    traceback?: string;
}

type StorageCommandResult = StorageCommandSuccess | StorageCommandFailure;

/**
 * Storage Backend Reader class
 *
 * Uses the Python storage backend API for backend-agnostic access.
 * Works with SQLite, and future backends (S3, DuckDB, etc.)
 */
export class StorageReader {
    constructor(
        private readonly workflowPath: string,
        private readonly workflowName: string
    ) {}

    /**
     * Check if the storage backend has data
     */
    async exists(): Promise<boolean> {
        const result = await this.runStorageCommand('exists');
        return result.ok && result.output === 'true';
    }

    /**
     * Preview data for a specific action
     */
    async previewAction(
        nodeName: string,
        limit: number = 50,
        offset: number = 0
    ): Promise<PreviewResult | PreviewError | null> {
        const result = await this.runStorageCommand('preview', {
            action_name: nodeName,
            limit,
            offset,
        });

        if (!result.ok) {
            return {
                error: result.error,
                stderr: result.stderr,
                traceback: result.traceback,
            };
        }

        if (!result.output) {
            return null;
        }

        try {
            const parsed = JSON.parse(result.output) as Record<string, unknown>;
            if (StorageReader.isErrorPayload(parsed)) {
                return {
                    error: parsed.error,
                    traceback: typeof parsed.traceback === 'string' ? parsed.traceback : undefined,
                };
            }
            return StorageReader.normalizePreviewResult(parsed, nodeName, this.workflowPath);
        } catch {
            return {
                error: 'Failed to parse preview result',
                stderr: result.output,
            };
        }
    }

    /**
     * Get list of actions with data
     */
    async listActions(): Promise<Map<string, number>> {
        const result = await this.runStorageCommand('list_actions');

        if (result.ok && result.output) {
            try {
                const data = JSON.parse(result.output);
                return new Map(Object.entries(data));
            } catch {
                // Return empty map on parse failure
            }
        }
        return new Map();
    }

    /** Get storage statistics. */
    async getStats(): Promise<StorageStats | null> {
        const result = await this.runStorageCommand('stats');
        if (!result.ok || !result.output) return null;

        try {
            const data = transformKeys<Record<string, unknown>>(JSON.parse(result.output));
            return {
                storagePath: getString(data, 'dbPath'),  // Python: db_path → dbPath
                backendType: getString(data, 'backendType', 'sqlite'),
                dbSizeBytes: getNumber(data, 'dbSizeBytes'),
                dbSizeHuman: getString(data, 'dbSizeHuman'),
                sourceCount: getNumber(data, 'sourceCount'),
                targetCount: getNumber(data, 'targetCount'),
                nodes: new Map(Object.entries(getObject(data, 'nodes') as Record<string, number>)),
            };
        } catch {
            return null;
        }
    }

    /**
     * Run a storage backend command via Python
     */
    private async runStorageCommand(
        command: string,
        args: Record<string, unknown> = {}
    ): Promise<StorageCommandResult> {
        // Get Python path and module path from settings
        const config = vscode.workspace.getConfiguration('agentActions');
        const pythonPath = await resolvePythonPath();
        const modulePath = config.get<string>('modulePath') || '';

        // Build module path insertion code
        const modulePathCode = modulePath ? `sys.path.insert(0, ${JSON.stringify(modulePath)})` : '';

        const pythonCode = `
import json
import sys
from pathlib import Path

# Add configured module path if set
${modulePathCode}

# Add agent_actions to path if needed
def find_agent_actions():
    """Try multiple strategies to import agent_actions.storage"""
    # Strategy 1: Already installed/available
    try:
        from agent_actions.storage import get_storage_backend
        return get_storage_backend
    except ImportError:
        pass

    workflow_path = Path(${JSON.stringify(this.workflowPath)})

    # Strategy 2: Look for agent_actions in parent directories of workflow
    for parent in [workflow_path] + list(workflow_path.parents):
        candidate = parent / "agent_actions"
        if (candidate / "storage" / "__init__.py").exists():
            sys.path.insert(0, str(parent))
            try:
                from agent_actions.storage import get_storage_backend
                return get_storage_backend
            except ImportError:
                pass

    # Strategy 3: Look for agent-actions sibling directory (common dev setup)
    for parent in workflow_path.parents:
        try:
            for sibling in parent.iterdir():
                if sibling.is_dir() and sibling.name in ("agent-actions", "agent_actions"):
                    candidate = sibling / "agent_actions" / "storage" / "__init__.py"
                    if candidate.exists():
                        sys.path.insert(0, str(sibling))
                        try:
                            from agent_actions.storage import get_storage_backend
                            return get_storage_backend
                        except ImportError:
                            pass
        except (PermissionError, OSError):
            continue

    # Strategy 4: Look one level deeper (e.g., qanalabs/agent-actions in sibling dirs)
    for parent in workflow_path.parents:
        try:
            for sibling in parent.iterdir():
                if sibling.is_dir():
                    for subdir in sibling.iterdir():
                        if subdir.is_dir() and subdir.name in ("agent-actions", "agent_actions"):
                            candidate = subdir / "agent_actions" / "storage" / "__init__.py"
                            if candidate.exists():
                                sys.path.insert(0, str(subdir))
                                try:
                                    from agent_actions.storage import get_storage_backend
                                    return get_storage_backend
                                except ImportError:
                                    pass
        except (PermissionError, OSError):
            continue

    raise ImportError("Could not find agent_actions.storage module. Install with: pip install agent-actions")

try:
    get_storage_backend = find_agent_actions()
except Exception as e:
    import traceback
    print(json.dumps({"error": f"Module import failed: {e}", "traceback": traceback.format_exc()}))
    sys.exit(1)

workflow_path = ${JSON.stringify(this.workflowPath)}
workflow_name = ${JSON.stringify(this.workflowName)}
command = ${JSON.stringify(command)}
args = ${JSON.stringify(args)}

try:
    backend = get_storage_backend(workflow_path, workflow_name)
    backend.initialize()

    if command == 'exists':
        # Check if there's any data
        try:
            stats = backend.get_storage_stats()
            result = 'true' if stats.get('target_count', 0) > 0 else 'false'
        except Exception:
            result = 'false'
        print(result)

    elif command == 'preview':
        result = backend.preview_target(
            action_name=args['action_name'],
            limit=args.get('limit', 50),
            offset=args.get('offset', 0),
        )
        result['storagePath'] = str(backend.db_path) if hasattr(backend, 'db_path') else workflow_path
        result['backendType'] = backend.backend_type
        print(json.dumps(result, ensure_ascii=False, default=str))

    elif command == 'list_actions':
        stats = backend.get_storage_stats()
        print(json.dumps(stats.get('nodes', {})))

    elif command == 'stats':
        stats = backend.get_storage_stats()
        stats['backendType'] = backend.backend_type
        print(json.dumps(stats, ensure_ascii=False, default=str))

    backend.close()

except Exception as e:
    import traceback
    print(json.dumps({"error": str(e), "traceback": traceback.format_exc()}), file=sys.stderr)
    sys.exit(1)
`;

        const { execFile } = await import('child_process');
        const { promisify } = await import('util');
        const execFileAsync = promisify(execFile);

        try {
            const { stdout, stderr } = await execFileAsync(pythonPath, ['-c', pythonCode], {
                maxBuffer: 10 * 1024 * 1024, // 10MB buffer
                cwd: this.workflowPath,
                timeout: 30000, // 30 second timeout to prevent hangs
            });

            if (stderr && !stdout) {
                const parsed = this.parseErrorPayload(stderr);
                if (parsed) {
                    return parsed;
                }
                return { ok: false, error: stderr };
            }

            return { ok: true, output: stdout.trim() };
        } catch (error: unknown) {
            const err = error as { message?: string; stderr?: string; stdout?: string };
            const parsed = this.parseErrorPayload(err.stdout) ?? this.parseErrorPayload(err.stderr);
            if (parsed) {
                this.showModulePathHint(parsed.error);
                return parsed;
            }
            return {
                ok: false,
                error: err.message ?? 'Unknown error running storage command',
                stderr: err.stderr,
            };
        }
    }

    private static modulePathHintShown = false;

    private showModulePathHint(error: string): void {
        if (StorageReader.modulePathHintShown) return;
        if (!error.includes('Could not find agent_actions') && !error.includes('Module import failed')) return;

        StorageReader.modulePathHintShown = true;
        vscode.window.showWarningMessage(
            'Agent Actions module not found. Set agentActions.modulePath for faster discovery.',
            'Open Settings'
        ).then(selection => {
            if (selection === 'Open Settings') {
                vscode.commands.executeCommand('workbench.action.openSettings', 'agentActions.modulePath');
            }
        });
    }

    private parseErrorPayload(raw?: string): StorageCommandFailure | null {
        if (!raw) {
            return null;
        }

        const trimmed = raw.trim();
        if (!trimmed) {
            return null;
        }

        const jsonCandidate = StorageReader.extractJson(trimmed);
        if (jsonCandidate) {
            try {
                const parsed = JSON.parse(jsonCandidate) as Record<string, unknown>;
                if (StorageReader.isErrorPayload(parsed)) {
                    return {
                        ok: false,
                        error: parsed.error,
                        traceback: typeof parsed.traceback === 'string' ? parsed.traceback : undefined,
                        stderr: trimmed,
                    };
                }
            } catch {
                // fall through to plain string error
            }
        }

        return { ok: false, error: trimmed };
    }

    private static extractJson(raw: string): string | null {
        const start = raw.indexOf('{');
        const end = raw.lastIndexOf('}');
        if (start === -1 || end === -1 || end <= start) {
            return null;
        }
        return raw.slice(start, end + 1);
    }

    private static isErrorPayload(parsed: Record<string, unknown>): parsed is { error: string; traceback?: string } {
        return typeof parsed.error === 'string';
    }

    /** Transform Python snake_case response to TypeScript camelCase. */
    private static normalizePreviewResult(
        parsed: Record<string, unknown>,
        fallbackNodeName: string,
        fallbackStoragePath: string
    ): PreviewResult {
        // Extract records BEFORE transformKeys — user data keys must not be altered.
        // transformKeys is for the metadata envelope only (total_count → totalCount, etc.)
        const records = Array.isArray(parsed.records) ? parsed.records : [];
        const { records: _records, ...envelope } = parsed;
        const meta = transformKeys<Record<string, unknown>>(envelope);

        return {
            records,
            totalCount: getNumber(meta, 'totalCount', records.length),
            nodeName: getString(meta, 'nodeName', fallbackNodeName),
            files: Array.isArray(meta.files) ? meta.files.map(String) : [],
            storagePath: getString(meta, 'storagePath', fallbackStoragePath),
            backendType: getString(meta, 'backendType', 'sqlite'),
        };
    }
}

/**
 * Create a storage reader for a workflow
 */
export function createStorageReader(workflowPath: string, workflowName: string): StorageReader {
    return new StorageReader(workflowPath, workflowName);
}
