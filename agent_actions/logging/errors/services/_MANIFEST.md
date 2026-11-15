# Error Services Manifest

## Overview

Services that emit structured error telemetry (context-aware events) for CLI/runner
errors.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `context.py` | Module | Provides helpers that attach contextual metadata to error events. `merge_exception_context` merges the exception chain's context, outer over inner; the caller's context (a command's options) fills only a key the exception leaves unset or `None`, and a caller's `None` is not added. | `logging`, `errors` |
