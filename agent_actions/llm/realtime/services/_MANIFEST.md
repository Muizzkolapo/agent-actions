# Online Services (realtime/services/) Manifest

## Overview

Services that back online flows (context building, prompt/schema loading, invocation
tracking, and metadata enrichment).

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `context.py` | Module | Builds context for streaming prompts plus historical lineage access. An LLM's context string is encoded with `ensure_json_safe` and `deep_json`, at any depth. | `preprocessing`, `lineage` |
| `invocation.py` | Module | Dispatches online provider invocations across LLM/tool/HITL clients, including lazy provider resolution for optional/deprecated SDKs; a provider client that raises `QuotaExceededError` ends the run here: `invoke_client` raises `ProviderQuotaStop` in its place, so no handler above fails the record; a `model_vendor` that names a declared endpoint resolves to `compatible.endpoint_client`. | `llm.providers`, `workflow` |
| `prompt_service.py` | Module | Retrieves prompt definitions and caches static prompts. `debug_print_prompt` prints a call's prompt, context and schema under `prompt_debug` in one write, so the blocks of actions running in parallel do not interleave; the batch preparator calls it for each row it prepares. | `prompt_generation`, `tooling.docs` |
