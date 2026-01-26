# Logging Handlers Manifest

## Overview

Handler helpers that wire logging events (run results, guard warnings) into the
CLI/Docs telemetry streams.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `run_results.py` | Module | Handler that captures workflow run metadata for the docs run tracker and telemetry. | `tooling.docs`, `logging` |
