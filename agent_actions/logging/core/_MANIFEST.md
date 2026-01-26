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
| `events.py` | Module | Event emitter definitions shared by logging pipelines. | `logging`, `events` |
| `manager.py` | Module | Central manager that instantiates configured loggers. | `logging` |
| `protocols.py` | Module | Protocol/type definitions used by logging handlers. | `typing`, `logging` |
