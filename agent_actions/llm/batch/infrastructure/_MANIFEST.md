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
| `recovery_state.py` | Module | `RecoveryState`: cross-pass retry/repair state persisted to storage metadata between runs, so a deferred batch resumes where it stopped. Its `phase` goes through `coerce_recovery_phase`, so a row naming a retired phase refuses rather than resuming into a handler that no longer exists. | `storage`, `llm.batch.core` |
| `registry.py` | Module | `BatchRegistryManager`: thread-safe CRUD over the batch job registry, persisted as storage-backend metadata keyed by action. `are_all_jobs_completed()` releases the lock before network I/O to prevent thread starvation. A malformed entry is skipped with a warning; one naming a retired recovery type is not, because dropping it makes its parent look unsubmitted. | `llm.providers`, `logging`, `storage` |
