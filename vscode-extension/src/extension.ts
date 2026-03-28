import { workspace, ExtensionContext, window, commands, OutputChannel } from "vscode";
import {
  LanguageClient,
  LanguageClientOptions,
  ServerOptions,
  TransportKind,
} from "vscode-languageclient/node";
import { PythonExtension } from "@vscode/python-extension";

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
    if (disposed) {
      outputChannel.appendLine("LSP restart skipped (extension disposing).");
      return;
    }

    outputChannel.appendLine("LSP restart starting...");

    try {
      if (client) {
        await client.stop();
        client = undefined;
      }
      await startClient(context);
      outputChannel.appendLine("LSP restart complete.");
    } catch (err: unknown) {
      // Invariant: client must be undefined if not fully started.
      // startClient() already enforces this in its catch block, but guard
      // against any path where client could be left half-initialized.
      client = undefined;
      const msg = err instanceof Error ? err.message : String(err);
      outputChannel.appendLine(`LSP restart failed: ${msg}`);
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
      await client.stop();
      client = undefined;
    }
  });
  return lifecycleQueue;
}
