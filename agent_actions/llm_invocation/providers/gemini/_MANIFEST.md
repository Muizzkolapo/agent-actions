# Gemini Manifest

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `batch_client.py` | Module | Gemini Batch API client implementation. | `errors` |
| `GeminiBatchClient` | Class | Gemini Batch API implementation of the BaseBatchClient interface. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `format_task_for_provider` | Method | Transform our BatchTask to Gemini's expected format. | - |
| `client.py` | Module | Gemini client for agent-actions LLM invocation. | `errors`, `llm_invocation`, `preprocessing`, `utilities` |
| `GeminiClient` | Class | Google Gemini API client for JSON and non-JSON LLM invocations. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `call_json` | Method | - | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `call_non_json` | Method | - | - |
