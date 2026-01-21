# Ollama Manifest

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `batch_client.py` | Module | Ollama Local Batch Client - Simple local batch simulation. | - |
| `OllamaBatchClient` | Class | Ollama local batch client with in-process simulation. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `format_task_for_provider` | Method | Format task as OpenAI-compatible JSONL (for consistency). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `retrieve_results` | Method | Retrieve results from output JSONL file. | - |
| `client.py` | Module | Ollama client for agent-actions LLM invocation. | `errors`, `llm_invocation`, `utilities` |
| `OllamaClient` | Class | Ollama local LLM client for JSON and non-JSON invocations. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `invoke` | Method | Override invoke to enforce Ollama does NOT support JSON mode. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `call_json` | Method | NOTE: This method should not be called for Ollama. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `call_non_json` | Method | Plain-text chat (no schema enforcement). | - |
