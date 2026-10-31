# OpenAI Provider Manifest

## Overview

Adapter for OpenAI APIs that differentiates tool/batch/online clients across the
project.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `batch_client.py` | Module | Batch client for uploading and monitoring OpenAI jobs. `STATUS_MAPPING` maps every status of the SDK's `Batch` into `BatchStatus`: `cancelling` is in flight, `expired` is failed. | `llm.batch`, `llm.providers` |
| `compatible.py` | Module | One `OpenAIClient` subclass per row of `RUNTIME_PROFILES` (llamafile): default `base_url`, key placeholder for a runtime that takes no key, capabilities from the row. Registered as `compatible:<vendor>`. `endpoint_client(name)` builds an `EndpointClient` for a declared endpoint (`llm.config.endpoints`): its url, headers, timeout and credential (`env`; `command`, run from the project root once per command under a lock, again after `refresh_seconds` or once after a 401; or none; a non-Authorization auth header drops the SDK's `Authorization` unless `headers:` declares one), inherited `api_key`/`base_url` ignored, a reply that does not match the schema returned as `_parse_error`, every secret read registered with the redactor. `ENDPOINT_CAPABILITIES` refuses batch. | `llm.realtime`, `validation.preflight` |
| `endpoint_probe.py` | Module | `probe_endpoint(name, model)`: one structured-output request to a declared endpoint for `--verify-keys`; a refused credential (401/403), an unreachable server and a reply that does not match the one-field probe schema are errors naming the endpoint. | `validation.preflight` |
| `client.py` | Module | Online OpenAI client supporting tool calls and streaming. Sends each action to its own `base_url` when the action sets one; `_client_options()` is the one place the SDK client's constructor kwargs come from, which a subclass extends. | `llm.realtime`, `llm.providers` |
