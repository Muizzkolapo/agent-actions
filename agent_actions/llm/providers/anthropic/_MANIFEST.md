# Anthropic Provider Manifest

## Overview

Anthropic-specific batch and online clients plus the thin adapter glue.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `batch_client.py` | Module | Batch client implementing Anthropic's API. A batch `canceling` is in flight; `ended` is completed, a canceled batch included. A status poll the server cannot answer now (a connection failure, `InternalServerError`, or one of `server_busy_errors`) is a transient error, asked again on the next run. Each line takes the action's `vendor_params`; the schema tool is forced as online, by `AnthropicClient._schema_tool_choice`. | `llm.batch`, `llm.providers` |
| `__init__.py` | Module | `PROMPT_CACHING_BETA_HEADER`, and `server_busy_errors(anthropic)`: the SDK's errors for a server that cannot answer now that are not `InternalServerError` (`OverloadedError` for 529, and `ServiceUnavailableError`/`DeadlineExceededError` for 503/504 on platforms that raise them), as far as the installed SDK defines them. | `llm.providers` |
| `client.py` | Module | Online Anthropic client for streaming responses. A 429 is a `RateLimitError`; a connection failure, an `InternalServerError` (5xx) or one of `server_busy_errors` (529 overloaded included) is a `NetworkError`; both are retried. `VENDOR_PARAMS` takes every keyword of `messages.create` (`extra_headers`/`extra_body`/`extra_query` merge). In JSON mode the request forces the one schema tool (`_schema_tool_choice`), except while `vendor_params.thinking` is on, and `vendor_params.tool_choice` replaces it. A `max_tokens` the SDK would refuse unstreamed (`_needs_streaming`: above 21,333, or the model's lower limit) goes through `messages.stream` and `get_final_message`. An empty text answer raises `empty_response_error` with the stop reason. | `llm.realtime`, `llm.providers` |
