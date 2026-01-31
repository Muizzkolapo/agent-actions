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
| `types.py` | Module | Event dataclasses used across the system. Includes workflow (W), agent (A), batch (B), LLM (L), validation (V), cache (C), template (T), data (D), guard (G), recovery (R), config (F), environment (E), init (I), plugin (P), file I/O (FIO), schema (SO), data validation (DV), data transformation (DT), record processing (RP), batch processing (BP), result collection (RC), and context introspection (CX) events. | `logging` |
