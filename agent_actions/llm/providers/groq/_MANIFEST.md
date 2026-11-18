# Groq Provider Manifest

## Overview

Groq Cloud integration with batch and streaming helpers.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `batch_client.py` | Module | Batch client for scheduling Groq jobs. `STATUS_MAPPING` maps every status of the SDK's batch types into `BatchStatus`: `cancelling` is in flight, `expired` is failed. Each line's `messages` are the online request's (`MessageBuilder.build` with the online client's arguments): one system message, the tagged prompt with the JSON rule in JSON mode, the instructions template otherwise. Each line's body takes the action's `vendor_params`. A JSON action with no schema sends `response_format: {type: json_object}`, as online. | `llm.batch`, `llm.providers` |
| `client.py` | Module | Online Groq client for low-latency inference. `VENDOR_PARAMS` takes every keyword of `chat.completions.create`. Neither call sends `max_tokens` unless the action sets it, as batch does not. An empty text answer cut off at `length` is a `ResponseTruncatedError`. At import it builds the models of `ChatCompletion` (`build_sdk_models`), which the SDK may otherwise build on first parse, in several record threads at once. | `llm.realtime`, `llm.providers` |
