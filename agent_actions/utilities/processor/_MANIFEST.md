# Processor Manifest

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `error_handling.py` | Module | Standardized error handling mixin for processors. | `errors` |
| `ProcessorErrorHandlerMixin` | Class | Mixin class providing standardized error handling for processors. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_error_context` | Method | Build contextual information for error logging. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `handle_processing_error` | Method | Handle a processing error with consistent logging and re-raising. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `handle_validation_error` | Method | Handle a validation error. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `handle_file_error` | Method | Handle a file operation error. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `handle_transformation_error` | Method | Handle a data transformation error. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `log_warning` | Method | Log a warning with consistent structure. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `log_info` | Method | Log an info message with consistent structure. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `with_retry` | Method | Decorator for adding retry logic to methods. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `with_fallback` | Method | Decorator for adding fallback behavior to methods. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `handle_partial_failure` | Method | Handle partial failures in batch operations. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `create_error_recovery_state` | Method | Create a recovery state that can be used to resume operations. | - |
| `processor_helpers.py` | Module | Utility helpers shared across processors. | `llm_invocation`, `preprocessing`, `utilities` |
| `evaluate_guard_condition` | Function | Evaluate guard conditions (where_clause, conditional_clause). | - |
| `run_dynamic_agent` | Function | Execute an agent with conditional guard processing and data filtering. | - |
| `transform_with_passthrough` | Function | Apply ``context_scope.passthrough`` logic to generated data consistently. | - |
