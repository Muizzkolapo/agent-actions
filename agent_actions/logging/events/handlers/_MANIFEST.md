# Handlers Manifest

## Overview

Handlers that emit structured run results and telemetry for CLI commands.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `run_results.py` | Module | `RunResultsCollector`: collects workflow execution results and writes `run_results.json` atomically via `tempfile.mkstemp` + `os.replace`. | `tooling.docs`, `logging` |
