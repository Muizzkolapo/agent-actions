# Ollama Provider Manifest

## Overview

Local Ollama adapter offering batch/online clients plus failure injection helpers.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `batch_client.py` | Module | Batch client interfacing with Ollama daemon. Its `Client` waits the action's `request_timeout` per request, passed in by the batch factory; unset or null, `LLMDefaults.REQUEST_TIMEOUT_SECONDS` (600). A task's `vendor_params` ride on its body and join the `chat()` call as online. As online, an unset temperature is not sent (`_get_default_temperature` is None), JSON mode with no schema sends `format="json"` on local, and a record's `finish_reason` is the response's `done_reason` (`length` when cut off at the limit). A failed request's line carries a `status` (`_failure_status`), which `_extract_error_status` reads: the HTTP status of a `ResponseError`; none for a failure the online client retries (a transport error), so a retry resends it; `_NOT_RETRIED_STATUS` for any other, so it is failed at once as online fails it. | `llm.batch`, `llm.providers`, `processing` |
| `client.py` | Module | Online Ollama client for streaming responses. A refused connection (which the ollama SDK re-raises as a builtin `ConnectionError`) or any other transport failure (`TRANSPORT_ERRORS`) is wrapped as `NetworkError`, so it is retried. The SDK raises an HTTP error answer as `ollama.ResponseError`, which both error mappings classify by its `status_code`: 429 is a `RateLimitError` and 500, 502, 503 and 504 a `NetworkError`, both retried; any other status (a 400, or a 404 for a model the server does not have) is a non-retriable `VendorAPIError`. `_VENDOR_PARAMS` (both clients' `VENDOR_PARAMS`) takes every argument of `Client.chat`; `options` merges into the generation options. An empty text answer whose `done_reason` is `length` is a `ResponseTruncatedError`. A JSON answer cut off at `done_reason: length` is a parse error naming it (`cut_off_parse_error`), never repaired into a partial object. | `llm.realtime`, `llm.providers` |
| `failure_injection.py` | Module | Simulates failures/latency for Ollama tests. | `tests`, `llm.providers` |
