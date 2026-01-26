# Error Services Manifest

## Overview

Services that emit structured error telemetry (context-aware events) for CLI/runner
errors.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `context.py` | Module | Provides helpers that attach contextual metadata to error events. | `logging`, `errors` |
