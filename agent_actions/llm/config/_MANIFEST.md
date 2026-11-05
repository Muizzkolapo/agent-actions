# Config Manifest

## Overview

Vendor configuration helpers used by both batch and online connectors.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `endpoints.py` | Module | `parse_endpoints()` validates the `endpoints:` block of `agent_actions.yml` into `Endpoint` rows (base `url` or one `${ENV_VAR}`, `auth` by env or command, extra `headers`, `timeout_seconds`), refusing a name that is a built-in vendor or profile. `load_project_endpoints()` validates the block beside its reader (`ConfigManager.get_user_agents`) and replaces the per-project registry that `project_endpoints()` / `project_endpoint()` read; a refused block registers nothing. | `config.manager` |
| `runtime_profiles.py` | Module | `RUNTIME_PROFILES`: one measured row per named OpenAI-compatible runtime (llamafile). `wire_vendor()` maps a profile vendor, or a declared endpoint, to the vendor whose formats it speaks (`openai`). | `llm.providers.openai`, `llm.realtime`, `output.response`, `validation.preflight` |
| `vendor.py` | Module | Defines vendor profiles + defaults (timeouts, engines). `vendor_names()` is the one list of names `model_vendor` accepts (`VendorType` + `RUNTIME_PROFILES` + the project's declared endpoints); `NON_LLM_VENDORS` names the vendors that run no model; `ONLINE_ONLY_VENDORS` (tool, hitl) names those the pipeline always runs online, which every batch check skips. | `llm.providers` |
