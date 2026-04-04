# Errors Manifest

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `base.py` | Module | Base exception classes for agent-actions. `AgentActionsError.__init__` defensively copies `context` (`dict(context) if context else {}`), preventing mutation by callers — inherited by all subclasses. | `utilities` |
| `AgentActionsError` | Class | Base exception for all agent-actions errors. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `detailed_str` | Method | Return message with full context dict — use at debug/event boundaries. | - |
| `get_error_detail` | Function | Return `detailed_str()` for `AgentActionsError`, else `str()`. Use instead of `str(error)` at structured-logging boundaries. | - |
| `common.py` | Module | Common errors used across multiple domains. | `errors` |
| `InvalidParameterError` | Class | Raised when invalid or missing parameters are provided. | - |
| `configuration.py` | Module | Configuration-related errors. `ConfigurationError.__init__` guards `config_key` with `config_key or message or "<no key>"` to ensure the interpolated key is never `None`. | `errors` |
| `ConfigurationError` | Class | Base exception for configuration-related errors. | - |
| `ConfigValidationError` | Class | Raised when configuration validation fails. | - |
| `DuplicateFunctionError` | Class | Raised when duplicate @udf_tool function names are detected. | - |
| `FunctionNotFoundError` | Class | Raised when a UDF is not found in the registry. | - |
| `UDFLoadError` | Class | Raised when a UDF module fails to load. | - |
| `AgentNotFoundError` | Class | Raised when a specified agent cannot be found. | - |
| `ProjectNotFoundError` | Class | Raised when a command requires being in a project but agent_actions.yml is not found. | - |
| `external_services.py` | Module | External service and vendor API errors. `ExternalServiceError.__init__` guards `endpoint` with `endpoint or "<unknown>"` before interpolation. | `errors` |
| `ExternalServiceError` | Class | Base exception for external service interactions. | - |
| `VendorAPIError` | Class | Raised when an error occurs during a call to a vendor's API. | - |
| `AnthropicError` | Class | Specific error for Anthropic API failures. | - |
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
| `TemplateVariableError` | Class | Raised when Jinja2 template references undefined variables. Includes namespace context for enhanced error messages. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `namespace_context` | Attr | Dict mapping namespace names to available fields for diagnostic output. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `template_line` | Attr | Line number in template where error occurred (for syntax errors). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `field_context_metadata` | Attr | Metadata about stored vs loaded fields per namespace (for enhanced diagnostics). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `storage_hints` | Attr | Dict mapping variable names to storage info when field exists in storage but wasn't loaded. | - |
| `preflight.py` | Module | Pre-flight validation errors for unified batch/online error handling. | `errors` |
| `_render_sections` | Function | Render a user-friendly multi-section error message from (label, value) pairs. | - |
| `PreFlightValidationError` | Class | Base exception for all pre-flight validation errors. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `format_user_message` | Method | Format a user-friendly error message with all details. | - |
| `ContextStructureError` | Class | Raised when context data structure doesn't match expected schema. | - |
| `VendorConfigError` | Class | Raised when vendor configuration is invalid or incompatible. | - |
| `PathValidationError` | Class | Raised when file or directory paths are invalid or inaccessible. | - |
| `processing.py` | Module | Processing and transformation errors. | `errors` |
| `ProcessingError` | Class | Base exception for processing operations. | - |
| `TransformationError` | Class | Raised when data transformation fails. | - |
| `GenerationError` | Class | Raised when data generation fails. | - |
| `WorkflowError` | Class | Raised when an error occurs in workflow processing. | - |
| `SerializationError` | Class | Raised when serialization/deserialization fails. | - |
| `EmptyOutputError` | Class | Raised when an action produces empty output and on_empty=error. | - |
| `resources.py` | Module | Resource-related errors (memory, dependencies, etc). | `errors` |
| `ResourceError` | Class | Base exception for resource-related errors. | - |
| `DependencyError` | Class | Raised when a required dependency is not provided or cannot be loaded. | - |
| `validation.py` | Module | Validation-related errors. | `errors` |
| `ValidationError` | Class | Base exception for validation failures. | - |
| `PromptValidationError` | Class | Raised when prompt validation fails. | - |
| `DataValidationError` | Class | Raised when data validation fails. | - |
| `SchemaValidationError` | Class | Raised when schema validation fails. | - |

