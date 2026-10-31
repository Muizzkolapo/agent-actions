# Config Manifest

## Overview

Vendor configuration helpers used by both batch and online connectors.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `endpoints.py` | Module | `parse_endpoints()` validates the `endpoints:` block of `agent_actions.yml` into `Endpoint` rows (base `url` or one `${ENV_VAR}`, `auth` by env or command, extra `headers`, `timeout_seconds`), refusing a name that is a built-in vendor or profile. `set_project_endpoints()` / `project_endpoints()` hold the per-project registry that `load_project_config` fills and replaces on every load. | `config.path_config` |
| `runtime_profiles.py` | Module | `RUNTIME_PROFILES`: one measured row per named OpenAI-compatible runtime (llamafile). `wire_vendor()` maps a profile vendor to the vendor whose formats it speaks. | `llm.providers.openai`, `llm.realtime`, `output.response`, `validation.preflight` |
| `vendor.py` | Module | Defines vendor profiles + defaults (timeouts, engines). `vendor_names()` is the one list of names `model_vendor` accepts (`VendorType` + `RUNTIME_PROFILES`); `NON_LLM_VENDORS` names the vendors that run no model; `ONLINE_ONLY_VENDORS` (tool, hitl) names those the pipeline always runs online, which every batch check skips. | `llm.providers` |
