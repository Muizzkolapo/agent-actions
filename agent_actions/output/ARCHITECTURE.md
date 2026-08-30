# Output Module Architecture

This document maps the moving parts of `agent_actions/output/` -- the module that handles file I/O, schema compilation, config expansion, and response handling for the entire framework.

---

## High-Level Overview

```
                       agent_actions/output/
                            │
              ┌─────────────┼──────────────┐
              │             │              │
          writer.py     saver.py      response/
        (file I/O)    (source data)   (schema + config + expansion)
              │             │              │
              │             │    ┌─────────┼──────────┐──────────┐
              │             │    │         │          │          │
              │             │  schema   expander   config    response
              │             │  pipeline  pipeline   models    builder
              │             │    │         │          │          │
              ▼             ▼    ▼         ▼          ▼          ▼
         StorageBackend   StorageBackend  LLM      workflow   provider
         (sqlite/tinydb)  (sqlite/tinydb) vendors  engine     clients
```

The module has **three responsibilities**:

| Component | What it does |
|-----------|-------------|
| `writer.py` + `saver.py` | File writing pipeline -- atomic JSON writes, storage backend delegation, staging/target/source output |
| `response/schema.py` + submodules | Schema compilation pipeline -- loads YAML/JSON schemas, compiles to vendor-specific formats, resolves dispatch_task calls |
| `response/expander.py` + submodules | Config expansion pipeline -- transforms action-based YAML configs into fully resolved agent configurations |

---

## File Writing Pipeline

FileWriter handles all disk I/O with atomic writes and optional database persistence.

```
┌─────────────────────────────────────────────────────────┐
│                     FileWriter                           │
│                                                          │
│   Constructor:                                           │
│     file_path         → full path to output file         │
│     storage_backend   → optional StorageBackend          │
│     action_name       → node name for backend writes     │
│     output_directory  → base dir for relative paths      │
│                                                          │
│   Three write methods:                                   │
│                                                          │
│   write_staging(data)                                    │
│     ├── .json → atomic_json_write (temp + fsync + rename)│
│     ├── .txt  → plain text (list joins with newlines)    │
│     └── .csv  → csv.DictWriter or csv.writer             │
│     Events: FileWriteStarted → write → FileWriteComplete │
│                                                          │
│   write_target(data)                                     │
│     ├── Requires storage_backend AND action_name         │
│     ├── Computes relative path from output_directory     │
│     ├── assert_path_contained (path traversal guard)     │
│     ├── storage_backend.write_target()  ← authoritative  │
│     └── atomic_json_write()  ← disk materialization      │
│                                                          │
│   write_source(data)                                     │
│     └── atomic_json_write (JSON only)                    │
└─────────────────────────────────────────────────────────┘

UnifiedSourceDataSaver:
  save_source_items(items, relative_path)
    ├── Requires storage_backend (raises ValueError if missing)
    ├── storage_backend.write_source() with optional deduplication
    └── Events: SourceDataSaving → write → SourceDataSaved
```

### Relative path preservation

When `output_directory` is provided, `write_target` computes the relative path from `output_directory` to `file_path`, preserving subdirectory structure in the storage backend. This prevents collisions when multiple files share the same name but live in different subdirectories:

```
file_path:        /project/agent_io/target/agent_1/subdir/file.json
output_directory: /project/agent_io/target/agent_1
stored as:        subdir/file.json   (not just file.json)
```

---

## Schema Compilation Pipeline

How a YAML schema on disk becomes the vendor-specific format sent to the LLM API. The pipeline has **6 stages**, orchestrated by `ResponseSchemaCompiler.compile()`.

```
Stage 1: Load                     Stage 2: Resolve              Stage 3: Inject
                                  dispatch_task()               dispatch_task()
                                  in schema string              in schema fields

schema/{wf}/{action}.yml   ──►  _load_named_schema()    ──►   _inject_functions_into_schema()
  OR                              uses SchemaLoader              recursive walk of all
inline schema: {...}        ──►  _load_inline_schema()          dict/list/string values
  OR                              _resolve_dispatch()            captured_results populated
dispatch_task() call        ──►  context_data_str
                                                          ──►   Stage 4: Unwrap

Stage 4: Unwrap              Stage 5: Compile             Stage 6: Sanitize
                              for vendor

_unwrap_nested_schema()  ──►  compile_unified_schema()  ──►  ensure_json_safe()
  {schema: {fields: [...]}}     routes by vendor               strips non-JSON
  → {fields: [...]}             (see matrix below)             values (NaN, Inf)
```

