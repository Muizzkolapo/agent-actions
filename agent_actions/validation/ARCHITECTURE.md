# Validation Module Architecture

This document maps the moving parts of `agent_actions/validation/` -- the module that validates everything from YAML config files to LLM output at runtime.

---

## High-Level Overview

Validation happens in **three phases**, at three different times:

```
Phase 1: CONFIG LOAD                Phase 2: PRE-RUN                Phase 3: PER-RECORD
(when YAML is parsed)               (before first LLM call)         (after each LLM response)

  agent_config/*.yml                 Workflow config (expanded)       LLM output dict
        |                                   |                              |
        v                                   v                              v
  ConfigValidator                   WorkflowStaticAnalyzer          validate_output_against_schema()
  SchemaValidator                   WorkflowResolutionService         - field presence
  PromptValidator                   apply_guard_nullable_           - type checking
  PathValidator                       schema_fixes()                  - schema-echo detection
        |                                   |                              |
        v                                   v                              v
  errors[] / warnings[]             StaticValidationResult          SchemaValidationReport
  (blocks CLI startup)              (blocks workflow run)            (triggers reprompt or reject)
```

Phase 1 catches structural problems (missing keys, bad types, invalid YAML).
Phase 2 catches semantic problems (broken field references, missing API keys, type mismatches across actions).
Phase 3 catches runtime problems (LLM returned wrong fields, wrong types, echoed the schema back).

---

## Phase 1: Config Load Validation

### BaseValidator

All Phase 1 validators inherit from `BaseValidator` (ABC). It provides:

- `_errors` / `_warnings` collection lists
- `_prepare_validation()` -- clears state, fires `ValidationStartEvent`
- `_complete_validation()` -- fires `ValidationCompleteEvent`, returns `not has_errors`
- `add_error()` / `add_warning()` -- appends message and fires event
- Static path helpers: `_ensure_path_exists()`, `_is_file()`, `_is_directory()`

```
BaseValidator (ABC)
  |
  +--> ConfigValidator     Validates agent_config/*.yml structure
  |     - operation dispatch (validate_agent_config_file_meta, validate_agent_entries)
  |     - file uniqueness, agent name uniqueness
  |     - dependency graph: missing deps, circular deps, inactive dep references
  |     - delegates per-entry validation to ActionEntryValidationOrchestrator
  |
  +--> SchemaValidator     Validates schema/*.yml against JSON Schema meta-schema
  |     - uses jsonschema library for meta-validation
  |     - detects suspicious keys (typos in JSON Schema keywords)
  |     - validates $ref references resolve
  |
  +--> PromptValidator     Validates prompt_store/*.md files
  |     - prompt ID extraction (delegates to PromptLoader.get_all_prompt_names)
  |     - duplicate ID detection (within-file = error, cross-file = warning)
  |     - unclosed {prompt_id}...{end_prompt} blocks
  |     - file size limits (PromptDefaults.MAX_PROMPT_SIZE_BYTES)
  |     - workflow-scoped: only validates {workflow_name}.md when config provided
  |
  +--> PathValidator       Validates file/directory paths
        - existence, readability, writability, executability
        - configurable via PathValidationOptions dataclass
```

### ActionEntryValidationOrchestrator

`ConfigValidator` delegates per-action-entry validation to this orchestrator, which runs a **chain of 8 specialized validators** in order:

```
ActionEntryValidationOrchestrator
  |
  |  For each action entry dict:
  |
  1. ActionEntryStructureValidator    Must be a dict (critical failure stops chain)
  2. ActionRequiredFieldsValidator    Required keys present (name, prompt, etc.)
  3. ActionTypeSpecificValidator      Type-specific rules (tool needs impl, etc.)
  4. VendorCompatibilityValidator     Vendor string valid, features supported
  5. OptionalFieldTypeValidator       Optional fields have correct types
  6. GranularityAndOutputFieldValidator  Granularity + output_field + on_schema_mismatch
  7. InlineSchemaValidator            Complex inline schema notation (array[object:...])
  8. UnknownKeysDetector              Typo detection (warnings only)
```

