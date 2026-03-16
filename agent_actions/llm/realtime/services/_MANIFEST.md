# Online Services (realtime/services/) Manifest

## Overview

Services that back online flows (context building, prompt/schema loading, invocation
tracking, and metadata enrichment).

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `context.py` | Module | Builds context for streaming prompts plus historical lineage access. | `preprocessing`, `lineage` |
| `invocation.py` | Module | Dispatches online provider invocations across LLM/tool/HITL clients, including lazy provider resolution for optional/deprecated SDKs. | `llm.providers`, `workflow` |
| `prompt_service.py` | Module | Retrieves prompt definitions and caches static prompts. | `prompt_generation`, `tooling.docs` |
