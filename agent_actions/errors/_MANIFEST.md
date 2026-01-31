# Errors Manifest

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `base.py` | Module | Base exception classes for agent-actions. | `utilities` |
| `AgentActionsError` | Class | Base exception for all agent-actions errors. | - |
| `common.py` | Module | Common errors used across multiple domains. | `errors` |
| `InvalidParameterError` | Class | Raised when invalid or missing parameters are provided. | - |
| `configuration.py` | Module | Configuration-related errors. | `errors` |
| `ConfigurationError` | Class | Base exception for configuration-related errors. | - |
| `ConfigValidationError` | Class | Raised when configuration validation fails. | - |
| `DuplicateFunctionError` | Class | Raised when duplicate @udf_tool function names are detected. | - |
| `FunctionNotFoundError` | Class | Raised when a UDF is not found in the registry. | - |
| `UDFLoadError` | Class | Raised when a UDF module fails to load. | - |
| `AgentNotFoundError` | Class | Raised when a specified agent cannot be found. | - |
| `ProjectNotFoundError` | Class | Raised when a command requires being in a project but agent_actions.yml is not found. | - |
| `EnvironmentConfigError` | Class | Raised when environment configuration is invalid or missing. | - |
| `external_services.py` | Module | External service and vendor API errors. | `errors` |
| `ExternalServiceError` | Class | Base exception for external service interactions. | - |
| `VendorAPIError` | Class | Raised when an error occurs during a call to a vendor's API. | - |
| `OpenAIError` | Class | Specific error for OpenAI API failures. | - |
| `AnthropicError` | Class | Specific error for Anthropic API failures. | - |
| `GeminiError` | Class | Specific error for Gemini API failures. | - |
| `NetworkError` | Class | Raised when network-related errors occur (timeout, connection, etc). | - |
| `RateLimitError` | Class | Raised when API rate limits are exceeded. | - |
| `filesystem.py` | Module | File system operation errors. | `errors` |
| `FileSystemError` | Class | Base exception for file system operations. | - |
| `FileLoadError` | Class | Raised when a file cannot be loaded. | - |
| `FileWriteError` | Class | Raised when a file cannot be written. | - |
| `DirectoryError` | Class | Raised when directory operations fail. | - |
| `operations.py` | Module | Operational errors for agent execution and template rendering. | `errors` |
| `OperationalError` | Class | Base exception for operational errors. | - |
| `AgentExecutionError` | Class | Raised when an error occurs during agent execution. | - |
| `TemplateRenderingError` | Class | Raised when an error occurs during template rendering. | - |
| `preflight.py` | Module | Pre-flight validation errors for unified batch/online error handling. | `errors` |
| `PreFlightValidationError` | Class | Base exception for all pre-flight validation errors. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `format_user_message` | Method | Format a user-friendly error message with all details. | - |
| `TemplateVariableError` | Class | Raised when Jinja2 template references undefined variables. Includes namespace context for enhanced error messages. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `namespace_context` | Attr | Dict mapping namespace names to available fields for diagnostic output. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `template_line` | Attr | Line number in template where error occurred (for syntax errors). | - |
| `ContextStructureError` | Class | Raised when context data structure doesn't match expected schema. | - |
| `DependencyValidationError` | Class | Raised when circular or invalid dependencies are detected. | - |
| `VendorConfigError` | Class | Raised when vendor configuration is invalid or incompatible. | - |
| `PathValidationError` | Class | Raised when file or directory paths are invalid or inaccessible. | - |
| `processing.py` | Module | Processing and transformation errors. | `errors` |
| `ProcessingError` | Class | Base exception for processing operations. | - |
| `TransformationError` | Class | Raised when data transformation fails. | - |
| `GenerationError` | Class | Raised when data generation fails. | - |
| `WorkflowError` | Class | Raised when an error occurs in workflow processing. | - |
| `SerializationError` | Class | Raised when serialization/deserialization fails. | - |
| `resources.py` | Module | Resource-related errors (memory, dependencies, etc). | `errors` |
| `ResourceError` | Class | Base exception for resource-related errors. | - |
| `ResourceMemoryError` | Class | Raised when memory-related issues occur. | - |
| `DependencyError` | Class | Raised when a required dependency is not provided or cannot be loaded. | - |
| `validation.py` | Module | Validation-related errors. | `errors` |
| `ValidationError` | Class | Base exception for validation failures. | - |
| `PromptValidationError` | Class | Raised when prompt validation fails. | - |
| `DataValidationError` | Class | Raised when data validation fails. | - |
| `SchemaValidationError` | Class | Raised when schema validation fails. | - |
