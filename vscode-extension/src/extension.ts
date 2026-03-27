import * as path from "path";
import {
  workspace,
  ExtensionContext,
  window,
  commands,
  Uri,
} from "vscode";
import {
  LanguageClient,
  LanguageClientOptions,
  ServerOptions,
  TransportKind,
} from "vscode-languageclient/node";

let client: LanguageClient | undefined;

export function activate(context: ExtensionContext) {
  const config = workspace.getConfiguration("agentActions");
  const serverPath: string = config.get("serverPath") || "agac-lsp";

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
        `Make sure 'agac-lsp' is installed: pip install agent-actions`
    );
  });

  // Command: restart LSP server
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
