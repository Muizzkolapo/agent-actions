# Gemini Provider Manifest

## Overview

Google Gemini adapter with batch/online clients.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `batch_client.py` | Module | Batch Gemini client implementation. Its `genai.Client` waits `LLMDefaults.REQUEST_TIMEOUT_SECONDS` (in ms) per request. Maps every `JobState` into `BatchStatus`: queued, pending, running, paused, updating and cancelling are in flight; succeeded and partially succeeded are completed, and the results of either are read; failed and expired are failed. An action's `vendor_params` go into `generation_config`, except the request-level fields (`_REQUEST_LEVEL_FIELDS`), which go beside it. | `llm.batch`, `llm.providers` |
| `client.py` | Module | Online Gemini client wrapper with prompt shaping. A transport failure the SDK lets through (`TRANSPORT_ERRORS`, such as `httpx.ConnectError`) is wrapped as `NetworkError`, so it is retried. `VENDOR_PARAMS` takes the fields of `GenerateContentConfig` but `http_options`, joined into the config the request carries. An empty text answer cut off at `MAX_TOKENS` is a `ResponseTruncatedError`. | `llm.realtime`, `llm.providers` |
