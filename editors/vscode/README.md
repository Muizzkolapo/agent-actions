# Agent Actions VS Code Extension

Language support for agent-actions workflows in VS Code.

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
code --install-extension agent-actions-lsp-0.2.0.vsix
```

### Development Mode

1. Open this folder in VS Code
2. Press F5 to launch Extension Development Host
3. Open a project with `agent_actions.yml`

## Features

- **Go to Definition**: Ctrl+Click on prompts, tools, schemas, actions
- **Hover**: Preview content on hover
- **Autocomplete**: Suggestions for prompts, tools, schemas
- **Outline**: Document symbols for actions and prompt blocks
- **Syntax Highlighting**: Colored `{prompt}` tags and Jinja2 expressions

## Troubleshooting

### "agac-lsp: command not found"

Ensure agent-actions is installed and in PATH:

```bash
pip install agent-actions
which agac-lsp
```

### Extension not activating

Check Output panel → "Agent Actions LSP" for errors.
