# Retry Manifest

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `batch_retry_config.py` | Module | Batch Retry Configuration. | - |
| `RetryConfig` | Class | Configuration for batch retry behavior. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate_max_attempts` | Method | Ensure max_attempts is consistent with enabled state. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `from_yaml` | Method | Parse retry configuration from various YAML formats. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `disabled` | Method | Create a disabled retry configuration. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `default` | Method | Create default retry configuration. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `is_enabled` | Method | Check if retries are effectively enabled. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `should_retry` | Method | Determine if another retry attempt should be made. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `to_dict` | Method | Convert to dictionary for serialization. | - |
| `get_retry_config` | Function | Extract retry configuration from agent config with fallback to default. | - |
| `batch_retry_orchestrator.py` | Module | Batch Retry Orchestrator. Uses `RetryMetadata` from unified metadata module. | `llm_invocation` |
| `RetryBatchResult` | Class | Result of a single retry batch submission and processing. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `all_succeeded` | Method | Check if all records in this retry succeeded. | - |
| `RetryChainResult` | Class | Result of the complete retry chain orchestration. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `all_succeeded` | Method | Check if all records ultimately succeeded. | - |
| `BatchRetryOrchestrator` | Class | Orchestrates automatic retry of failed/missing batch records. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `should_retry` | Method | Determine if a retry should be triggered. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_retry_records` | Method | Extract original record data for failed/missing records. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `prepare_retry_tasks` | Method | Prepare batch tasks for retry records. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `submit_retry_batch` | Method | Submit a retry batch and update registry. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `orchestrate_retry_chain` | Method | Orchestrate the complete retry chain until exhaustion. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `add_retry_metadata_to_record` | Method | Add retry metadata to a processed record. | - |
