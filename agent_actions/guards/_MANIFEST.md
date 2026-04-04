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

> How this module interacts with the user's project files.

| Symbol | User File | Interaction | Config Key |
|--------|-----------|-------------|------------|
| `GuardParser.parse()` | `agent_config/{workflow}.yml` | Validates | `actions[].guard.condition` |
| `parse_guard_config()` | `agent_config/{workflow}.yml` | Validates | `actions[].guard` |
| `GuardConfig.from_dict()` | `agent_config/{workflow}.yml` | Reads | `actions[].guard.condition`, `actions[].guard.on_false` |
| `GuardBehavior` | `agent_config/{workflow}.yml` | Validates | `actions[].guard.on_false` |
| `GuardParser._validate_sql_expression()` | `agent_config/{workflow}.yml` | Validates | `actions[].guard.condition` (SQL expressions) |
| `GuardParser._validate_udf_expression()` | `tools/{workflow}/*.py` | Validates | `actions[].guard.condition` (UDF references via `udf:module.function`) |

**Internal only**: `GuardExpression.__init__()`, `GuardConfig.__repr__()` — no direct project surface.

**Examples** — see this module in action:
- [`examples/incident_triage/.../incident_triage.yml`](../../examples/incident_triage/agent_workflow/incident_triage/agent_config/incident_triage.yml) — SQL guard on `final_severity` for conditional executive escalation (`guard.condition: 'final_severity == "SEV1" or final_severity == "SEV2"'`, `on_false: "filter"`)
- [`examples/review_analyzer/.../review_analyzer.yml`](../../examples/review_analyzer/agent_workflow/review_analyzer/agent_config/review_analyzer.yml) — numeric threshold guard gating two parallel branches (`guard.condition: 'consensus_score >= 6'`, `on_false: "filter"`)
- [`examples/contract_reviewer/.../contract_reviewer.yml`](../../examples/contract_reviewer/agent_workflow/contract_reviewer/agent_config/contract_reviewer.yml) — string equality guard for risk-level filtering (`guard.condition: 'risk_level == "high"'`, `on_false: "filter"`)
