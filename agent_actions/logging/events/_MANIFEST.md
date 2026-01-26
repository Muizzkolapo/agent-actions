# Events Manifest

## Overview

Event-driven logging helpers that surface telemetry events (run results, cache hits)
and provide formatter hooks for the CLI/tracing system.

## Sub-Modules

| Sub-Module | Description |
|------------|-------------|
| [handlers](handlers/_MANIFEST.md) | Console/event handlers used by logging. |

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `formatters.py` | Module | Formatters that render runtime events for CLI output. | `logging`, `cli` |
| `types.py` | Module | Event dataclasses (CacheHit, RunStarted, etc.) used across the system. | `logging` |
