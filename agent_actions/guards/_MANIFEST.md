# Guards

Guard expression parsing and configuration for conditional action execution.

Extracted from `output/response/` to break the `config ↔ output` import cycle.
Only depends on `errors` and `utils.constants` (leaf packages).

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `guard_parser.py` | Module | Guard expression parser for SQL-like and UDF conditions. | `GuardType`, `GuardExpression`, `GuardParser`, `parse_guard` |
| `consolidated_guard.py` | Module | Guard configuration with behavior control (skip, filter, write_to, reprocess). | `GuardBehavior`, `GuardConfig`, `parse_guard_config` |

## Key Symbols

| Module | Symbol | Type | Description |
|--------|--------|------|-------------|
| `guard_parser` | `GuardParser` | Class | Parses guard expression strings into typed `GuardExpression` objects. |
| `guard_parser` | `GuardType` | Enum | Guard types: `SQL`, `UDF`. |
| `consolidated_guard` | `GuardBehavior` | Enum | Behavior on guard failure: `SKIP`, `FILTER`, `WRITE_TO`, `REPROCESS`. |
| `consolidated_guard` | `parse_guard_config` | Function | Parses guard config from string or dict format. |

## Re-export Shims

The original modules under `output/response/` are now re-export shims pointing here:
- `output/response/guard_parser.py` → `guards.guard_parser`
- `output/response/consolidated_guard.py` → `guards.consolidated_guard`
