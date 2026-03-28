import * as vscode from "vscode";
import { workspace, ExtensionContext, window, commands, OutputChannel, Uri } from "vscode";
import {
  LanguageClient,
  LanguageClientOptions,
  ServerOptions,
  TransportKind,
} from "vscode-languageclient/node";
import { PythonExtension } from "@vscode/python-extension";
import { ActionInfo } from "./model/types";
import { WorkflowModel } from "./model/workflowModel";
import { WorkflowTreeProvider } from "./providers/treeViewProvider";
import { ExtensionInfoProvider } from "./providers/extensionInfoProvider";
import { HelpProvider } from "./providers/helpProvider";
import { DagWebview } from "./views/dagWebview";
import { QueryResultsPanel } from "./views/queryResultsPanel";
import { createStorageReader, isPreviewError } from "./utils/storageReader";

let client: LanguageClient | undefined;
let outputChannel: OutputChannel;

// Lifecycle serialization — all start/stop transitions chain through this promise
// so at most one cycle is in-flight at any time.
let lifecycleQueue: Promise<void> = Promise.resolve();
let lifecyclePending = 0;
let disposed = false;

// Debounce timer for interpreter change events — the Python extension can emit
// 2-4 rapid events during its own activation; collapse them into one restart.
let debounceTimer: ReturnType<typeof setTimeout> | undefined;
const DEBOUNCE_MS = 300;

const ACTIVATION_TIMEOUT_MS = 10_000;
const MODULE_ARGS = ["-m", "agent_actions.tooling.lsp.server", "--stdio"];

async function getPythonPath(): Promise<string | undefined> {
  try {
    const api = await PythonExtension.api();
    const envPath = api.environments.getActiveEnvironmentPath();
    if (!envPath) return undefined;
    const env = await api.environments.resolveEnvironment(envPath);
    return env?.executable.uri?.fsPath;
  } catch {
    outputChannel.appendLine(
      "Python extension not available; skipping interpreter discovery."
    );
    return undefined;
  }
}

async function resolveServerOptions(): Promise<ServerOptions> {
  const config = workspace.getConfiguration("agentActions");

  // 1. Explicit serverPath override (escape hatch)
  const serverPath: string = config.get("serverPath") || "";
  if (serverPath && serverPath !== "agac-lsp") {
    outputChannel.appendLine(`Using explicit server path: ${serverPath}`);
    return { command: serverPath, args: ["--stdio"], transport: TransportKind.stdio };
  }

  // 2. Explicit interpreter setting
  const interpreter: string[] = config.get("interpreter") || [];
  if (interpreter.length > 0) {
    outputChannel.appendLine(`Using interpreter from setting: ${interpreter[0]}`);
    return { command: interpreter[0], args: MODULE_ARGS, transport: TransportKind.stdio };
  }

  // 3. Python extension API
  const pythonPath = await getPythonPath();
  if (pythonPath) {
    outputChannel.appendLine(`Using Python from extension: ${pythonPath}`);
    return { command: pythonPath, args: MODULE_ARGS, transport: TransportKind.stdio };
  }

  // 4. Fall back to agac-lsp on PATH
  outputChannel.appendLine("Falling back to agac-lsp on PATH");
  return { command: "agac-lsp", args: ["--stdio"], transport: TransportKind.stdio };
}

async function startClient(context: ExtensionContext): Promise<void> {
  const serverOptions = await resolveServerOptions();

  const clientOptions: LanguageClientOptions = {
    documentSelector: [{ scheme: "file", language: "yaml" }],
    synchronize: {
      fileEvents: workspace.createFileSystemWatcher(
        "**/{agent_config/*.yml,agent_actions.yml,schema/**/*.yml,prompt_store/**/*.md}"
      ),
    },
    outputChannel,
  };

  client = new LanguageClient(
    "agentActions",
    "Agent Actions",
    serverOptions,
    clientOptions
  );

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
    outputChannel.appendLine("LSP server started successfully.");
  } catch (err) {
    client.stop().catch((e) => outputChannel.appendLine(`Stop error: ${e}`));
    client = undefined;
    throw err;
  } finally {
    if (timer) clearTimeout(timer);
  }
}

/**
 * Serialized restart — every caller (activation, interpreter change, manual command)
 * goes through this single gate. The promise chain guarantees at most one stop→start
 * cycle is in-flight. Errors are caught internally so the chain never jams.
 *
 * Returns a promise that resolves when this particular cycle completes (or is skipped).
 * Callers that need the result (activate, restart command) can await it.
 * Fire-and-forget callers (debounced interpreter change) can ignore it.
 */
