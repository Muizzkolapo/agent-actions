# Agent Actions for VS Code

YAML language support for [Agent Actions](https://docs.runagac.com) workflows — autocomplete, validation, and go-to-definition.

## Features

- **Autocomplete** — action names, schema fields, context scope directives, model vendors
- **Validation** — real-time error highlighting for dangling dependencies, unknown fields, invalid references
- **Go-to-definition** — navigate from a prompt reference to its definition in the prompt store
- **Hover docs** — inline documentation for YAML keys
- **Field references** — validates `observe`, `drop`, and `passthrough` fields against upstream actions

## Requirements

Install the `agac-lsp` binary via pip:

```bash
pip install agent-actions
```

The extension automatically connects to `agac-lsp` on your PATH when you open a workflow file.

## Activation

The extension activates automatically when your workspace contains:
- `agent_config/*.yml`
- `agent_actions.yml`

## Configuration

| Setting | Default | Description |
|---|---|---|
| `agentActions.serverPath` | `agac-lsp` | Path to the agac-lsp binary |
| `agentActions.trace.server` | `off` | LSP trace level (`off`, `messages`, `verbose`) |

## Commands

- **Agent Actions: Restart Server** — restart the LSP server without reloading VS Code

## Getting Started

1. Install [Agent Actions](https://pypi.org/project/agent-actions/): `pip install agent-actions`
2. Install this extension
3. Open a folder containing `agent_actions.yml`
4. Start editing — autocomplete and validation activate automatically

## Documentation

Full documentation at [docs.runagac.com](https://docs.runagac.com)

## Issues

Report bugs and feature requests at [github.com/Muizzkolapo/agent-actions/issues](https://github.com/Muizzkolapo/agent-actions/issues)
