# Root Manifest

## Sub-Modules

| Sub-Module | Description |
|------------|-------------|
| [cli](cli/_MANIFEST.md) | Command-line interface for agent-actions. |
| [config](config/_MANIFEST.md) | Workflow configuration and dependency injection. |
| [errors](errors/_MANIFEST.md) | Centralized error exports for agent-actions. |
| [input](input/_MANIFEST.md) | Data ingestion utilities (context loaders, preprocessors, and transformers). |
| [llm](llm/_MANIFEST.md) | LLM runtime connectors for batch/realtime execution. |
| [lsp](lsp/_MANIFEST.md) | Backward-compatible LSP entrypoint shims that delegate to tooling LSP modules. |
| [logging](logging/_MANIFEST.md) | Agent Actions logging infrastructure. |
| [models](models/_MANIFEST.md) | Unified data models for agent-actions. |
| [output](output/_MANIFEST.md) | Output serialization, schema loading, and response helpers. |
| [processing](processing/_MANIFEST.md) | Shared processing helpers (enrichment, error handling, recovery). |
| [prompt](prompt/_MANIFEST.md) | Prompt rendering, context building, and formatting helpers. |
| [skills](skills/_MANIFEST.md) | Reusable skills and templates for agent workflows. |
| [tooling](tooling/_MANIFEST.md) | Documentation generation and IDE tooling (docs site + LSP). |
| [utils](utils/_MANIFEST.md) | Core utilities for Agent Actions. |
| [validation](validation/_MANIFEST.md) | Configuration and workflow validation. |
| [workflow](workflow/_MANIFEST.md) | Workflow orchestration, runners, and schema services. |

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `__version__.py` | Module | Agent Actions version. | - |
