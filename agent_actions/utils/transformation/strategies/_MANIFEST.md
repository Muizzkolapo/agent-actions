# Passthrough Strategy Manifest

## Overview

Strategy implementations that the passthrough transformer evaluates in priority
order (precomputed fields, context_scope helpers, default no-op, etc.).

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `base.py` | Module | `IPassthroughTransformStrategy` interface that defines `can_handle`/`transform`. | `typing`, `abc` |
| `IPassthroughTransformStrategy` | Interface | Strategy contract for deciding applicability and performing transformations. | `typing` |
| `context_scope.py` | Module | `ContextScopeStructuredStrategy`, `ContextScopeUnstructuredStrategy`, `NoOpStrategy`, `DefaultStructureStrategy` for context_scope-based passthrough. | `preprocessing`, `prompt.context`, `field_management` |
| `precomputed.py` | Module | `PrecomputedStructuredStrategy` and `PrecomputedUnstructuredStrategy` that merge precomputed passthrough fields before structuring data. | `field_management`, `preprocessing` |
