# Utils Manifest

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `error_handler.py` | Module | Error handling utilities. | `errors`, `shared` |
| `ErrorHandler` | Class | Utility class for handling errors in a consistent way. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `format_for_user` | Method | Format error using user-friendly system. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `handle_error` | Method | Handle an error by logging it and raising an appropriate exception. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `handle_validation_error` | Method | Handle a validation error. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `handle_file_error` | Method | Handle a file operation error. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `handle_config_error` | Method | Handle a configuration error. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `handle_template_error` | Method | Handle a template rendering error. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `handle_execution_error` | Method | Handle an execution error. | - |
| `error_wrap.py` | Module | Error wrapping utilities for validation errors. | `errors` |
| `as_validation_error` | Function | Any exception inside the wrapped function is re-raised as `exc_cls` | - |
| `service_logger.py` | Module | Service logging utilities. | - |
| `ServiceLogger` | Class | Utility class for service logging. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `log_operation_start` | Method | Log the start of an operation. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `log_operation_success` | Method | Log the successful completion of an operation. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `log_operation_error` | Method | Log an error that occurred during an operation. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `log_validation_start` | Method | Log the start of a validation operation. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `log_validation_success` | Method | Log the successful completion of a validation operation. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `log_validation_error` | Method | Log an error that occurred during validation. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `log_file_operation` | Method | Log a file operation. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `log_config_operation` | Method | Log a configuration operation. | - |
