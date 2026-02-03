# Agent Actions VS Code Extension

Language support and workflow navigation for Agent Actions projects in VS Code.

## Prerequisites

Install agent-actions with pip:

```bash
pip install agent-actions
```

This includes the `agac-lsp` command used by this extension.

## Installation

### From VSIX (Recommended)

```bash
cd editors/vscode
npm install
npm run compile
npx vsce package --allow-missing-repository
code --install-extension agent-actions-lsp-0.3.0.vsix
```

### Development Mode

1. Open this folder in VS Code
2. Press F5 to launch Extension Development Host
3. Open a project with `agent_config/*.yml`

## Features

### Language Features

- **Go to Definition**: Ctrl+Click on prompts, tools, schemas, actions
- **Hover**: Preview content on hover
- **Autocomplete**: Suggestions for prompts, tools, schemas
- **Outline**: Document symbols for actions and prompt blocks
- **Syntax Highlighting**: Colored `{prompt}` tags and Jinja2 expressions

### Workflow Navigator

The Workflow Navigator provides an IDE-first experience for understanding and navigating Agent Actions workflows.

#### Sidebar Tree View

See all actions in execution order with live status indicators:
- ✓ Completed (green)
- ↻ Running (yellow, spinning)
- ✗ Failed (red)
- ○ Pending (gray)
- ⊘ Skipped (blue)

Click any action to jump to its definition in the YAML config.

#### DAG Visualization

Press `Cmd+Shift+D` (Mac) or `Ctrl+Shift+D` (Windows/Linux) to open a visual DAG showing:
- Action dependencies as directed edges
- Status-colored nodes
- Click-to-navigate to action definitions

#### CodeLens Actions

In workflow YAML files, each action shows inline links:
- 🔎 **Preview Output** - Preview action output from storage backend
- Status indicator with click to show DAG

#### File Decorations

Action folders in `agent_io/target/` show:
- Execution order badges (1, 2, 3...)
- Status-colored text

#### Status Bar

Shows workflow progress at a glance:
- Completed/total count
- Currently running action name
- Click to focus Workflow Navigator

### Keyboard Shortcuts

| Command | Mac | Windows/Linux |
|---------|-----|---------------|
| Show Workflow DAG | `Cmd+Shift+D` | `Ctrl+Shift+D` |
| Go to Action | `Cmd+Shift+A` | `Ctrl+Shift+A` |
| Refresh Workflow | `Cmd+Shift+R` | `Ctrl+Shift+R` |

## Settings

```json
{
  "agentActions.pythonPath": "",
  "agentActions.modulePath": "",
  "agentActions.showStatusBar": true,
  "agentActions.showCodeLens": true,
  "agentActions.showFileDecorations": true,
  "agentActions.dagLayout": "vertical",
  "agentActions.refreshInterval": 0,
  "agentActions.previewCacheTTL": 5000
}
```

| Setting | Default | Description |
|---------|---------|-------------|
| `pythonPath` | `""` | Python interpreter path. Empty = auto-detect. |
| `modulePath` | `""` | Path to agent-actions module. **Set this for faster startup in monorepos.** |
| `showStatusBar` | `true` | Show workflow status in status bar. |
| `showCodeLens` | `true` | Show action links in YAML files. |
| `showFileDecorations` | `true` | Show badges on action folders. |
| `dagLayout` | `"vertical"` | DAG direction: `"vertical"` or `"horizontal"`. |
| `refreshInterval` | `0` | Polling interval (ms). 0 = file watchers only. |
| `previewCacheTTL` | `5000` | Cache duration (ms) for data preview. 0 = disable. |

## Data Sources

The extension reads from:

1. **`agent_config/*.yml`** - Workflow configuration (actions, dependencies)
2. **`agent_io/target/.manifest.json`** - Execution plan and status
3. **`agent_io/.agent_status.json`** - Live runtime status (optional)

File watchers automatically refresh the UI when these files change.

## Troubleshooting

### "agac-lsp: command not found"

Ensure agent-actions is installed and in PATH:

```bash
pip install agent-actions
which agac-lsp
```

### Extension not activating

Check Output panel → "Agent Actions LSP" for errors.

### Workflow Navigator not showing

Ensure your project has:
- `agent_config/` directory with `.yml` files
- Actions defined with `name:` fields

### Status not updating

- Check that `agent_io/target/.manifest.json` exists
- Try `Cmd+Shift+R` to manually refresh
- Enable polling: `"agentActions.refreshInterval": 2000`

### Data preview not working / "Module import failed"

The extension needs to find the `agent_actions` Python module. Set `modulePath` explicitly:

```json
{
  "agentActions.modulePath": "/path/to/agent-actions"
}
```

This is recommended for:
- **Monorepos** where auto-discovery might find the wrong module
- **Large directory structures** where traversal is slow
- **Development setups** with local clones of agent-actions

## Architecture

```
src/
├── extension.ts          # Entry point, wires everything together
├── model/
│   ├── types.ts          # Type definitions
│   ├── workflowModel.ts  # Central model, file watchers
│   ├── yamlParser.ts     # YAML parsing
│   └── manifestReader.ts # JSON parsing
├── providers/
│   ├── treeViewProvider.ts    # Sidebar tree
│   ├── codeLensProvider.ts    # In-editor links
│   ├── decorationProvider.ts  # File explorer badges
│   └── statusBarProvider.ts   # Status bar item
├── views/
│   └── dagWebview.ts     # Mermaid DAG panel
└── commands/
    └── index.ts          # Command registration
```

## Contributing

This implementation consolidates ideas from multiple team contributions:
- Multi-project support
- Live status from `.agent_status.json`
- Clean event-driven architecture
- Comprehensive VS Code integrations