### Schema input formats

The pipeline accepts three input shapes:

```
1. Unified format (native):
   name: extraction
   fields:
     - id: title
       type: string
     - id: tags
       type: array
       items: {type: string}

2. JSON Schema array format:
   name: facts_list
   type: array
   items:
     type: object
     properties:
       fact: {type: string}
     required: [fact]

   → auto-converted to unified by _convert_json_schema_to_unified()

3. Inline shorthand (dict):
   schema:
     title: string!          ← trailing ! = required
     tags: array[string]
     items: array[object:{'name': 'string', 'price': 'number!'}]

   → converted by SchemaLoader.construct_schema_from_dict()
```

### Vendor-specific compilation

`compile_unified_schema()` transforms the unified format into the dialect each LLM vendor expects:

```
Stage 5 output per vendor:

  OpenAI/Groq/AGAC:
    {"name":"...","schema":{"type":"object","properties":{...},"required":[...],"additionalProperties":false}}

  Anthropic:
    [{"name":"...","description":"...","input_schema":{"type":"object","properties":{...},"required":[...],"additionalProperties":false}}]

  Gemini:
    {"name":"...","schema":{"type":"object","properties":{...},"required":[...]}}

  Ollama Local/Cloud:
    {"title":"...","type":"object","properties":{...},"required":[...],"additionalProperties":false}

  Cohere:
    {"type":"object","properties":{...},"required":[...]}
```

### Vendor compilation comparison matrix

| | OpenAI | Anthropic | Gemini | Groq | Cohere | Ollama |
|---|---|---|---|---|---|---|
| **Wrapper** | `{name, schema}` | `[{name, description, input_schema}]` | `{name, schema}` | Same as OpenAI | Flat `{type, properties}` | Flat `{title, type, properties}` |
| **Return type** | `dict` | `list[dict]` | `dict` | `dict` | `dict` | `dict` |
| **additionalProperties** | `false` | `false` | Omitted | `false` | Omitted | `false` |
| **Name field** | `name` | `name` | `name` | `name` | None | `title` |
| **Field mappings** | Supported | Supported | Supported | Supported | Supported | Supported |

---

## Dispatch Injection System

Schema fields can contain `dispatch_task()` calls that execute Python UDFs at schema-compile time and inject the results into the schema.

```
Schema YAML:
  fields:
    - id: category
      type: string
      enum: "dispatch_task('get_categories', context_data)"

At compile time:
  _inject_functions_into_schema()
    └── recursive walk of every string value
         └── "dispatch_task(" found?
              └── PromptUtils.process_dispatch_in_text()
                   └── runs UDF, returns result
                        └── enum: ["electronics", "clothing", "food"]

captured_results:
  {"get_categories": ["electronics", "clothing", "food"]}
  → merged into LLM response as add_dispatch output
```

Two functions handle dispatch:

| Function | Scope |
|----------|-------|
| `_inject_functions_into_schema()` | Recursive walk of entire schema tree (dicts, lists, strings) |
| `_resolve_dispatch_in_schema()` | Single string value resolution (used for inline schema loading) |

Both delegate to `PromptUtils.process_dispatch_in_text()` with `preserve_type_on_exact_match=True` so that dispatch results retain their native Python type (list, dict) instead of being stringified.

---

## Action Expander Pipeline

`ActionExpander.expand_actions_to_agents()` transforms action-based YAML workflow configs into fully resolved agent configurations. The core logic lives in `_create_agent_from_action()`, which executes 17 steps:

