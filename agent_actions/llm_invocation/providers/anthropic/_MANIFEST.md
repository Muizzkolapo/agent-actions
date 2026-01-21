# Anthropic Manifest

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `batch_client.py` | Module | Anthropic Batch API client implementation. | `errors` |
| `AnthropicBatchClient` | Class | Anthropic Message Batches API implementation of the BaseBatchClient interface. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `format_task_for_provider` | Method | Transform our BatchTask to Anthropic's Message Batches API format. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `retrieve_results` | Method | Retrieve and transform Anthropic batch results to our format. | - |
| `client.py` | Module | Anthropic Claude client for agent-actions. | `errors`, `llm_invocation`, `preprocessing`, `utilities` |
| `AnthropicClient` | Class | Anthropic Claude API client for JSON and non-JSON LLM invocations. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `call_json` | Method | - | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `call_non_json` | Method | Non-JSON mode is not implemented for Claude. | - |
