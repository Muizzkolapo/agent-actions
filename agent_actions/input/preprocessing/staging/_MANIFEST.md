# Staging Manifest

## Sub-Modules

| Sub-Module | Description |
|------------|-------------|
| (none) | Initial-stage logic lives at this level. |

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `__init__.py` | Module | Module docstring describing the staging helpers. | `preprocessing` |
| `initial_pipeline.py` | Module | `process_initial_stage` entry point plus validation, source saving, mode-specific preparation helpers, and storage-backend requirements for first-stage target writes. | `processing`, `output`, `logging` |
