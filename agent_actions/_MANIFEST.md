# Root Manifest

## Sub-Modules

| Sub-Module | Description |
|------------|-------------|
| [cli](cli/_MANIFEST.md) | Command-line interface for agent-actions. |
| [config](config/_MANIFEST.md) | Workflow configuration and dependency injection. |
| [errors](errors/_MANIFEST.md) | Centralized error exports for agent-actions. |
| [guards](guards/_MANIFEST.md) | Guard expression parsing and configuration. |
| [input](input/_MANIFEST.md) | Data ingestion utilities (context loaders, preprocessors, and transformers). |
| [llm](llm/_MANIFEST.md) | LLM runtime connectors for batch/online execution. |
| [logging](logging/_MANIFEST.md) | Agent Actions logging infrastructure. |
| [models](models/_MANIFEST.md) | Unified data models for agent-actions. |
| [output](output/_MANIFEST.md) | Output serialization, schema loading, and response helpers. |
| [processing](processing/_MANIFEST.md) | Shared processing helpers (enrichment, error handling, recovery). |
| [prompt](prompt/_MANIFEST.md) | Prompt rendering, context building, and formatting helpers. |
| [record](record/_MANIFEST.md) | Single authority for record content assembly. |
| [skills](skills/_MANIFEST.md) | Reusable skills and templates for agent workflows. |
| [storage](storage/_MANIFEST.md) | Extensible storage backend module for workflow data persistence. |
| [tooling](tooling/_MANIFEST.md) | Documentation generation and IDE tooling (docs site + LSP). |
| [utils](utils/_MANIFEST.md) | Core utilities for Agent Actions. |
| [validation](validation/_MANIFEST.md) | Configuration and workflow validation. |
| [workflow](workflow/_MANIFEST.md) | Workflow orchestration, runners, and schema services. |

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `__version__.py` | Module | Agent Actions version. | - |
