# Realtime Services Manifest

## Overview

Services that back realtime flows (context building, prompt/schema loading, invocation
tracking, and metadata enrichment).

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `context.py` | Module | Builds context for streaming prompts plus historical lineage access. | `preprocessing`, `lineage` |
| `invocation.py` | Module | Tracks realtime LLM invocations, tokens, and retries. | `logging`, `llm.providers` |
| `prompt_service.py` | Module | Retrieves prompt definitions and caches static prompts. | `prompt_generation`, `tooling.docs` |
| `schema_service.py` | Module | Loads JSON/YAML schemas for realtime actions and expands them for output. | `output.response`, `validation` |