```
┌─────────────────────────────────────────────────────────────┐
│          _create_agent_from_action() — 17 steps              │
│                                                              │
│   1.  inherit_simple_fields()                                │
│       → 30+ fields from action > defaults > hardcoded        │
│                                                              │
│   2.  Force model_vendor = "hitl" for HITL actions           │
│                                                              │
│   3.  Force run_mode = online for tool/hitl actions          │
│       (only if action doesn't explicitly override)           │
│                                                              │
│   4.  validate_vendor_exists()                               │
│       → checks against VendorType enum                       │
│                                                              │
│   5.  validate_required_fields()                             │
│       → model_vendor + model_name + api_key (LLM only)      │
│                                                              │
│   6.  process_schema_config()                                │
│       → compiled schema passthrough OR template replacement  │
│                                                              │
│   7.  process_guard_config()                                 │
│       → string guards → GuardParser.parse()                  │
│       → dict guards → parse_guard_config()                   │
│       → UDF guards → conditional_clause                      │
│       → expression guards → agent["guard"] dict              │
│                                                              │
│   8.  Process prompt (template_replacer)                     │
│                                                              │
│   9.  process_tool_action()                                  │
│       → validates impl field, rejects batch mode             │
│       → requires output schema                               │
│                                                              │
│  10.  process_hitl_action()                                  │
│       → validates hitl config block + instructions           │
│       → applies workflow-level timeout default               │
│       → injects canonical HITL output schema                 │
│                                                              │
│  11.  compile_output_schema()                                │
│       → YAML schema → json_output_schema (JSON Schema)       │
│       → skips if json_output_schema already set (HITL)       │
│                                                              │
│  12.  Process granularity                                    │
│       → HITL defaults to "file", rejects "record"            │
│       → LLM inherits from defaults                           │
│                                                              │
│  13.  deep_merge_context_scope()                             │
│       → action directives merge with defaults (not replace)  │
│                                                              │
│  14.  Initialize dependencies                                │
│                                                              │
│  15.  process_chunk_config()                                 │
│       → chunk_config block OR legacy chunk_size/overlap      │
│                                                              │
│  16.  initialize_optional_fields()                           │
│       → skip_if, add_dispatch, conditional_clause, guard     │
│                                                              │
│  17.  Process version_consumption + interceptors             │
└─────────────────────────────────────────────────────────────┘
```

### Versioned action expansion

Actions with a `versions` block are expanded into multiple agents:

```
versions:
  param: round
  range: [1, 3]

→ Expands to 3 agents: action_1, action_2, action_3
  Each gets:
    is_versioned_agent: true
    version_base_name: original action name
    version_number: 1/2/3
    version_mode: parallel (default)
    _version_context: {i, idx, length, first, last}

  Template variables available:
    ${round}   → current iteration value
    ${round-1} → previous iteration value
```

---

## Three-Level Config Inheritance

Every config field follows the same inheritance chain:

```
┌──────────────────────────────────────────────────┐
│  Priority 1 (highest): Action-level value         │
│    actions:                                        │
│      - name: extract                               │
│        temperature: 0.3    ← wins                  │
├──────────────────────────────────────────────────┤
│  Priority 2: Workflow defaults value               │
│    defaults:                                       │
│        temperature: 0.7                            │
├──────────────────────────────────────────────────┤
│  Priority 3 (lowest): Hardcoded default            │
│    SIMPLE_CONFIG_FIELDS = {                        │
│        "temperature": None,  ← use provider default│
│    }                                               │
└──────────────────────────────────────────────────┘

inherit_simple_fields() applies this for 30+ fields:
  model_vendor, model_name, api_key, run_mode, json_mode,
  temperature, max_tokens, top_p, stop, reprompt, retry,
  granularity, is_operational, prompt_debug, output_field,
  chunk_size, chunk_overlap, record_limit, file_limit, ...

Mutable values (list, dict) are deep-copied to prevent
cross-agent state leakage.
```

`context_scope` is a special case -- it uses `deep_merge_context_scope()` which merges action-level directives **into** defaults (dicts merged, lists deduplicated) rather than replacing them. This lets an action add drop fields while inheriting seed from defaults.

---

## ResponseBuilder

Centralizes response handling that was previously duplicated across every provider client.

```
ResponseBuilder (static methods):

  wrap_non_json(content, agent_config) → list[dict]
    Wraps plain-text LLM output in the configured output_field.
    Used by all provider call_non_json() methods.

  extract_usage(response, provider) → UsageResult
    Dispatches to per-shape extractors based on PROVIDER_RESPONSE_CONFIGS:
      OpenAI/Groq  → response.usage.prompt_tokens / completion_tokens
      Anthropic    → response.usage.input_tokens / output_tokens
      Gemini       → response.usage_metadata.prompt_token_count
      Cohere       → response.usage.tokens.input_tokens
      Ollama       → response.prompt_eval_count / eval_count

  record_usage_and_event(response, provider, model, latency_ms, request_id)
    → extract_usage + set_last_usage (ContextVar) + fire LLMResponseEvent
```

---

## File Index

### File I/O
| File | Role |
|------|------|
| `writer.py` | FileWriter -- atomic writes to staging/target/source with storage backend delegation |
| `saver.py` | UnifiedSourceDataSaver -- source data persistence with deduplication |

