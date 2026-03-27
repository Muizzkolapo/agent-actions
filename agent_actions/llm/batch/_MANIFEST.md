# Batch Manifest

## Sub-Modules

| Sub-Module | Description |
|------------|-------------|
| [core](core/_MANIFEST.md) | Core batch components: constants, models, and metadata helpers. |
| [infrastructure](infrastructure/_MANIFEST.md) | Batch infrastructure: client resolution, context management, registry. |
| [processing](processing/_MANIFEST.md) | Batch processing: result processing, reconciliation, and task preparation. |
| [services](services/_MANIFEST.md) | Batch services: focused service classes for batch operations. |

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `batch_cli.py` | Module | CLI commands for batch processing operations. | llm.batch |
| `service.py` | Module | Shared batch utilities (registry manager factory). | llm.batch |
