# Logging Core Manifest

## Overview

Core logging utilities that manage event protocols, logger managers, and handler
registrations consumed by both CLI commands and runtime services.

## Sub-Modules

| Sub-Module | Description |
|------------|-------------|
| [handlers](handlers/_MANIFEST.md) | Handler implementations for run results and telemetry. |

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `_compat.py` | Module | Optional dependency compatibility helpers (Rich availability check). | `logging` |
| `events.py` | Module | Event emitter definitions shared by logging pipelines. | `logging`, `events` |
| `manager.py` | Module | `EventManager` singleton: injects the global context (`set_context`) and the per-task overlay (`context()`, a `ContextVar`) into each event's `meta`, then dispatches to handlers. An event whose `data["action_name"]` is `""`, as the provider LLM events are fired, takes the overlay's `action_name`. Per-action labels belong in the overlay only: actions of one step run at once and share the global context. | `logging` |
| `protocols.py` | Module | Protocol/type definitions used by logging handlers. | `typing`, `logging` |
