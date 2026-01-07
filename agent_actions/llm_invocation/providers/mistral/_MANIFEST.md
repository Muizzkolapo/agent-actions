# Mistral Manifest

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `batch_client.py` | Module | Mistral Batch API client implementation. | `errors` |
| `MistralBatchClient` | Class | Mistral Batch API implementation of the BaseBatchClient interface. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `format_task_for_provider` | Method | Transform our BatchTask to Mistral's expected format. | - |
| `client.py` | Module | Mistral client for agent-actions LLM invocation. | `errors`, `llm_invocation`, `preprocessing`, `utilities` |
| `MistralClient` | Class | Mistral AI API client for JSON and non-JSON LLM invocations. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `call_json` | Method | - | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `call_non_json` | Method | - | - |
