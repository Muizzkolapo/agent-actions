import * as fs from "fs";
import * as path from "path";
import { workspace, ExtensionContext, window, commands, OutputChannel } from "vscode";
import {
  LanguageClient,
  LanguageClientOptions,
  ServerOptions,
  TransportKind,
} from "vscode-languageclient/node";

let client: LanguageClient | undefined;
let outputChannel: OutputChannel;

const ACTIVATION_TIMEOUT_MS = 10_000;

function findAgacLsp(): string {
  const config = workspace.getConfiguration("agentActions");
  const configured: string = config.get("serverPath") || "";
  if (configured && configured !== "agac-lsp") {
    return configured;
  }

  // Search venv locations relative to workspace root
  const workspaceFolders = workspace.workspaceFolders;
  if (workspaceFolders) {
    const root = workspaceFolders[0].uri.fsPath;
    const venvNames = [".venv", "venv", ".env", "env", ".env_agac"];
    const binDir = process.platform === "win32" ? "Scripts" : "bin";
    for (const venv of venvNames) {
      const candidate = path.join(root, venv, binDir, "agac-lsp");
      if (fs.existsSync(candidate)) {
        return candidate;
      }
    }
  }

  // Fall back to system PATH
  return "agac-lsp";
}

async function startClient(context: ExtensionContext): Promise<void> {
  const serverPath = findAgacLsp();
  outputChannel.appendLine(`Using LSP server: ${serverPath}`);

  const serverOptions: ServerOptions = {
    command: serverPath,
    args: ["--stdio"],
    transport: TransportKind.stdio,
  };

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

  let timer: NodeJS.Timeout;
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
    // Stop the half-started client so it doesn't linger
    client.stop().catch(() => {});
    client = undefined;
    throw err;
  } finally {
    clearTimeout(timer!);
  }
}

export async function activate(context: ExtensionContext): Promise<void> {
  outputChannel = window.createOutputChannel("Agent Actions");
  context.subscriptions.push(outputChannel);

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
        `Make sure agent-actions is installed: pip install agent-actions`
    );
  }
}

export function deactivate(): Thenable<void> | undefined {
  return client?.stop();
}
