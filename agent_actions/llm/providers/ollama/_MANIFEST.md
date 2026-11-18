# Ollama Provider Manifest

## Overview

Local Ollama adapter offering batch/online clients plus failure injection helpers.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `batch_client.py` | Module | Batch client interfacing with Ollama daemon. Ollama has no batch API, so the batch is a loop in this process, run at submit time by a thread pool. Its worker count (`_get_max_workers`) is the action's `batch_max_workers` (handed in by the batch factory), else `OLLAMA_BATCH_MAX_WORKERS`, else 1; a value below 1 falls back to 1 and one above 32 is clamped, the warning naming the setting the value came from. `record_concurrency`, the online setting, never sets it. Its `Client` waits the action's `request_timeout` per request, passed in by the batch factory; unset or null, `LLMDefaults.REQUEST_TIMEOUT_SECONDS` (600). A task's `vendor_params` ride on its body and join the `chat()` call as online. As online, an unset temperature is not sent, JSON mode with no schema sends `format="json"` on local, and a record's `finish_reason` is the response's `done_reason` (`length` when cut off at the limit). `_parse_json_content` reads a reply as online reads one in JSON mode: a list holding a non-object is one record under `response`, and text that is neither an object nor a list (a number, `true`) stays text, a parse error in JSON mode. | `llm.batch`, `llm.providers` |
| `client.py` | Module | Online Ollama client for streaming responses. A refused connection (which the ollama SDK re-raises as a builtin `ConnectionError`) or any other transport failure (`TRANSPORT_ERRORS`) is wrapped as `NetworkError`, so it is retried. The SDK raises an HTTP error answer as `ollama.ResponseError`, which both error mappings classify by its `status_code`: 429 is a `RateLimitError` and 500, 502, 503 and 504 a `NetworkError`, both retried; any other status (a 400, or a 404 for a model the server does not have) is a non-retriable `VendorAPIError`. `_VENDOR_PARAMS` (both clients' `VENDOR_PARAMS`) takes every argument of `Client.chat`; `options` merges into the generation options. An empty text answer whose `done_reason` is `length` is a `ResponseTruncatedError`. | `llm.realtime`, `llm.providers` |
| `failure_injection.py` | Module | Simulates failures/latency for Ollama tests. | `tests`, `llm.providers` |
