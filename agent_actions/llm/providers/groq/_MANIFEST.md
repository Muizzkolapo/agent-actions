# Groq Provider Manifest

## Overview

Groq Cloud integration with batch and streaming helpers.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `batch_client.py` | Module | Batch client for scheduling Groq jobs. `STATUS_MAPPING` maps every status of the SDK's batch types into `BatchStatus`: `cancelling` is in flight, `expired` is failed. Each line's body takes the action's `vendor_params`. `_vendor_label` names Groq in an empty-response error. | `llm.batch`, `llm.providers` |
| `client.py` | Module | Online Groq client for low-latency inference. `VENDOR_PARAMS` takes every keyword of `chat.completions.create`. Neither call sends `max_tokens` unless the action sets it, as batch does not. An empty text answer cut off at `length` is a `ResponseTruncatedError`. At import it builds the models of `ChatCompletion` (`build_sdk_models`), which the SDK may otherwise build on first parse, in several record threads at once. A JSON answer with no content names its finish reason (`empty_parse_error`), and one cut off at `length` is a parse error (`cut_off_parse_error`), never repaired into a partial object. A text answer with no content at all raises `empty_response_error`. | `llm.realtime`, `llm.providers` |
