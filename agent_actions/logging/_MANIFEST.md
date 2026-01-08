# Logging Manifest

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `config.py` | Module | Logging configuration dataclasses. | - |
| `HandlerConfig` | Class | Configuration for a single log handler. | - |
| `FileHandlerSettings` | Class | File handler configuration settings. | - |
| `LoggingConfig` | Class | Central logging configuration. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `file_handler_enabled` | Method | Legacy property for backward compatibility. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `log_file_path` | Method | Legacy property for backward compatibility. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `file_log_level` | Method | Legacy property for backward compatibility. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `file_max_bytes` | Method | Legacy property for backward compatibility. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `file_backup_count` | Method | Legacy property for backward compatibility. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `file_format` | Method | Legacy property for backward compatibility. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `from_project_config` | Method | Create LoggingConfig from project configuration. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `from_environment` | Method | Create LoggingConfig from environment variables. | - |
| `context.py` | Module | Correlation context management for logging. | - |
| `ExecutionContext` | Class | Context information for a single workflow execution. | - |
| `CorrelationContext` | Class | Manages execution context for logging correlation. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `generate_correlation_id` | Method | Generate a unique correlation ID. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_context` | Method | Get current execution context. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `set_context` | Method | Set execution context for current thread/coroutine. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `clear_context` | Method | Clear execution context. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `start_workflow` | Method | Initialize context for workflow execution. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `set_agent` | Method | Update context with current agent information. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `set_batch` | Method | Update context with batch information. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `set_item` | Method | Update context with item information. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `add_extra` | Method | Add extra context information. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_correlation_id` | Method | Get current correlation ID if available. | - |
| `factory.py` | Module | Logger factory for centralized logging configuration. | `logging` |
| `LoggerFactory` | Class | Factory for creating and configuring loggers. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `initialize` | Method | Initialize the logging system with configuration. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_logger` | Method | Get a logger with the given name. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `set_level` | Method | Set log level for a logger. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `set_debug` | Method | Enable or disable debug logging globally. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_config` | Method | Get the current logging configuration. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `is_initialized` | Method | Check if the factory has been initialized. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `reset` | Method | Reset the factory state. | - |
| `filters.py` | Module | Custom logging filters for context injection. | `llm_invocation`, `logging` |
| `ContextInjectingFilter` | Class | Injects execution context into log records. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `filter` | Method | Add context fields to log record. | - |
| `RedactingFilter` | Class | Redacts sensitive information from log records. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `filter` | Method | Redact sensitive patterns from message and extra fields. | - |
| `formatters.py` | Module | Custom logging formatters for structured and human-readable output. | - |
| `JSONFormatter` | Class | Formats log records as single-line JSON for log aggregation. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `format` | Method | Format log record as JSON string. | - |
| `HumanFormatter` | Class | Formats log records for human readability with colors. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `format` | Method | Format record for human readability. | - |
| `SimpleFormatter` | Class | Simple formatter without colors for file output or minimal logging. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `format` | Method | Format record as simple string. | - |
