# Infrastructure Manifest

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `batch_client_resolver.py` | Module | Batch Client Resolver. | `errors`, `llm_invocation` |
| `BatchClientResolver` | Class | Resolves and caches batch clients. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_for_config` | Method | Get the appropriate client based on agent configuration. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_for_batch_id` | Method | Get the client that was used for a specific batch ID. | - |
| `batch_context_manager.py` | Module | Batch Context Manager. | `errors`, `utilities` |
| `BatchContextManager` | Class | Manages batch context map lifecycle. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `save_batch_context_map` | Method | Save batch processing context map to batch directory. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `load_batch_context_map` | Method | Load batch processing context map from batch directory. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `batch_context_exists` | Method | Check if batch context map file exists. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `delete_batch_context_map` | Method | Delete batch context map file if it exists. | - |
| `batch_data_loader.py` | Module | Data loader for batch processing from JSON and JSONL files. | `configuration` |
| `BatchDataLoader` | Class | Loads data for batch processing from a specified file path. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `supports_async` | Method | Return True as this loader supports async operations. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_processing_mode` | Method | Return AUTO processing mode to let system choose. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `load_data` | Method | Loads data from the given file path. | - |
| `batch_job_manager.py` | Module | Batch job lifecycle and registry status management. | `llm_invocation` |
| `RetryChainStatus` | Class | Status summary for a batch retry chain. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `is_complete` | Method | Check if the retry chain is fully complete. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `has_retries` | Method | Check if any retries were performed. | - |
| `BatchJobManager` | Class | Manages batch job lifecycle and registry status. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `set_registry_manager` | Method | Set the registry manager (for lazy initialization). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `are_all_jobs_completed` | Method | Check if all batch jobs in the registry are completed. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_registry_status` | Method | Get the overall status of all batch jobs in the registry. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_batch_children` | Method | Get all retry batches for a parent batch. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_batch_lineage` | Method | Get full chain from original batch to all retries. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_retry_chain_status` | Method | Get aggregated status for a batch retry chain. | - |
| `batch_registry_manager.py` | Module | Batch Registry Manager. | `llm_invocation`, `utilities` |
| `BatchRegistryManager` | Class | Manages batch job registry with caching and thread-safe operations. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `save_batch_job` | Method | Save or update a batch job entry. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_batch_job` | Method | Retrieve batch job entry by file name. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_batch_job_by_id` | Method | Retrieve batch job entry by batch ID. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `update_status` | Method | Update status for a batch job. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_all_jobs` | Method | Get all batch jobs in registry. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_registry_stats` | Method | Get aggregated statistics for all batches. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_overall_status` | Method | Get overall status across all batches. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `are_all_jobs_completed` | Method | Check if all batch jobs are in terminal state. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `invalidate_cache` | Method | Force cache reload on next access. | - |
| `batch_source_handler.py` | Module | Batch source data persistence handler. | `file_io` |
| `BatchSourceHandler` | Class | Handles batch source data persistence. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `save_task_source` | Method | Save task source data using unified source saver. | - |
