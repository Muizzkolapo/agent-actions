# Passthrough Strategy Manifest

## Overview

Strategy implementations that the passthrough transformer evaluates in priority
order (precomputed fields, context_scope helpers, default no-op, etc.).

All strategies return flat action output dicts (just the fields belonging to the
action's namespace).  `PassthroughTransformer` handles namespace wrapping and
upstream preservation via `RecordEnvelope.build()`.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `base.py` | Module | `IPassthroughTransformStrategy` interface that defines `can_handle`/`transform`. | `typing`, `abc` |
| `IPassthroughTransformStrategy` | Interface | Strategy contract for deciding applicability and performing transformations. | `typing` |
| `context_scope.py` | Module | `ContextScopeStructuredStrategy`, `ContextScopeUnstructuredStrategy`, `NoOpStrategy`, `DefaultStructureStrategy` — return flat action output dicts. | `preprocessing`, `prompt.context` |
| `precomputed.py` | Module | `PrecomputedStructuredStrategy` and `PrecomputedUnstructuredStrategy` — merge precomputed passthrough fields, return flat action output dicts. | — |
