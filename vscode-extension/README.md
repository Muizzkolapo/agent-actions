# Agent Actions for VS Code

YAML language support and workflow navigation for [Agent Actions](https://github.com/Muizzkolapo/agent-actions) projects.

## Features

### Workflow Navigator
Browse your workflow actions in the sidebar with real-time status updates, record counts, and execution levels.

### CodeLens
Inline "Preview Output" and status indicators above each action definition in your YAML config files.

### DAG Visualization
View your workflow as an interactive directed acyclic graph. Actions are color-coded by status (completed, running, failed, pending, skipped). Click any node to jump to its definition.

**Shortcut:** `Cmd+Shift+D` (macOS) / `Ctrl+Shift+D` (Windows/Linux)

### Data Preview
Preview action output directly from the storage backend as a paginated table or JSON. Supports table/JSON toggle and page navigation.

### File Decorations
Action folders in the file explorer show colored badges with execution order numbers and status.

### Status Bar
Workflow progress displayed in the status bar. Shows the currently running action name during execution.

### Prompt Block Syntax
Syntax highlighting for `{prompt}...{end_prompt}` blocks in Markdown files.

## Getting Started

1. Install the extension from the [VS Code Marketplace](https://marketplace.visualstudio.com/items?itemName=runagac.agent-actions)
2. Open a folder containing an `agent_actions.yml` file
3. The Agent Actions sidebar appears automatically in the Activity Bar

## Requirements

- [Agent Actions](https://github.com/Muizzkolapo/agent-actions) Python package installed (`pip install agent-actions`)
- [Python extension](https://marketplace.visualstudio.com/items?itemName=ms-python.python) for automatic interpreter detection

## Commands

| Command | Shortcut | Description |
|---------|----------|-------------|
| Show Workflow DAG | `Cmd+Shift+D` | Open DAG visualization |
| Go to Action | `Cmd+Shift+A` | Quick pick to jump to any action |
| Refresh Workflow | `Cmd+Shift+R` | Refresh workflow data |
| Preview Data | — | Preview action output from storage |
| Restart LSP Server | — | Restart the language server |

## Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `agentActions.showStatusBar` | `true` | Show workflow progress in status bar |
| `agentActions.showCodeLens` | `true` | Show inline actions above YAML definitions |
| `agentActions.showFileDecorations` | `true` | Show badges in file explorer |
| `agentActions.dagLayout` | `vertical` | DAG direction (`vertical` or `horizontal`) |
| `agentActions.autoRevealSidebar` | `false` | Auto-open sidebar on project detection |
| `agentActions.logLevel` | `info` | Log verbosity in Output panel |
| `agentActions.previewPageSize` | `50` | Rows per page in data preview |

## License

Apache-2.0
