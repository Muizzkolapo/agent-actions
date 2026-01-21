# Providers Manifest

## Sub-Modules

| Sub-Module | Description |
|------------|-------------|
| [anthropic](anthropic/_MANIFEST.md) | - |
| [cohere](cohere/_MANIFEST.md) | - |
| [gemini](gemini/_MANIFEST.md) | - |
| [groq](groq/_MANIFEST.md) | Groq client module. |
| [mistral](mistral/_MANIFEST.md) | Mistral client module. |
| [ollama](ollama/_MANIFEST.md) | - |
| [openai](openai/_MANIFEST.md) | - |
| [tools](tools/_MANIFEST.md) | - |

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `batch_client_base.py` | Module | Base batch client interface for batch processing systems. | `errors`, `utilities` |
| `BatchTask` | Class | Provider-agnostic representation of a batch task. | - |
| `BatchResult` | Class | Provider-agnostic representation of a batch result. | - |
| `BaseBatchClient` | Class | Abstract base class for batch processing clients. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `prepare_tasks` | Method | Convert agent-actions data format to provider-specific task format (Template Method). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `format_task_for_provider` | Method | Transform standardized BatchTask to provider-specific format. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `submit_batch` | Method | Submit a batch job to the provider (Template Method). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `check_status` | Method | Check the status of a batch job (Template Method). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `retrieve_results` | Method | Retrieve and parse results from a completed batch job (Template Method). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `parse_provider_response` | Method | Transform provider-specific response format to standardized BatchResult (Template Method). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `compile_schema` | Method | DEPRECATED: This method is no longer used for schema compilation. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_supported_models` | Method | Get list of model names supported by this provider. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate_config` | Method | Validate that the agent configuration is compatible with this provider (Template Method). | - |
| `batch_client_factory.py` | Module | Factory for creating batch clients based on configuration. | `errors` |
| `BatchClientFactory` | Class | Factory class for creating batch client instances. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `create_client` | Method | Create a batch client instance. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_supported_clients` | Method | Get list of supported client types. | - |
| `client_base.py` | Module | Base client for agent-actions LLM invocation. | `errors`, `utilities` |
| `BaseClient` | Class | Common functionality shared by LLM clients. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `redact_sensitive_data` | Method | Redact sensitive data from request/response for logging. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_api_key` | Method | Return the API key using the name specified in ``agent_config``. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `call_json` | Method | Call vendor API in JSON mode with schema. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `call_non_json` | Method | Call vendor API in non-JSON mode. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `invoke` | Method | Dispatch to JSON or non-JSON methods after loading the API key. | - |
| `mixins.py` | Module | Reusable mixins for vendor handlers to reduce code duplication. | `errors` |
| `JSONResponseMixin` | Class | Mixin providing standardized JSON response parsing with error handling. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `parse_json_response` | Method | Parse JSON response with standardized error handling and logging. | - |
| `GenericErrorHandlerMixin` | Class | Mixin providing standardized generic error handling for vendor API calls. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `handle_generic_error` | Method | Handle generic exceptions with standardized logging and re-raising. | - |
| `OpenAICompatibleResponseMixin` | Class | Mixin for providers that use OpenAI-compatible response format. | - |
| `mock_batch_client.py` | Module | Mock Batch Client for Testing Retry Functionality. | `llm_invocation` |
| `MockBatchState` | Class | Tracks state of a mock batch job. | - |
| `MockBatchClient` | Class | Mock batch client for testing retry functionality. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `format_task_for_provider` | Method | Format task for mock processing. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `reset` | Method | Reset all mock batch state. Useful between tests. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_batch_state` | Method | Get internal state of a batch (for testing/debugging). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `set_failure_ids_for_batch` | Method | Manually set which IDs should fail for a specific batch. | - |
| `usage_tracker.py` | Module | Thread-safe token usage tracking for LLM providers. | - |
| `set_last_usage` | Function | Store token usage in thread-local storage. | - |
| `get_last_usage` | Function | Retrieve token usage from thread-local storage. | - |
| `clear_usage` | Function | Clear usage data from thread-local storage. | - |
