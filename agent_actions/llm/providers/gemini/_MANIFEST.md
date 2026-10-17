# Gemini Provider Manifest

## Overview

Google Gemini adapter with batch/online clients.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `batch_client.py` | Module | Batch Gemini client implementation. Maps every `JobState` into `BatchStatus`: queued, pending, running, paused, updating and cancelling are in flight; succeeded and partially succeeded are completed, and the results of either are read; failed and expired are failed. | `llm.batch`, `llm.providers` |
| `client.py` | Module | Online Gemini client wrapper with prompt shaping. A transport failure the SDK lets through (`TRANSPORT_ERRORS`, such as `httpx.ConnectError`) is wrapped as `NetworkError`, so it is retried. | `llm.realtime`, `llm.providers` |
