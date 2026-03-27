# Batch Infrastructure Manifest

## Overview

Infrastructure modules resolve context, job management, and file handling for
batch services that orchestrate runs outside online mode.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `batch_client_resolver.py` | Module | Returns the appropriate provider/batch client per agent config. | `llm.providers`, `validation` |
| `batch_data_loader.py` | Module | Loads and prepares batched input payloads for processors. | `input`, `preprocessing` |
| `batch_source_handler.py` | Module | Maps target paths back to their source location for batch processing. Delegates workflow root discovery to `utils.path_utils.derive_workflow_root`. | `file_io`, `lineage`, `utils.path_utils` |
| `context.py` | Module | Batch context builders and metadata propagation helpers. | `logging`, `workflow` |
| `job_manager.py` | Module | Job lifecycle controller that tracks active batch runs. | `logging`, `tooling.docs` |
| `registry.py` | Module | `BatchRegistryManager`: thread-safe CRUD for `.batch_registry.json`. `are_all_jobs_completed()` releases the lock before network I/O to prevent thread starvation. | `llm.providers`, `logging` |
