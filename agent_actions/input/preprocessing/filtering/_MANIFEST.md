# Filtering Manifest

## Sub-Modules

| Sub-Module | Description |
|------------|-------------|
| (none) | All filtering logic resides at this level. |

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `__init__.py` | Module | Module docstring describing the filtering package. | `preprocessing` |
| `evaluator.py` | Module | `GuardEvaluator`, `GuardResult`, and two-phase guard evaluation (early + with-context) with thread-safe global singleton. | `filtering`, `processing`, `workflow` |
| `guard_filter.py` | Module | `GuardFilter`, `FilterResult`, and helper functions that securely evaluate WHERE clauses with timeouts, caching, and metrics. Thread-safe global singleton with double-checked locking. | `filtering`, `processing`, `logging` |
