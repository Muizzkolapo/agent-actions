# Models Module Architecture

The `agent_actions/models/` module is a small data-definition package: one source file, four exported symbols. It defines the domain types that describe workflow actions and their fields, consumed by the CLI, workflow engine, and docs generator.

---

## Overview

```
agent_actions/models/
├── __init__.py          ← re-exports all 4 symbols
└── action_schema.py     ← defines FieldSource, FieldInfo, ActionSchema;
                            re-exports ActionKind from config.schema
```

Four symbols, three roles:

| Symbol | Type | Defined in | Role |
|--------|------|-----------|------|
| `ActionKind` | `str, Enum` | `config/schema.py` | Action type discriminator (llm, tool, hitl, source, seed) |
| `FieldSource` | `Enum` | `models/action_schema.py` | How a field is produced (schema, observe, passthrough, tool_output) |
| `FieldInfo` | `@dataclass` | `models/action_schema.py` | Metadata for a single field (name, source, type, required, dropped) |
| `ActionSchema` | `@dataclass` | `models/action_schema.py` | Full schema for one action: inputs, outputs, dependencies, flags |

---

## Data Models

### ActionKind (re-export from config/schema.py)

```python
class ActionKind(str, Enum):
    LLM = "llm"
    TOOL = "tool"
    HITL = "hitl"
    SOURCE = "source"
    SEED = "seed"

    @classmethod
    def _missing_(cls, value):  # case-insensitive lookup
```

A `str` enum so it serializes naturally to JSON. The `_missing_` override allows `ActionKind("LLM")` to resolve to `ActionKind.LLM`.

### FieldSource

```python
class FieldSource(Enum):
    SCHEMA = "schema"          # defined in the output schema YAML
    OBSERVE = "observe"        # read-only context injected into the prompt
    PASSTHROUGH = "passthrough" # copied from input to output unchanged
    TOOL_OUTPUT = "tool_output" # produced by a tool/UDF function
```

This is a plain `Enum`, not `str, Enum`. Comparisons like `source == "schema"` will fail -- use `source == FieldSource.SCHEMA` or compare against `.value`.

### FieldInfo

```python
@dataclass
class FieldInfo:
    name: str
    source: FieldSource
    is_required: bool = True
    is_dropped: bool = False
    field_type: str = "unknown"
    description: str = ""
```

`to_dict()` serializes the field for JSON output. The key mapping is:

```
field_type  (attribute name)  -->  "type"  (dict key in to_dict output)
```

This is deliberate: the attribute is named `field_type` to avoid shadowing Python's `type` builtin, but the serialized form uses `"type"` because that is what consumers (CLI, docs) expect.

### ActionSchema

```python
@dataclass
class ActionSchema:
    name: str
    kind: ActionKind
    input_fields: list[FieldInfo]
    output_fields: list[FieldInfo]
    dependencies: list[str]
    is_dynamic: bool = False
    is_schemaless: bool = False
    is_template_based: bool = False
```

**Computed properties:**

| Property | Returns | Logic |
|----------|---------|-------|
| `available_outputs` | `list[str]` | `output_fields` where `is_dropped == False`, sorted |
| `dropped_outputs` | `list[str]` | `output_fields` where `is_dropped == True`, sorted |
| `required_inputs` | `list[str]` | `input_fields` where `is_required == True`, sorted |
| `optional_inputs` | `list[str]` | `input_fields` where `is_required == False`, sorted |

`to_dict()` includes both the raw field lists and the computed properties, so downstream consumers get both views without re-filtering.

---

## How Models Fit in the Pipeline

```
                    BUILDER                      CONSUMERS
                       │                             │
     ┌─────────────────┼───────────┐     ┌───────────┼───────────┐
     │                 │           │     │           │           │
config/schema.py   workflow/      │     cli/        cli/       tooling/docs/
 (ActionKind)    schema_service.py│  inspect_base  renderers/  generator.py
                       │           │     .py        schema_     (catalog
                       │           │                renderer    output)
                       ▼           │                .py
                 ActionSchema      │
                 instances         │
                                   │
                          models/action_schema.py
                          (type definitions)
```

**Builder:** `WorkflowSchemaService` (in `workflow/schema_service.py`) is the sole factory. It reads action configs + YAML schema files + UDF registries, constructs `FieldInfo` objects, and assembles `ActionSchema` instances. No other code creates these objects in production.

**Display:** CLI commands (`inspect`, `schema`) receive `ActionSchema` from the service and render it via `schema_renderer.py`. The renderer reads `kind`, `available_outputs`, `dropped_outputs`, and the field lists.

**Catalog:** The docs generator (`tooling/docs/generator.py`) iterates `ActionSchema.to_dict()` to produce documentation pages.

---

## Import Map

Where each symbol is used in production code:

| Symbol | Imported by |
|--------|-------------|
| `ActionKind` | `workflow/schema_service.py`, `cli/renderers/schema_renderer.py` |
| `FieldSource` | `workflow/schema_service.py`, `cli/renderers/schema_renderer.py`, `tooling/docs/generator.py` |
| `FieldInfo` | `workflow/schema_service.py`, `tooling/docs/generator.py` |
| `ActionSchema` | `workflow/schema_service.py`, `cli/inspect_base.py`, `cli/renderers/schema_renderer.py`, `tooling/docs/generator.py` |

Test files that exercise the models directly:

- `tests/unit/models/test_action_schema.py`
- `tests/services/test_workflow_schema_service.py`
- `tests/cli/renderers/test_schema_renderer.py`
- `tests/cli/test_inspect_commands_integration.py`
- `tests/cli/test_cli_hardening.py`

---

## File Index

| File | Role |
|------|------|
| `__init__.py` | Re-exports `ActionKind`, `ActionSchema`, `FieldInfo`, `FieldSource` |
| `action_schema.py` | Defines `FieldSource`, `FieldInfo`, `ActionSchema`; re-exports `ActionKind` from `config.schema` |

---

## Caveats

**ActionKind lives in `config/`, not `models/`.** It is defined in `config/schema.py` and re-exported here for convenience. The canonical definition is in `config/` because it is used in Pydantic config validation before `models/` is involved. Do not duplicate it.

**FieldSource is NOT a `str` enum.** Unlike `ActionKind(str, Enum)`, `FieldSource` is a plain `Enum`. String comparisons like `field.source == "schema"` will silently evaluate to `False`. Always compare against the enum member or use `.value`.

**`output_fields` includes dropped fields.** The `output_fields` list contains all fields regardless of drop status. Use `available_outputs` for the filtered list. This means `len(output_fields)` is not the same as the number of fields a downstream action can see.

**Deduplication is the caller's responsibility.** If the same field name appears in both schema and passthrough sources, `output_fields` will contain both `FieldInfo` entries. `available_outputs` (which returns only names) will deduplicate via `sorted()` on a set-like comprehension, but the underlying list does not. Callers iterating `output_fields` directly must handle duplicates.

**Rename impact table.** Because these types are imported across many modules, renaming any symbol requires updating all importers:

| Symbol | Import sites (production + tests) |
|--------|-----------------------------------|
| `ActionKind` | 6 files |
| `ActionSchema` | 8 files |
| `FieldInfo` | 5 files |
| `FieldSource` | 6 files |
