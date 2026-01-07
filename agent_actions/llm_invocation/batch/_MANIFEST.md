# Batch Manifest

## Sub-Modules

| Sub-Module | Description |
|------------|-------------|
| [core](core/_MANIFEST.md) | Core batch module components: constants, models, and metadata helpers. |
| [infrastructure](infrastructure/_MANIFEST.md) | Batch infrastructure: client resolution, context management, registry. |
| [processing](processing/_MANIFEST.md) | Batch processing: result processing, reconciliation, and task preparation. |
| [retry](retry/_MANIFEST.md) | Batch retry: configuration and orchestration for batch retries. |
| [services](services/_MANIFEST.md) | Batch services: focused service classes for batch operations. |

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `batch_cli.py` | Module | CLI commands for batch processing operations. | `cli`, `llm_invocation`, `validation` |
| `batch` | Function | CLI command group for batch processing operations. | - |
| `status` | Function | Checks the status of a running batch job. | - |
| `retrieve` | Function | Retrieves the results of a completed batch job. | - |
| `retry` | Function | Retry failed records from a completed batch job. | - |
| `chain_status` | Function | Show the status of a batch retry chain. | - |
| `batch_service.py` | Module | Batch processing service facade for managing batch job lifecycle and results. | `llm_invocation`, `orchestration` |
| `BatchService` | Class | Thin facade for batch processing that delegates to specialized services. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `prepare_batch_tasks` | Method | Prepare batch tasks from data (delegates to submission service). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `submit_batch_job` | Method | Submit a batch job for processing (delegates to submission service). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `check_status` | Method | Check the status of a batch job (delegates to submission service). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `retrieve_results` | Method | Retrieve and save results from a completed batch job (delegates to retrieval service). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `process_batch_results` | Method | Process batch results to workflow output (delegates to processing service). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `process_all_batch_results` | Method | Process all completed batch jobs (delegates to processing service). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `retry_batch_job` | Method | Retry a batch job (delegates to retry service). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `are_all_batch_jobs_completed` | Method | Check if all batch jobs in the registry are completed (delegates to BatchJobManager). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_batch_registry_status` | Method | Get overall status of all batch jobs in the registry. | - |
