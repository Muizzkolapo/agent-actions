# Groq Manifest

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `batch_client.py` | Module | Groq Batch API client implementation. | `errors` |
| `GroqBatchClient` | Class | Groq Batch API implementation of the BaseBatchClient interface. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `format_task_for_provider` | Method | Transform our BatchTask to Groq's expected format. | - |
| `client.py` | Module | Groq LLM client for agent-actions. | `errors`, `llm_invocation`, `preprocessing`, `utilities` |
| `GroqClient` | Class | Groq API client for JSON and non-JSON LLM invocations. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `call_json` | Method | - | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `call_non_json` | Method | - | - |
