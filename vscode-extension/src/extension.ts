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

export async function activate(context: ExtensionContext): Promise<void> {
  outputChannel = window.createOutputChannel("Agent Actions");
  context.subscriptions.push(outputChannel);

  // Restart server when Python interpreter changes
  try {
    const pythonApi = await PythonExtension.api();
    context.subscriptions.push(
      pythonApi.environments.onDidChangeActiveEnvironmentPath(async () => {
        outputChannel.appendLine("Python interpreter changed, restarting LSP server...");
        try {
          if (client) {
            await client.stop();
            client = undefined;
          }
          await startClient(context);
        } catch (err: unknown) {
          const msg = err instanceof Error ? err.message : String(err);
          outputChannel.appendLine(`Restart after interpreter change failed: ${msg}`);
        }
      })
    );
  } catch {
    outputChannel.appendLine(
      "Python extension not available; interpreter change detection disabled."
    );
  }

  context.subscriptions.push(
    commands.registerCommand("agentActions.restartServer", async () => {
      try {
        if (client) {
          outputChannel.appendLine("Restarting LSP server...");
          await client.stop();
          client = undefined;
        }
        await startClient(context);
        window.showInformationMessage("Agent Actions LSP restarted.");
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : String(err);
        outputChannel.appendLine(`Restart failed: ${msg}`);
        window.showErrorMessage(`Agent Actions: restart failed — ${msg}`);
      }
    })
  );

  try {
    await startClient(context);
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
  return client?.stop();
}
