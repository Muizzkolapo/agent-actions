# Guards

**[> Architecture deep-dive (ARCHITECTURE.md)](ARCHITECTURE.md)**

Guard expression parsing and configuration for conditional action execution.

Extracted from `output/response/` to break the `config ↔ output` import cycle.
Only depends on `errors` and `utils.constants` (leaf packages).

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `guard_parser.py` | Module | Guard expression parser for SQL-like and UDF conditions. | `GuardType`, `GuardExpression`, `GuardParser`, `parse_guard` |
| `consolidated_guard.py` | Module | Guard configuration with behavior control (skip, filter, warn). | `GuardBehavior`, `GuardConfig`, `parse_guard_config`, `_UNSUPPORTED_GUARD_BEHAVIORS` |
| `bare_reference.py` | Module | Whether a bare (un-dotted) guard name provably resolves against nothing: no record, version, namespace or `output_field` promotion answers it and no upstream spreads its output flat. A first action names no upstream and its record holds the staged row under `source`, so a bare staged column there is unresolvable (1535). Shared by pre-flight's guard validation. | `bare_reference_is_unresolvable`, `spreads_output_flat`, `PROMOTED_RECORD_FIELDS`, `PROMOTED_VERSION_KEYS` |

## Key Symbols

| Module | Symbol | Type | Description |
|--------|--------|------|-------------|
| `guard_parser` | `GuardParser` | Class | Parses guard expression strings into typed `GuardExpression` objects. |
| `guard_parser` | `GuardType` | Enum | Guard types: `SQL`, `UDF`. |
| `consolidated_guard` | `GuardBehavior` | Enum | Behavior on guard failure: `SKIP`, `FILTER`, `WARN`. Unsupported values (`write_to`, `reprocess`) are in `_UNSUPPORTED_GUARD_BEHAVIORS`. |
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
| `record` | outbound | `bare_reference` reads `RECORD_FRAMEWORK_FIELDS` for the record keys a guard reads bare |
| `validation` | inbound | Pre-flight guard validation asks `bare_reference` whether a bare name resolves |
| `config` | inbound | Config schema imports GuardParser and parse_guard_config for guard expansion |
| `output` | inbound | Response expander imports GuardBehavior, GuardParser, parse_guard_config for guard evaluation |
