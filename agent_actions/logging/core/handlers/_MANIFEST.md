# Logging Core Handlers Manifest

## Overview

Handler implementations for routing events to various outputs (console, files,
debug collectors). These handlers process events from the EventManager.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `bridge.py` | Module | Bridges Python's standard logging to the event system. | `logging` |
| `console.py` | Module | Console handler for user-facing structured output using Rich. Drops events marked diagnostic unless built with `show_diagnostics`. | `logging`, `cli` |
| `json_file.py` | Module | JSON file handler for writing structured event logs. | `logging`, `file_io` |
| `progress.py` | Module | Console handler that groups workflow, step and action events into a live per-step progress stream; everything else falls through to plain console formatting. | `logging`, `cli` |
| `ProgressRenderer` | Class | The run's console handler. Suppresses action-start lines, names each result under its step, and reports failures with the message rather than an index. | - |