## Project Surface

> How this module interacts with the user's project files.

The `errors` module has **zero direct project file surface**. It does not read, write, validate, or transform any user project files. It defines the exception hierarchy used by every other module.

However, several error classes carry project-file context in their `context` dict, making them the user-visible surface when something goes wrong:

| Symbol | Triggered By | User File Context |
|--------|-------------|-------------------|
| `ConfigurationError` | Invalid workflow YAML | `agent_config/{workflow}/{workflow}.yml` |
| `ConfigValidationError` | Schema/key validation failure | `agent_actions.yml`, `agent_config/{workflow}/{workflow}.yml` |
| `ProjectNotFoundError` | Missing `agent_actions.yml` | `agent_actions.yml` |
| `AgentNotFoundError` | Missing agent config directory | `agent_config/{workflow}/` |
| `FileLoadError` | Cannot read a config/schema/prompt file | `agent_config/{workflow}/{workflow}.yml`, `schema/{workflow}/{action}.yml`, `prompt_store/{workflow}.md` |
| `FileWriteError` | Cannot write to output directory | `agent_io/target/{action}/` |
| `SchemaValidationError` | LLM output mismatches schema | `schema/{workflow}/{action}.yml` |
| `TemplateRenderingError` | Jinja2 template error in config | `templates/`, `agent_config/{workflow}/{workflow}.yml` |
| `TemplateVariableError` | Undefined variable in prompt template | `prompt_store/{workflow}.md` |
| `DuplicateFunctionError` | Duplicate `@udf_tool` names | `tools/{workflow}/` |
| `FunctionNotFoundError` | `impl` reference not found | `tools/{workflow}/`, `agent_config/{workflow}/{workflow}.yml` (`actions[].impl`) |
| `UDFLoadError` | Python import error in tool file | `tools/{workflow}/` |
| `PreFlightValidationError` | Pre-run checks fail | `agent_config/{workflow}/{workflow}.yml`, `.env` |
| `VendorConfigError` | Invalid vendor/API key config | `.env`, `agent_config/{workflow}/{workflow}.yml` (`actions[].api_key`, `actions[].model_vendor`) |
| `EmptyOutputError` | Action produces no output | `agent_config/{workflow}/{workflow}.yml` (`actions[].on_empty`) |

**Consumed by**: `config`, `validation`, `workflow`, `processing`, `cli`, `prompt`, `input`, `output`, `storage`, `llm` -- every module in the framework imports from `errors`.

**Examples** -- see these errors in action:
- [`examples/book_catalog_enrichment/agent_actions.yml`](../../examples/book_catalog_enrichment/agent_actions.yml) -- `ProjectNotFoundError` raised if this file is missing; `ConfigValidationError` raised if YAML is malformed or `schema_path` is absent
- [`examples/book_catalog_enrichment/agent_workflow/book_catalog_enrichment/agent_config/book_catalog_enrichment.yml`](../../examples/book_catalog_enrichment/agent_workflow/book_catalog_enrichment/agent_config/book_catalog_enrichment.yml) -- `ConfigurationError` raised if workflow validation fails (duplicate actions, dangling deps, circular deps); `TemplateRenderingError` if Jinja2 template rendering fails
- [`examples/book_catalog_enrichment/tools/book_catalog_enrichment/format_catalog_entry.py`](../../examples/book_catalog_enrichment/tools/book_catalog_enrichment/format_catalog_entry.py) -- `DuplicateFunctionError` if `@udf_tool` name collides; `FunctionNotFoundError` if `impl: format_catalog_entry` cannot resolve
- [`examples/incident_triage/agent_workflow/incident_triage/agent_config/incident_triage.yml`](../../examples/incident_triage/agent_workflow/incident_triage/agent_config/incident_triage.yml) -- `VendorConfigError` surfaced during preflight if `GROQ_API_KEY` is missing; `ConfigurationError` if version config is invalid
- [`examples/review_analyzer/schema/review_analyzer/score_quality.yml`](../../examples/review_analyzer/schema/review_analyzer/score_quality.yml) -- `SchemaValidationError` raised at runtime if LLM output does not match this schema's `properties`/`required` fields
