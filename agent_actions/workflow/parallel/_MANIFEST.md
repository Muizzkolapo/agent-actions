# Workflow Parallel Manifest

## Overview

Helpers for parallel action execution, dependency tracking, and action-level
scheduling.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `action_executor.py` | Module | Executes actions concurrently while honoring dependencies. `compute_execution_levels` and `upstream_actions` read the same `dependencies`, a version base expanded to its versions, without writing the expansion back to `action_configs`. `upstream_actions(levels)` gives each action its ancestors through `dependencies` in the order the levels run them, which the coordinator stores as `dependency_graph`: not every action of an earlier level, since one beside an action or under another start node never reaches its records. Step boundaries are fired as events, not printed. | `asyncio`, `workflow` |