The chain stops early on `is_critical_failure` (e.g., entry is not a dict). Each validator returns an `ActionEntryValidationResult` dataclass with errors, warnings, and the critical flag.

These validators inherit from `BaseActionEntryValidator` (ABC), **not** from `BaseValidator`. The two base classes have incompatible interfaces: `BaseValidator.validate(data, config)` vs `BaseActionEntryValidator.validate(context) -> ActionEntryValidationResult`.

---

## Phase 2: Pre-Run Static Analysis

### WorkflowStaticAnalyzer

The core of Phase 2. Builds a `DataFlowGraph` from the expanded workflow config and runs compile-time type checking analogous to TypeScript's type system.

```
WorkflowStaticAnalyzer.analyze()
  |
  Step 0:  Validate context_scope structure (BEFORE normalization)
  Step 0b: Normalize context_scope (null -> {}, ensures downstream sees dicts)
  |
  |  Guard warnings computed BEFORE wildcard expansion
  |  (expansion turns wildcards into specific refs, causing false positives)
  |
  Step 1:  Build DataFlowGraph
  |          - source node (always present, represents input data)
  |          - one DataFlowNode per action
  |          - edges built from InputRequirements
  |
  Step 2:  Expand wildcards (namespace.* -> concrete fields)
  |          - modifies context_scope in the workflow config IN PLACE
  |          - unknown namespaces -> error
  |          - dynamic/schemaless schemas -> left as *
  |
  Step 3:  StaticTypeChecker.check_all()
  |          - referenced actions exist
  |          - referenced actions are in depends_on
  |          - referenced fields exist in upstream output schema
  |          - fields not dropped from output
  |          - unused dependency warnings
  |
  Step 3+: Additional checks
             - reserved action name validation
             - template namespace coverage
             - context_scope field references
             - seed_data/seed_path/static_data misuse
             - schema structure validation
             - drop directive targeting
             - guard-nullable field detection
             - lineage reachability
             - reprompt UDF references
             - json_mode vs schema mismatch
```

### DataFlowGraph

A directed graph where nodes are actions and edges represent data flow.

```
DataFlowGraph
  nodes: dict[str, DataFlowNode]
  edges: list[DataFlowEdge]

DataFlowNode
  name: str
  agent_kind: ActionKind
  output_schema: OutputSchema    schema_fields, observe_fields, passthrough_fields,
  |                               dropped_fields, available_fields (computed)
  input_schema: InputSchema      required_fields, optional_fields
  input_requirements: list[InputRequirement]   source_agent + field_path + location
  dependencies: set[str]

DataFlowEdge
  source: str (action name)
  target: str (action name)
  fields_used: set[str]
```

Key graph operations:
- `topological_sort()` -- Kahn's algorithm, raises on cycles
- `get_reachable_upstream_names()` -- transitive closure of dependencies
- `is_special_namespace()` -- checks against SPECIAL_NAMESPACES (source, loop, etc.)

### WorkflowResolutionService

Performs resource resolution checks that require I/O (env vars, filesystem, network):

```
WorkflowResolutionService.resolve_all()
  |
  1. API key checks
  |    - resolves env var name from vendor config class (single source of truth)
  |    - skips _NO_KEY_SENTINELS ("NO_KEY_REQUIRED" for tool, hitl)
  |    - supports custom $ENV_VAR and literal key syntax
  |    - optional --verify-keys: probes vendor endpoints
  |    - AA_SKIP_ENV_VALIDATION=1 skips key checks ONLY (not seed/vendor checks)
  |
  2. Seed file checks
  |    - $file: reference existence and path security (resolve_seed_path)
  |    - loads JSON content, validates seed field references in templates
  |    - namespace mismatch = error, nested field mismatch = warning
  |
  3. Vendor run-mode compatibility
       - batch mode requires vendor support (e.g., Cohere has no batch)
       - capabilities read from client class CAPABILITIES attribute
```

