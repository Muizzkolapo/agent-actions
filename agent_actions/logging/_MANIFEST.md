# Logging Manifest

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `config.py` | Module | Logging configuration dataclasses. | - |
| `FileHandlerSettings` | Class | File handler configuration settings. | - |
| `LoggingConfig` | Class | Central logging configuration. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `from_project_config` | Method | Create LoggingConfig from project configuration. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `from_environment` | Method | Create LoggingConfig from environment variables. | - |
| `context.py` | Module | DEPRECATED: Re-exports EventManager for backwards compatibility. | - |
| `factory.py` | Module | Logger factory for centralized logging configuration. | `logging` |
| `LoggerFactory` | Class | Factory for creating and configuring loggers. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `initialize` | Method | Initialize the logging system with configuration. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_logger` | Method | Get a logger with the given name. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `set_level` | Method | Set log level for a logger. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `set_debug` | Method | Enable or disable debug logging globally. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_config` | Method | Get the current logging configuration. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `is_initialized` | Method | Check if the factory has been initialized. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `reset` | Method | Reset the factory state. | - |
| `filters.py` | Module | Custom logging filters. | `logging` |
| `RedactingFilter` | Class | Redacts sensitive information from log records. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `filter` | Method | Redact sensitive patterns from message and extra fields. | - |
| `formatters.py` | Module | Custom logging formatters. | - |
| `JSONFormatter` | Class | Formats log records as single-line JSON for log aggregation. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `format` | Method | Format log record as JSON string. | - |