function restartServer(context: ExtensionContext): Promise<void> {
  if (lifecyclePending > 0) {
    outputChannel.appendLine("LSP restart requested (queued behind in-flight cycle).");
  }
  lifecyclePending++;
  const cycle = lifecycleQueue.then(async () => {
    try {
      if (disposed) {
        outputChannel.appendLine("LSP lifecycle: skipped (extension disposing).");
        return;
      }

      outputChannel.appendLine("LSP lifecycle: starting...");

      if (client) {
        await client.stop();
        client = undefined;
      }
      await startClient(context);
      outputChannel.appendLine("LSP lifecycle: started.");
    } catch (err: unknown) {
      // Invariant: client must be undefined if not fully started.
      // startClient() already enforces this in its catch block, but guard
      // against any path where client could be left half-initialized.
      client = undefined;
      const msg = err instanceof Error ? err.message : String(err);
      outputChannel.appendLine(`LSP lifecycle: failed — ${msg}`);
      // Re-throw so callers that await the returned `cycle` promise see the
      // error (activate shows a user-facing message, restart command shows a
      // toast). The queue itself is insulated via cycle.catch(() => {}) below.
      // Fire-and-forget callers (interpreter change) must attach their own .catch().
      throw err;
    } finally {
      lifecyclePending--;
    }
  });

  // The queue promise never rejects — errors are visible to the caller via
  // the returned `cycle` promise, but the queue itself stays healthy.
  lifecycleQueue = cycle.catch(() => {});

  return cycle;
}

