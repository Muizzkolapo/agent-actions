# OpenAI Provider Manifest

## Overview

Adapter for OpenAI APIs that differentiates tool/batch/online clients across the
project.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `batch_client.py` | Module | Batch client for uploading and monitoring OpenAI jobs. `STATUS_MAPPING` maps every status of the SDK's `Batch` into `BatchStatus`: `cancelling` is in flight, `expired` is failed. | `llm.batch`, `llm.providers` |
| `compatible.py` | Module | One `OpenAIClient` subclass per row of `RUNTIME_PROFILES` (llamafile): default `base_url`, key placeholder for a runtime that takes no key, capabilities from the row. Registered as `compatible:<vendor>`. | `llm.realtime`, `validation.preflight` |
| `client.py` | Module | Online OpenAI client supporting tool calls and streaming. Sends each action to its own `base_url` when the action sets one. | `llm.realtime`, `llm.providers` |
