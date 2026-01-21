# Core Manifest

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `batch_constants.py` | Module | Constants for batch processing module. | - |
| `BatchStatus` | Class | Batch job status values. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `terminal_states` | Method | Get set of terminal (final) batch states. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `in_flight_states` | Method | Get set of in-flight (active) batch states. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `is_terminal` | Method | Check if this status is a terminal state. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `is_in_flight` | Method | Check if this status is an in-flight state. | - |
| `FilterStatus` | Class | Record filter status values. | - |
| `ContextMetaKeys` | Class | Internal metadata keys used in context maps. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `all_internal_keys` | Method | Get set of all internal metadata keys. | - |
| `batch_context_metadata.py` | Module | Centralized access to batch context metadata fields. | `llm_invocation` |
| `BatchContextMetadata` | Class | Helper class for batch context metadata operations. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `set_filter_status` | Method | Set the filter status on a record. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_filter_status` | Method | Get the filter status from a record. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `is_included` | Method | Check if record has included status. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `is_skipped` | Method | Check if record has skipped status. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `is_filtered` | Method | Check if record has filtered status. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `set_passthrough_fields` | Method | Set passthrough fields on a record. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_passthrough_fields` | Method | Get passthrough fields from a record. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `pop_passthrough_fields` | Method | Remove and return passthrough fields from a record. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `set_retry_metadata` | Method | Set retry metadata on a record. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_retry_metadata` | Method | Get retry metadata from a record. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `strip_internal_fields` | Method | Create a copy of record with all internal metadata fields removed. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `has_internal_fields` | Method | Check if record contains any internal metadata fields. | - |
| `batch_models.py` | Module | Data models for batch processing. | `llm_invocation` |
| `BatchJobEntry` | Class | Represents a single batch job entry in the registry. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `from_dict` | Method | Create BatchJobEntry from dictionary (JSON deserialization). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `to_dict` | Method | Convert to dictionary for JSON serialization. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `is_terminal` | Method | Check if batch is in terminal state (completed/failed/cancelled). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `is_in_flight` | Method | Check if batch is still in progress. | - |
| `BatchRegistryStats` | Class | Aggregated statistics for all batches in registry. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `overall_status` | Method | Get overall status across all jobs. | - |
| `BatchFilterResult` | Class | Result of filtering a single item. | - |
| `BatchTaskPreparationStats` | Class | Statistics from batch task preparation. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `success_rate` | Method | Calculate success rate (included / total). | - |
| `PreparedBatchTasks` | Class | Result of batch task preparation. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `is_empty` | Method | Check if no tasks were prepared. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `task_count` | Method | Get number of prepared tasks. | - |
