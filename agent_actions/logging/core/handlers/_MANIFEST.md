# Logging Core Handlers Manifest

## Overview

Handler implementations for routing events to various outputs (console, files,
debug collectors). These handlers process events from the EventManager.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `bridge.py` | Module | Bridges Python's standard logging to the event system. | `logging` |
| `console.py` | Module | Console handler for user-facing structured output using Rich. | `logging`, `cli` |
| `context_debug.py` | Module | Handler that aggregates context events for debug display with `--debug-context` flag. | `logging`, `cli`, `debug` |
| `json_file.py` | Module | JSON file handler for writing structured event logs. | `logging`, `file_io` |
