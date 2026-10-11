# Gemini Provider Manifest

## Overview

Google Gemini adapter with batch/online clients.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `batch_client.py` | Module | Batch Gemini client implementation. Maps every `JobState` into `BatchStatus`: queued, pending, running, paused, updating and cancelling are in flight; succeeded and partially succeeded are completed, and the results of either are read; failed and expired are failed. | `llm.batch`, `llm.providers` |
| `client.py` | Module | Online Gemini client wrapper with prompt shaping. | `llm.realtime`, `llm.providers` |