### Guard Condition Validation

Guard conditions are validated in the static analyzer through several checks:

- `_check_guard_nullable_fields()` -- detects fields that may be None at runtime due to upstream guard filtering, warns when downstream tool schemas reject null
- `_check_guard_skipped_observe_refs()` -- warns when observe refs target specific fields from skip-guarded actions (the entire namespace is None)
- `_check_filter_fanin_observe_hazard()` -- warns about guard-filter + fan-in observe combinations

These checks run **before** wildcard expansion to avoid false positives from expanded wildcards.

### apply_guard_nullable_schema_fixes()

A module-level function (not a method on the analyzer) that **mutates `json_output_schema` dicts in place**. Called after schema compilation and static validation but before workflow execution:

```
apply_guard_nullable_schema_fixes(action_configs)
  |
  1. Find guarded actions with filter/skip behavior
  2. For each downstream action that observes guarded fields:
     - If the field's schema type rejects null (e.g., "string")
     - Mutate the type to ["string", "null"] or add null to anyOf
  3. Return list of fixed field paths (e.g., ["consumer.field"])
```

This mutation is necessary because guarded actions produce None for filtered records, but JSON Schema would reject null by default.

---

## Phase 3: Per-Record Output Validation

### validate_output_against_schema()

Called after each LLM response to check compliance. Handles **5 schema formats**:

```
_extract_schema_fields(schema) handles:

1. "fields" format     fields: [{id: "title", type: "string", required: true}]
2. "properties" format properties: {title: {type: "string"}}  (standard JSON Schema)
3. "schema" wrapper    schema: {properties: {...}}  (OpenAI compiled format)
4. Array schema        type: "array", items: {type: "object", properties: {...}}
5. Inline schema       {optimal_code: "string", score: "number"}  (key=fieldname, value=type)
```

The validation pipeline:

```
LLM output dict
      |
      v
_check_properties_type()     Structural check: properties must be dict
      |
      v
_extract_schema_fields()     -> (all_fields, required_fields, field_types)
_extract_output_fields()     -> actual_fields (set of keys)
      |
      v
Field comparison:
  missing_required = required - actual
  missing_optional = (all - required) - actual
  extra_fields = actual - all
      |
      v
_check_field_types()         Python isinstance checks per field
  type_map: string->str, number->(int,float), boolean->bool, etc.
  Special: bool is subclass of int, so booleans rejected for integer/number
  None values always pass (optional fields)
      |
      v
Schema-echo detection:
  If schema declares fields but output has NONE of them,
  and the output keys are all JSON Schema meta-keys (type, properties, etc.)
  -> "Schema-echo detected" error
      |
      v
_deep_validation_errors()    jsonschema-backed constraint checks
  Per-element validation of array fields against their items sub-schema
  (errors name the element index), additionalProperties: false at top
  level and inside elements, minimum/maximum, enum. Appends to
  validation_errors and flips is_compliant; None field values tolerated.
      |
      v
Namespace hint:
  If missing_required AND extra_fields are dicts
  -> suggests UDF is passing namespaced input without unwrapping
      |
      v
SchemaValidationReport
  is_compliant: bool
  (all field analysis + type_errors + validation_errors)
```

### on_schema_mismatch modes

Configured in `reprompt.on_schema_mismatch` in action config:

| Mode | Behavior |
|------|----------|
| `reject` | Raises `SchemaValidationError` immediately |
| `reprompt` | Sends corrective feedback to LLM, retries |
| `warn` | Logs warning, passes output through unchanged |
| (not set) | Schema validation skipped entirely |

`validate_and_raise_if_invalid()` is the convenience wrapper that calls `validate_output_against_schema()` and raises `SchemaValidationError` on failure (used by the reject path).

---

## File Index

