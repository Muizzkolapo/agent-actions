# Logging Core Handlers Manifest

## Overview

Handler implementations for routing events to various outputs (console, files,
debug collectors). These handlers process events from the EventManager.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `bridge.py` | Module | Bridges Python's standard logging to the event system. | `logging` |
| `console.py` | Module | Console handler for user-facing structured output using Rich. Drops events marked diagnostic unless built with `show_diagnostics`. | `logging`, `cli` |
| `json_file.py` | Module | JSON file handler for writing structured event logs; drops DEBUG rows past `max_debug_bytes` and records `LogFileCapReachedEvent` once. `rotate_run_logs()` shifts the run logs one slot back at run start. | `logging`, `file_io` |
| `progress.py` | Module | Console handler that groups workflow, step and action events into a live per-step progress stream; everything else falls through to plain console formatting. An action line ends `— N skipped by guard` when its event's `guard_skipped` is above zero. An action with `checks_failed` above zero shows `⚠` (`WARN`) and `N failed their checks` after any guard skips; the workflow line totals `records_failed_checks` and turns `⚠` unless an action failed (`✗`). | `logging`, `cli` |
| `ProgressRenderer` | Class | The run's console handler. Suppresses action-start lines, names each result under its step, and reports failures with the message rather than an index. | - |
