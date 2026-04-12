# Workflow Parallel Manifest

## Overview

Helpers for parallel action execution, dependency tracking, and action-level
scheduling.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `action_executor.py` | Module | Executes actions concurrently while honoring dependencies. `compute_execution_levels` deepcopies `action_configs` before expanding version dependencies to prevent shared-reference mutation. | `asyncio`, `workflow` |
