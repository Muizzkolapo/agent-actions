import * as fs from "fs";
import * as path from "path";
import { workspace, ExtensionContext, window, commands } from "vscode";
import {
  LanguageClient,
  LanguageClientOptions,
  ServerOptions,
  TransportKind,
} from "vscode-languageclient/node";

let client: LanguageClient | undefined;

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

export function activate(context: ExtensionContext) {
  const serverPath = findAgacLsp();

  const serverOptions: ServerOptions = {
    command: serverPath,
    args: [],
    transport: TransportKind.stdio,
  };

  const clientOptions: LanguageClientOptions = {
    documentSelector: [{ scheme: "file", language: "yaml" }],
    synchronize: {
      fileEvents: workspace.createFileSystemWatcher(
        "**/{agent_config/*.yml,agent_actions.yml,schema/**/*.yml,prompt_store/**/*.md}"
      ),
    },
  };

  client = new LanguageClient(
    "agentActions",
    "Agent Actions",
    serverOptions,
    clientOptions
  );

  client.start().catch((err) => {
    window.showErrorMessage(
      `Agent Actions LSP failed to start: ${err.message}\n` +
        `Make sure agent-actions is installed: pip install agent-actions`
    );
  });

  context.subscriptions.push(
    commands.registerCommand("agentActions.restartServer", async () => {
      if (client) {
        await client.stop();
        await client.start();
        window.showInformationMessage("Agent Actions LSP restarted.");
      }
    })
  );
}

export function deactivate(): Thenable<void> | undefined {
  return client?.stop();
}
