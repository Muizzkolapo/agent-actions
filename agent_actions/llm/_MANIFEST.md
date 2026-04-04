# LLM Manifest

## Overview

LLM integrations provide both batch and online execution paths, vendor profile
configuration, and a growing set of provider adapters (OpenAI, Anthropic, Claude,
Cohere, etc.).

## Sub-Modules

| Sub-Module | Description |
|------------|-------------|
| [batch](batch/_MANIFEST.md) | Batch execution helpers, CLI entrypoints, and services for running workflows as jobs. |
| [config](config/_MANIFEST.md) | Shared vendor configuration utilities. |
| [providers](providers/_MANIFEST.md) | Provider-specific clients, failure injection, usage tracking, and tooling. |
| [realtime](realtime/_MANIFEST.md) | Online runner utilities, context handlers, and invocation services. |

## Project Surface

> How this module interacts with the user's project files.

| Symbol | User File | Interaction | Config Key |
|--------|-----------|-------------|------------|
| `ClientInvocationService.invoke_client()` | — | Reads | `actions[].model_vendor`, `actions[].model_name` |
| `AgentManager.get_agent_paths()` | `agent_config/{workflow}.yml` | Reads | — |
| `AgentManager.get_agent_paths()` | `agent_io/` | Reads | — |
| `BatchSubmissionService` | `agent_io/target/{action}/batch/.batch_registry.json` | Reads/Writes | — |
| `BatchRetrievalService` | `agent_io/target/{action}/batch/` | Reads | — |
| `BatchRegistryManager` | `agent_io/target/{action}/batch/.batch_registry.json` | Reads/Writes | — |
| `extract_generation_params()` | — | Reads | `actions[].temperature`, `actions[].max_tokens`, `actions[].top_p` |
| `VendorType` | — | Validates | `actions[].model_vendor` |
| `ToolClient` | `tools/{workflow}/{tool}.py` | Reads | `actions[].impl`, `tool_path` |
| `batch_cli.status()` | `agent_io/target/{action}/batch/` | Reads | — |
| `batch_cli.retrieve()` | `agent_io/target/{action}/batch/` | Reads | — |
| `AgentManager.clean_directory()` | `agent_io/target/{action}/` | Writes | — |

**Internal only**: `_resolve_client()`, `CLIENT_REGISTRY`, `PROVIDER_MESSAGE_CONFIGS`, `_VENDOR_PACKAGES`, `PromptService.debug_print_prompt()`, `BaseVendorConfig` and per-vendor config classes, `error_wrapper`, `failure_injection`, `usage_tracker`, `mixins` — no direct project surface.

**Examples** — see this module in action:
- [`examples/review_analyzer/agent_workflow/review_analyzer/agent_config/review_analyzer.yml`](../../examples/review_analyzer/agent_workflow/review_analyzer/agent_config/review_analyzer.yml) — multi-vendor workflow using `groq`, `openai`, `ollama`, and `anthropic` providers with per-action `model_vendor` / `model_name` / `api_key` overrides
- [`examples/review_analyzer/tools/review_analyzer/aggregate_quality_scores.py`](../../examples/review_analyzer/tools/review_analyzer/aggregate_quality_scores.py) — tool implementation invoked by `ToolClient` via `kind: tool` + `impl:` config
- [`examples/contract_reviewer/agent_workflow/contract_reviewer/agent_config/contract_reviewer.yml`](../../examples/contract_reviewer/agent_workflow/contract_reviewer/agent_config/contract_reviewer.yml) — workflow with tool actions using FILE granularity (map-reduce pattern)
- [`examples/incident_triage/agent_workflow/incident_triage/agent_config/incident_triage.yml`](../../examples/incident_triage/agent_workflow/incident_triage/agent_config/incident_triage.yml) — workflow demonstrating `reprompt` config with `validation` and `max_attempts` keys consumed by the online invocation path
