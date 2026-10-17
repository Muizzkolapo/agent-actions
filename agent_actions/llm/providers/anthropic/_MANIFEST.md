# Anthropic Provider Manifest

## Overview

Anthropic-specific batch and online clients plus the thin adapter glue.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `batch_client.py` | Module | Batch client implementing Anthropic's API. A batch `canceling` is in flight; `ended` is completed, a canceled batch included. A status poll the server cannot answer now (a connection failure, `InternalServerError`, or one of `server_busy_errors`) is a transient error, asked again on the next run. | `llm.batch`, `llm.providers` |
| `__init__.py` | Module | `PROMPT_CACHING_BETA_HEADER`, and `server_busy_errors(anthropic)`: the SDK's errors for a server that cannot answer now that are not `InternalServerError` (`OverloadedError` for 529, and `ServiceUnavailableError`/`DeadlineExceededError` for 503/504 on platforms that raise them), as far as the installed SDK defines them. | `llm.providers` |
| `client.py` | Module | Online Anthropic client for streaming responses. A 429 is a `RateLimitError`; a connection failure, an `InternalServerError` (5xx) or one of `server_busy_errors` (529 overloaded included) is a `NetworkError`; both are retried. | `llm.realtime`, `llm.providers` |
