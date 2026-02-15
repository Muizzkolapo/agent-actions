# Lsp Manifest

## Sub-Modules

| Sub-Module | Description |
|------------|-------------|
| (none) | Compatibility shims are defined directly in this package. |

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `__init__.py` | Module | Exposes `main` from the compatibility server shim. | `tooling.lsp` |
| `server.py` | Module | Backward-compatible `agent_actions.lsp.server` entrypoint that delegates to `agent_actions.tooling.lsp.server`. | `tooling.lsp` |
