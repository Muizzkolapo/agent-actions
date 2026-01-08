# Openai Manifest

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `batch_client.py` | Module | OpenAI Batch API client implementation. | `errors` |
| `OpenAIBatchClient` | Class | OpenAI Batch API implementation of the BaseBatchClient interface. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `format_task_for_provider` | Method | Transform our BatchTask to OpenAI's expected format. | - |
| `client.py` | Module | OpenAI client for agent-actions. | `errors`, `llm_invocation`, `preprocessing`, `utilities` |
| `OpenAIClient` | Class | OpenAI API client for JSON and non-JSON LLM invocations. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `call_json` | Method | - | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `call_non_json` | Method | - | - |
