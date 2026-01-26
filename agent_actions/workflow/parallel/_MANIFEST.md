# Workflow Parallel Manifest

## Overview

Helpers for parallel action execution, dependency tracking, and action-level
scheduling.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `action_executor.py` | Module | Executes actions concurrently while honoring dependencies. | `asyncio`, `workflow` |
| `dependency.py` | Module | Computes dependencies between parallel actions for scheduling. | `workflow`, `validation` |
