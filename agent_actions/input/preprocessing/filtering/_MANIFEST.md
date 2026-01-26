# Filtering Manifest

## Sub-Modules

| Sub-Module | Description |
|------------|-------------|
| (none) | All filtering logic resides at this level. |

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `__init__.py` | Module | Module docstring describing the filtering package. | `preprocessing` |
| `guard_filter.py` | Module | `GuardFilter`, `FilterResult`, and helper functions that securely evaluate WHERE clauses with timeouts, caching, and metrics. | `filtering`, `processing`, `logging` |
| `guard_handler.py` | Module | `GuardHandler`, `GuardConfig`, and helpers that unify batch/online filtering, context tracking, and passthrough item construction. | `filtering`, `processing`, `services` |
| `service.py` | Module | `FilterService` plus `FilterStatus` helpers that centralize guard/conditional clause evaluation and expose a singleton. | `filtering`, `workflow`, `services` |
