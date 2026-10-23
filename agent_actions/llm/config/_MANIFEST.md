# Config Manifest

## Overview

Vendor configuration helpers used by both batch and online connectors.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `runtime_profiles.py` | Module | `RUNTIME_PROFILES`: one measured row per named OpenAI-compatible runtime (llamafile). `wire_vendor()` maps a profile vendor to the vendor whose formats it speaks. | `llm.providers.openai`, `llm.realtime`, `output.response`, `validation.preflight` |
| `vendor.py` | Module | Defines vendor profiles + defaults (timeouts, engines). | `llm.providers` |
