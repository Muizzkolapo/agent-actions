# Recovery Manifest

## Overview

Transport-layer retry tracking and the shared response validators processors
use to judge an LLM response.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `response_validator.py` | Module | Shared `ResponseValidator` protocol (`UdfValidator`, `SchemaValidator`, `ComposedValidator`) and `build_validation_feedback()`. | `validation`, `schema` |
| `retry.py` | Module | Retry helpers with backoff used across processing pipelines. `RetryService.execute` waits the `retry_after` an error's context carries (the provider's Retry-After), capped at `max_delay` with a warning; without one it waits a jittered backoff from `base_delay`. `create_retry_service_from_config` reads `max_attempts`, `base_delay` and `max_delay` from the action's `retry:` block. `ResponseTruncatedError` is in `RETRIABLE_ERRORS`, classified `truncated`. | `retry`, `logging` |
