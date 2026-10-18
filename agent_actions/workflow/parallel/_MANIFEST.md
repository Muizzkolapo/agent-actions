# Workflow Parallel Manifest

## Overview

Helpers for parallel action execution, dependency tracking, and action-level
scheduling.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `action_executor.py` | Module | Executes actions concurrently while honoring dependencies. `compute_execution_levels` and `upstream_actions` read the same `dependencies`, a version base expanded to its versions, without writing the expansion back to `action_configs`. `upstream_actions(levels)` gives each action its ancestors through `dependencies` in the order the levels run them, which the coordinator stores as `dependency_graph`: not every action of an earlier level, since one beside an action or under another start node never reaches its records. Step boundaries are fired as events, not printed. Each action runs inside `EventManager.context(action_name=..., action_index=...)`, entered within its own gather task, so every event it fires, from `asyncio.to_thread` workers too, names it while the step's other actions run; nothing sets the action with the shared `set_context`. An action's failed result is logged and left to the circuit breaker; an exception that escaped an action's run (a store error setting it running or counting its rows) is re-raised by `_end_level_on` once the step's other actions finish, an interrupt before an error, so it ends the run as it does in sequential mode. `in_flight` holds the actions of the level last started, narrowed to the actions that raised when a step ends on one, which the coordinator names as the failed action when a parallel run dies. | `asyncio`, `workflow` |