### Core validators (Phase 1)
| File | Role |
|------|------|
| `base_validator.py` | ABC for Phase 1 validators, error/warning collection, event firing |
| `config_validator.py` | Agent config YAML validation, dependency graph checks |
| `schema_validator.py` | JSON Schema meta-schema validation, suspicious key detection |
| `prompt_validator.py` | Prompt file validation (IDs, blocks, size, duplicates) |
| `path_validator.py` | File/directory path validation with configurable options |
| `project_validator.py` | Project name and directory validation |
| `prompt_ast.py` | Jinja2 AST parsing for template variable extraction |

### Action entry validators (Phase 1, orchestrated)
| File | Role |
|------|------|
| `orchestration/action_entry_validation_orchestrator.py` | Chain runner for 8 action validators |
| `action_validators/base_action_validator.py` | ABC for action validators (separate from BaseValidator) |
| `action_validators/action_entry_structure_validator.py` | Checks entry is a dict (critical gate) |
| `action_validators/action_required_fields_validator.py` | Required keys: name, prompt, etc. |
| `action_validators/action_type_specific_validator.py` | Type-specific rules (tool needs impl) |
| `action_validators/vendor_compatibility_validator.py` | Vendor string valid, features supported |
| `action_validators/optional_field_type_validator.py` | Optional field type correctness |
| `action_validators/granularity_output_field_validator.py` | Granularity + output_field + on_schema_mismatch |
| `action_validators/inline_schema_validator.py` | array[object:...] notation validation |
| `action_validators/unknown_keys_detector.py` | Typo detection via edit distance (warnings) |

### Static analyzer (Phase 2)
| File | Role |
|------|------|
| `static_analyzer/workflow_static_analyzer.py` | Main orchestrator, all Phase 2 checks, wildcard expansion, guard analysis |
| `static_analyzer/data_flow_graph.py` | DataFlowGraph, DataFlowNode, OutputSchema, InputSchema |
| `static_analyzer/type_checker.py` | StaticTypeChecker: field reference validation against schemas |
| `static_analyzer/reference_extractor.py` | Extracts field references from prompts, guards, context_scope |
| `static_analyzer/schema_extractor.py` | Extracts output schemas from action configs and tool UDFs |
| `static_analyzer/schema_structure_validator.py` | Pre-flight schema structure checks |
| `static_analyzer/field_flow_analyzer.py` | Field-level data flow analysis |
| `static_analyzer/conflict_detector.py` | Detects field naming conflicts |
| `static_analyzer/errors.py` | StaticTypeError, StaticTypeWarning, StaticValidationResult, FieldLocation |

### Preflight (Phase 2, resource resolution)
| File | Role |
|------|------|
| `preflight/resolution_service.py` | WorkflowResolutionService: API keys, seed files, vendor compat |
| `preflight/vendor_compatibility_validator.py` | VALID_VENDORS from CLIENT_REGISTRY, capability checks |
| `preflight/key_verifier.py` | Optional API key probing (--verify-keys) |
| `preflight/path_validator.py` | Preflight path validation |
| `preflight/error_formatter.py` | Human-readable preflight error formatting |

### Output validation (Phase 3)
| File | Role |
|------|------|
| `schema_output_validator.py` | validate_output_against_schema(), SchemaValidationReport |

### CLI command validators
| File | Role |
|------|------|
| `batch_validator.py` | BatchCommandArgs pydantic model |
| `clean_validator.py` | CleanCommandArgs pydantic model |
| `init_validator.py` | InitCommandArgs pydantic model |
| `run_validator.py` | RunCommandArgs and pre-flight gating |
| `status_validator.py` | StatusCommandArgs pydantic model |
| `retry_validator.py` | Retry command validation |

### Utilities
| File | Role |
|------|------|
| `utils/action_config_validation_utilities.py` | Key normalization, context formatting |
| `utils/schema_type_validator.py` | Schema type string validation helpers |
| `validate_udfs.py` | UDF reference existence validation |

---

## Caveats

1. **Two incompatible base classes.** `BaseValidator` (Phase 1, `validate(data, config) -> bool`) and `BaseActionEntryValidator` (orchestrated chain, `validate(context) -> ActionEntryValidationResult`) have completely different interfaces. The action entry validators do NOT inherit from `BaseValidator`. Mixing them up will cause type errors at runtime.

