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

## Project Surface

| Symbol | File | Interaction | Config Key |
|--------|------|-------------|------------|
| `GuardParser.parse()` | `agent_config/{workflow}.yml` | Validates | `actions[].guard.condition` |
| `parse_guard_config()` | `agent_config/{workflow}.yml` | Reads | `actions[].guard` |
| `GuardConfig.from_dict()` | `agent_config/{workflow}.yml` | Reads | `actions[].guard.condition`, `actions[].guard.on_false` |
| `GuardConfig.from_string()` | `agent_config/{workflow}.yml` | Reads | `actions[].guard` |

**Internal only**: `GuardType`, `GuardExpression`, `GuardBehavior`, `GuardConfig.is_udf_condition()`, `GuardConfig.is_sql_condition()`, `GuardConfig.get_condition_expression()` — no direct project surface.

## Dependencies

| Package | Direction | Why |
|---------|-----------|-----|
| `errors` | outbound | Uses ValidationError and ConfigValidationError for parse/config failures |
| `utils` | outbound | Reads DANGEROUS_PATTERNS constants for expression safety checks |
| `config` | inbound | Config schema imports GuardParser and parse_guard_config for guard expansion |
| `output` | inbound | Response expander imports GuardBehavior, GuardParser, parse_guard_config for guard evaluation |