export async function activate(context: ExtensionContext): Promise<void> {
  outputChannel = window.createOutputChannel("Agent Actions");
  context.subscriptions.push(outputChannel);

  // Sidebar panels
  const model = new WorkflowModel();
  const treeProvider = new WorkflowTreeProvider(model);
  const infoProvider = new ExtensionInfoProvider(() => client, context);
  const helpProvider = new HelpProvider();
  const dagWebview = new DagWebview(context, model);
  const queryResultsPanel = new QueryResultsPanel(context.extensionUri, context);

  context.subscriptions.push(
    model, treeProvider, infoProvider, dagWebview, queryResultsPanel,
    vscode.window.registerTreeDataProvider("agentActionsWorkflow", treeProvider),
    vscode.window.registerTreeDataProvider("agentActionsInfo", infoProvider),
    vscode.window.registerTreeDataProvider("agentActionsHelp", helpProvider),
  );

  // Workflow commands
  context.subscriptions.push(
    commands.registerCommand("agentActions.refreshWorkflows", () => void model.refresh()),
    commands.registerCommand("agentActions.openConfig", (arg: ActionInfo | { action: ActionInfo }) => {
      const action: ActionInfo | undefined = arg && "action" in arg ? arg.action : arg;
      if (action?.configLocation) {
        vscode.workspace.openTextDocument(action.configLocation.uri).then((doc) => {
          vscode.window.showTextDocument(doc, { preview: false }).then((editor) => {
            const pos = action.configLocation.range.start;
            editor.revealRange(new vscode.Range(pos, pos), vscode.TextEditorRevealType.InCenter);
            editor.selection = new vscode.Selection(pos, pos);
          });
        });
      }
    }),
    commands.registerCommand("agentActions.openDocs", () => {
      vscode.env.openExternal(Uri.parse("https://docs.runagac.com"));
    }),
    commands.registerCommand("agentActions.showDAG", () => dagWebview.show()),
    commands.registerCommand("agentActions.goToAction", async () => {
      const workflows = model.getWorkflows();
      if (workflows.length === 0) {
        window.showInformationMessage("No Agent Actions workflows detected.");
        return;
      }
      const items = workflows.flatMap((wf) =>
        wf.actions.map((a) => ({
          label: `[${a.index}] ${a.name}`,
          description: `${a.status} | ${wf.name}`,
          action: a,
        }))
      );
      const selected = await window.showQuickPick(items, {
        title: "Go to Action",
        placeHolder: "Select an action to navigate to",
      });
      if (selected) {
        commands.executeCommand("agentActions.openConfig", selected.action);
      }
    }),
    commands.registerCommand("agentActions.previewData", async (arg: ActionInfo | { action: ActionInfo }) => {
      const action: ActionInfo | undefined = arg && "action" in arg ? arg.action : arg;
      if (!action) return;
      const workflow = model.getWorkflows().find((w) => w.actions.some((a) => a.name === action.name));
      if (!workflow) {
        window.showErrorMessage(`Could not find workflow for action ${action.name}`);
        return;
      }
      const config = workspace.getConfiguration("agentActions");
      const limit = config.get<number>("previewPageSize", 50);
      const reader = createStorageReader(workflow.rootPath, workflow.name);
      const result = await reader.previewAction(action.name, limit, 0);
      if (!result) {
        queryResultsPanel.showError(action.name, "Failed to load data from storage backend");
        return;
      }
      if (isPreviewError(result)) {
        queryResultsPanel.showError(action.name, result.error, result.traceback ?? result.stderr);
        return;
      }
      queryResultsPanel.showResults(result, action.name, workflow.rootPath, workflow.name, limit, 0);
    }),
    commands.registerCommand("agentActions.nextPage", () => navigatePreviewPage(model, queryResultsPanel, "next")),
    commands.registerCommand("agentActions.previousPage", () => navigatePreviewPage(model, queryResultsPanel, "previous")),
    commands.registerCommand("agentActions.openSettings", () => {
      commands.executeCommand("workbench.action.openSettings", "agentActions");
    }),
    commands.registerCommand("agentActions.showWorkflowTree", () => {
      commands.executeCommand("workbench.view.extension.agentActions");
    }),
  );

  // Register interpreter change listener unconditionally — before startClient() —
  // so "install package → switch interpreter → auto-start" recovery works even
  // when initial startup fails. The 300ms debounce collapses rapid-fire events
  // from the Python extension's own activation into a single queued restart.
  try {
    const pythonApi = await PythonExtension.api();
    context.subscriptions.push(
      pythonApi.environments.onDidChangeActiveEnvironmentPath(() => {
        if (debounceTimer) clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => {
          debounceTimer = undefined;
          outputChannel.appendLine("Python interpreter changed; scheduling LSP restart...");
          restartServer(context).catch((err: unknown) => {
            const msg = err instanceof Error ? err.message : String(err);
            outputChannel.appendLine(`Restart after interpreter change failed: ${msg}`);
          });
        }, DEBOUNCE_MS);
      })
    );
  } catch {
    // TODO(#43): re-register interpreter listener if Python extension activates
    // after us. Currently, if the Python extension isn't available at activation
    // time (slow extension host, workspace trust delay), interpreter change
    // detection is permanently dead for the session.
    outputChannel.appendLine(
      "Python extension not available; interpreter change detection disabled."
    );
  }

  context.subscriptions.push(
    commands.registerCommand("agentActions.restartServer", async () => {
      try {
        await restartServer(context);
        window.showInformationMessage("Agent Actions LSP restarted.");
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : String(err);
        window.showErrorMessage(`Agent Actions: restart failed — ${msg}`);
      }
    })
  );

  try {
    await restartServer(context);
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    outputChannel.appendLine(`Activation error: ${msg}`);
    window.showErrorMessage(
      `Agent Actions LSP failed to start: ${msg}\n` +
        `Ensure agent-actions is installed (pip install agent-actions) ` +
        `and either the Python extension is active or agac-lsp is on your PATH.`
    );
  }
}

async function navigatePreviewPage(
  model: WorkflowModel,
  panel: QueryResultsPanel,
  direction: "next" | "previous"
): Promise<void> {
  const pagination = panel.getPagination();
  if (!pagination) return;
  const { actionName, workflowPath, workflowName, limit, offset, totalCount } = pagination;
  const newOffset = direction === "next" ? offset + limit : Math.max(0, offset - limit);
  if (direction === "previous" && offset === 0) return;
  if (direction === "next" && offset + limit >= totalCount) return;
  const reader = createStorageReader(workflowPath, workflowName);
  const result = await reader.previewAction(actionName, limit, newOffset);
  if (!result) {
    panel.showError(actionName, "Failed to load data");
    return;
  }
  if (isPreviewError(result)) {
    panel.showError(actionName, result.error, result.traceback ?? result.stderr);
    return;
  }
  panel.showResults(result, actionName, workflowPath, workflowName, limit, newOffset);
}

export function deactivate(): Thenable<void> | undefined {
  disposed = true;
  if (debounceTimer) {
    clearTimeout(debounceTimer);
    debounceTimer = undefined;
  }
  // Chain onto the lifecycle queue so we wait for any in-flight cycle to
  // complete before stopping, avoiding orphan processes.
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