2. **apply_guard_nullable_schema_fixes() mutates in place.** It modifies the `json_output_schema` dicts inside `action_configs` directly. The caller must ensure this runs after schema compilation and before execution. The mutation is not reversible -- the original schema types are overwritten.

3. **"fields" format bypasses required-field validation.** When the schema uses the `fields` array format (format 1 above), `_extract_schema_fields` checks per-field `required` annotations. But when `required` is omitted from both the field dict and the top-level `required` array, the field is treated as optional. The inline schema format (format 5) has no concept of required fields at all.

4. **Wildcard expansion modifies the workflow config.** `_expand_wildcards()` replaces `namespace.*` with concrete field lists in `context_scope` of the workflow config dict. This is a shallow copy of the context_scope dict, but the replacement happens on the config that all downstream checks see. Any code reading the original wildcards after analysis will see expanded values.

5. **Guard warnings run before wildcard expansion.** `_check_guard_skipped_observe_refs()` and `_check_filter_fanin_observe_hazard()` are computed before `_expand_wildcards()` because expansion turns safe wildcards into specific refs, producing false positives. If you reorder the analyze() steps, these checks will produce incorrect results.

6. **AA_SKIP_ENV_VALIDATION only skips API key checks.** Setting `AA_SKIP_ENV_VALIDATION=1` skips the `_check_api_keys()` call in `WorkflowResolutionService.resolve_all()`, but seed file checks and vendor run-mode compatibility checks still run.

7. **VALID_VENDORS is derived from CLIENT_REGISTRY at import time.** `preflight/vendor_compatibility_validator.py` imports `CLIENT_REGISTRY` from `llm.realtime.services.invocation` and builds `VALID_VENDORS = set(CLIENT_REGISTRY.keys())`. If a new vendor is added to the registry, it is automatically valid. But vendor capabilities are resolved lazily from each client class's `CAPABILITIES` attribute, so adding a registry entry without a `CAPABILITIES` dict will cause `_resolve_capabilities()` to return None (silently skipping capability checks).

8. **Schema-echo detection uses a frozen set of JSON Schema keywords.** `schema_output_validator.py` imports `JSON_SCHEMA_RESERVED_KEYWORDS` from `SchemaValidator` and uses it to detect when the LLM echoed the schema definition. If the LLM returns a mix of schema keywords and real data, the check may not trigger -- it only fires when ALL actual fields are meta-keys and NONE of the declared fields are present.

9. **ConfigValidator dispatches on an "operation" key.** Unlike the other validators that take direct data, `ConfigValidator.validate()` expects `data["operation"]` to be one of `"validate_agent_config_file_meta"` or `"validate_agent_entries"`. Passing raw config data without an operation key will produce an error, not a validation.

10. **PromptValidator validates differently with/without workflow_name.** When `config["workflow_name"]` is provided, only `{workflow_name}.md` is validated. Without it, every `.md` file in the prompt directory is scanned. Cross-file duplicate prompt IDs are warnings (not errors) because the runtime loads prompts per-workflow.

11. **ActionEntryValidationOrchestrator stops on critical failure.** If `ActionEntryStructureValidator` returns `is_critical_failure=True` (entry is not a dict), the remaining 7 validators never run. This means you will only see structural errors, not semantic ones, until the structure is fixed.

12. **WorkflowResolutionService resolves API key env var names from vendor config Pydantic models.** It reads `model_fields["api_key_env_name"].default` from the vendor's config class. If a vendor config class changes its default env var name, the resolution service picks it up automatically -- there is no separate mapping to maintain.

13. **Type checking rejects booleans for integer/number.** `_check_field_types()` explicitly rejects `bool` values when the expected type is `integer` or `number`, even though Python's `isinstance(True, int)` returns True. This is intentional: JSON Schema treats boolean and integer as distinct types.