### Schema pipeline
| File | Role |
|------|------|
| `response/schema.py` | ResponseSchemaCompiler -- orchestrates the 6-stage compilation pipeline |
| `response/loader.py` | SchemaLoader -- discovers and loads schema files from disk |
| `response/schema_conversion.py` | JSON Schema to unified format conversion, per-field compilation |
| `response/vendor_compilation.py` | compile_unified_schema -- vendor-specific output formatting |
| `response/dispatch_injection.py` | Recursive dispatch_task() resolution in schema trees |
| `response/context_data.py` | Context data preparation, schema loading/unwrapping helpers |

### Config expansion
| File | Role |
|------|------|
| `response/expander.py` | ActionExpander -- orchestrates action-to-agent transformation |
| `response/expander_validation.py` | Vendor, name, and required-field validation |
| `response/expander_schema.py` | Schema processing and compile_output_schema |
| `response/expander_action_types.py` | Guard, tool, and HITL action processing |
| `response/expander_merge.py` | Config merging, context_scope deep merge, chunk config |
| `response/expander_guard_validation.py` | Guard reference validation against upstream actions |

### Config models
| File | Role |
|------|------|
| `response/config_fields.py` | SIMPLE_CONFIG_FIELDS registry, get_default(), inherit_simple_fields() |
| `response/config_schema.py` | Pydantic models: AgentConfig, DefaultAgentConfig, WhereClauseConfig |

### Response handling
| File | Role |
|------|------|
| `response/response_builder.py` | ResponseBuilder -- usage extraction and non-JSON wrapping |

---

## Caveats

1. **Gemini rejects additionalProperties.** The Gemini compilation path deliberately omits `additionalProperties: false` from its schema output. Including it causes the Gemini API to reject the request. All other vendors include it.

2. **Anthropic returns a list.** `compile_unified_schema()` returns `list[dict]` for Anthropic (tools format) but `dict` for every other vendor. Callers that type-check the return value must handle both shapes.

3. **compile_output_schema must run after process_hitl_action.** HITL actions inject a canonical output schema (`HITL_OUTPUT_SCHEMA`). `compile_output_schema` skips when `json_output_schema` is already set, preserving the HITL schema. Reordering these calls would overwrite the HITL schema with a compiled version.

4. **Dispatch failures are non-fatal.** When `dispatch_task()` resolution fails inside a schema field, the unresolved string is passed through to the LLM vendor as-is (with a warning logged). This may cause vendor API errors downstream but does not crash the pipeline.

5. **Schema name collisions fail on reference, not on discovery.** `SchemaLoader.load_schema()` raises `SchemaValidationError` (naming every colliding path) when the requested name matches more than one file. `discover_schema_files()` stays lenient — first occurrence wins, warning logged once per process — because the LSP indexer and docs scanner call it directly and must not crash on a user project state.

6. **write_target requires both storage_backend and action_name.** Calling `write_target()` without both raises `ValueError` at runtime. There is no compile-time check -- the constructor accepts `None` for both parameters because `write_staging()` and `write_source()` do not need them.

7. **captured_results for add_dispatch.** The `captured_results` dict populated during dispatch injection is returned alongside the compiled schema. It carries the output of `dispatch_task()` UDF calls so that the caller (typically `create_dynamic_agent` in the builder) can merge those results into the LLM response. If no dispatch calls exist, it is an empty dict.

8. **Inline schema takes precedence over schema_name.** When an action config has both `schema` (inline) and `schema_name`, the inline schema wins and `schema_name` is ignored. A warning is logged.

9. **Tool actions must declare an output schema.** `process_tool_action()` raises `ConfigValidationError` if neither `json_output_schema` nor `schema` is present. This runs before `compile_output_schema`, which would otherwise silently skip schema-less actions.

10. **HITL granularity must be "file".** HITL actions default to file-level granularity. Explicitly setting `granularity: record` on a HITL action raises `ConfigurationError` with the `HITL_FILE_GRANULARITY_ERROR` constant.

11. **Mutable defaults are deep-copied.** `inherit_simple_fields()` deep-copies any list or dict value before assigning it to the agent dict. Without this, all agents in a versioned expansion would share the same mutable reference, causing cross-agent state leakage.

12. **Array-type schemas produce separate output_schema and json_output_schema.** When the schema is `type: array`, the full unified schema goes to `output_schema` (for LLM providers) while `json_output_schema` gets just the `items` definition (for validation). This is because validation operates on individual items, not the outer array wrapper.

13. **context_scope merges, not replaces.** Unlike all other config fields that follow "action overrides defaults", `context_scope` uses `deep_merge_context_scope()` which merges action-level directives into defaults. Dicts are shallow-merged; lists are concatenated and deduplicated. This lets an action add `drop` fields while inheriting `seed` from defaults.
