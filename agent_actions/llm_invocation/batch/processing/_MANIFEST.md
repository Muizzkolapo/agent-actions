# Processing Manifest

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `batch_passthrough_builder.py` | Module | Passthrough Data Builder. | `llm_invocation`, `utilities` |
| `BatchPassthroughBuilder` | Class | Builder for creating passthrough data structures. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `from_data` | Method | Build passthrough data from raw data list. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `from_context` | Method | Build passthrough data from context map. | - |
| `batch_result_processor.py` | Module | Batch Result Processor. | `llm_invocation`, `preprocessing`, `utilities` |
| `BatchProcessingContext` | Class | Context passed through the processing pipeline. | - |
| `BatchResultProcessor` | Class | Pipeline-based processor for batch results. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `process` | Method | Process batch results through the pipeline. | - |
| `batch_result_reconciler.py` | Module | Result Reconciler. | `llm_invocation` |
| `BatchReconciliationResult` | Class | Result of reconciling batch results with expected records. | - |
| `BatchResultReconciler` | Class | Reconciles batch results with expected records from context map. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `mark_processed` | Method | Mark a custom_id as processed. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_expected_ids` | Method | Get set of custom_ids that are expected to be processed. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_missing_ids` | Method | Get set of custom_ids that were expected but not processed. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_passthrough_records` | Method | Get records that need passthrough treatment. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `reconcile` | Method | Perform full reconciliation. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_record_by_id` | Method | Get original record data by custom_id. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_source_guid` | Method | Get source_guid for a custom_id with fallback. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_record_index` | Method | Get the index of a custom_id in the context_map order. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `collect_expected_custom_ids` | Method | Collect custom_ids of records that were submitted to batch API. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `collect_result_custom_ids` | Method | Collect custom_ids from batch results. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `log_batch_reconciliation` | Method | Log batch reconciliation status with visual indicators. | - |
| `batch_side_output_handler.py` | Module | Side Output Handler. | `utilities` |
| `BatchSideOutputHandler` | Class | Handles side output operations for batch processing. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `separate` | Method | Split processed items into main and side output collections. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `save` | Method | Persist side output data, merging with existing content if present. | - |
| `batch_task_preparator.py` | Module | Batch Task Preparator. | `errors`, `llm_invocation`, `preprocessing`, `prompt_generation`, `response_processing`, `utilities`, `validation` |
| `BatchTaskPreparator` | Class | Prepares batch tasks from raw data. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `prepare_tasks` | Method | Prepare batch tasks from raw data. | - |
