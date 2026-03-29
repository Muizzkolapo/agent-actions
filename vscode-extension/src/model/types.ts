/**
 * Workflow Navigator Types
 *
 * Consolidated type definitions combining the best approaches from all PRs:
 * - PR #820: WorkflowProject multi-project support
 * - PR #821: ActionInfo with configLocation as vscode.Location
 * - PR #823: ActionStatus with 'skipped' state, agent_status.json support
 */

import * as vscode from 'vscode';

/**
 * Action execution status derived from manifest and agent_status.json
 */
export type ActionStatus =
    | 'pending'
    | 'running'
    | 'completed'
    | 'failed'
    | 'skipped';

/**
 * Action type inferred from dependencies and configuration
 */
export type ActionType =
    | 'source'     // No dependencies - data source
    | 'transform'  // Single dependency - data transformation
    | 'merge'      // Multiple dependencies - data merge
    | 'parallel'   // Same level as other actions
    | 'output';    // Terminal action

/**
 * Complete action information combining config and runtime data
 */
export interface ActionInfo {
    /** Action name from config */
    name: string;
    /** 1-based execution order index */
    index: number;
    /** Execution level (0-based, actions at same level can run in parallel) */
    level: number;
    /** Current execution status */
    status: ActionStatus;
    /** Inferred action type */
    type: ActionType;
    /** Path to action output folder in agent_io/target */
    folderPath: string;
    /** Location in config file for navigation */
    configLocation: vscode.Location;
    /** Names of actions this depends on */
    dependencies: string[];
    /** Output field names from schema */
    outputFields: string[];
    /** Version folders if action has multiple versions */
    versions?: string[];
    /** Output directory name (may differ from action name) */
    outputDir?: string;
    /** Record count from manifest */
    recordCount?: number | null;
    /** Base name for versioned actions (e.g., "extract_raw_qa" for "extract_raw_qa_1") */
    baseName?: string;
    /** Version number/string for versioned actions */
    version?: number | string;
}

/**
 * Workflow project information for multi-project support
 */
export interface WorkflowInfo {
    /** Workflow name from config or manifest */
    name: string;
    /** Root path of the project */
    rootPath: string;
    /** Path to the workflow config file */
    configPath: string;
    /** All actions in execution order */
    actions: ActionInfo[];
    /** Action names in execution order */
    executionOrder: string[];
    /** Actions grouped by execution level */
    levels: Map<number, ActionInfo[]>;
    /** Summary of action statuses */
    statusSummary: StatusSummary;
}

/**
 * Status counts for workflow progress display
 */
export interface StatusSummary {
    total: number;
    completed: number;
    running: number;
    failed: number;
    pending: number;
    skipped: number;
}

/**
 * Manifest action entry from .manifest.json
 */
export interface ManifestActionInfo {
    index?: number;
    level?: number;
    status?: string;
    output_dir?: string;
    dependencies?: string[];
    record_count?: number | null;
}

/**
 * Workflow manifest from agent_io/target/.manifest.json
 */
export interface ManifestData {
    workflow_name?: string;
    execution_order?: string[];
    levels?: string[][];
    actions?: Record<string, ManifestActionInfo>;
}

/**
 * Agent status from agent_io/.agent_status.json (runtime status)
 */
export interface AgentStatusData {
    [actionName: string]: string | { status: string; [key: string]: unknown };
}

/**
 * Parsed action from workflow config YAML
 */
export interface ParsedAction {
    name: string;
    dependencies: string[];
    type?: string;
    outputFields: string[];
    /** Base name for versioned actions (e.g., "extract_raw_qa" for "extract_raw_qa_1") */
    baseName?: string;
    /** Version number/string for versioned actions */
    version?: number | string;
}

/**
 * Parsed workflow configuration
 */
export interface ParsedWorkflowConfig {
    name: string;
    actions: ParsedAction[];
    actionLocations: Map<string, number>;
}
