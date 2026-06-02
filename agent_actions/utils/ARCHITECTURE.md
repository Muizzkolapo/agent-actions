# Utils Module Architecture

This document maps the moving parts of `agent_actions/utils/` — the shared utility layer that every other module depends on. It is a pure dependency sink: nothing outside `utils/` is imported at module load time, with two narrow exceptions (lazy imports inside function bodies).

---

## High-Level Overview

```
                        agent_actions/utils/
                              │
        ┌─────────┬───────────┼──────────┬──────────────┐
        │         │           │          │              │
   identity &   constants   UDF       JSON &        filesystem
    lineage                registry   safety          & path
        │         │           │          │              │
   id_generation  constants.py  udf_management  json_parsing.py  atomic_write.py
   lineage/       (~57 importers) registry.py   json_safety.py   path_utils.py
   correlation/                module_loader.py                  path_safety.py
   field_management/
```

The module has **no outward imports at load time**. Two files use lazy (in-function) imports to avoid circular dependencies:

| File | Lazy import | Why |
|------|-------------|-----|
| `content.py` | `agent_actions.record.envelope.RecordEnvelope` | Needs `build_content()` and `RECORD_FRAMEWORK_FIELDS` |
| `transformation/strategies/context_scope.py` | `agent_actions.input.preprocessing.transformation.transformer.DataTransformer` | Reuses existing transformation logic |

Everything else imports only from `config` (types, paths), `errors`, and `logging` — all lower-level or peer modules.

---

## Identity & Lineage

Four classes handle identity, lineage, field enforcement, and version correlation.

```
IDGenerator (id_generation/generator.py)
├── generate_target_id()       → UUID4  (unique record identity)
├── generate_node_id(action)   → "{action}_{uuid4}"  (lineage node)
├── generate_source_guid()     → UUID4  (record instance identity)
└── generate_content_hash()    → UUID5  (deterministic content fingerprint)

LineageBuilder (lineage/builder.py)
├── build_lineage(item, node_id)           → append node to chain
├── add_lineage_tracking(obj, item, node)  → node_id + lineage + ancestry
├── add_lineage_tracking_from_sources()    → many-to-one (FILE tools)
├── add_unified_lineage()                  → single entry point for enrichers
├── set_parent_tracking()                  → propagate parent/root target_id
└── filter_node_lineage()                  → strip invalid node IDs

FieldManager (field_management/manager.py)
└── ensure_required_fields(obj, source_guid, action_name)
    → guarantees target_id, source_guid, node_id, lineage exist

VersionIdGenerator (correlation/version_id.py)
├── get_or_create_version_correlation_id()          → GUID-based
├── get_or_create_position_based_version_correlation_id()  → index-based
├── add_version_correlation_id(obj, agent_config)   → main entry point
└── _evict_oldest_if_needed()                       → LRU cap at 10,000
```

`VersionIdGenerator` uses a class-level `OrderedDict` registry with LRU eviction and a reentrant lock. IDs are deterministic: `sha256(session_id:content)[:16]` prefixed with `corr_`.

---

## Constants

`constants.py` is imported by ~57 files across the codebase. It defines:

| Constant | Type | Used by |
|----------|------|---------|
| `RESERVED_AGENT_NAMES` | `frozenset` | Config validators, static analyzers, CLI |
| `DANGEROUS_PATTERNS` | `frozenset` | Guard parser, UDF expression checker |
| `DANGEROUS_PATTERNS_UDF` | `frozenset` | UDF-specific superset (adds `__`) |
| `SPECIAL_NAMESPACES` | `frozenset` | `RESERVED_AGENT_NAMES - {"context_scope"}` |
| `HITL_FILE_GRANULARITY_ERROR` | `str` | HITL config validation |
| `HITL_OUTPUT_SCHEMA` / `HITL_OUTPUT_JSON_SCHEMA` | `dict` | Pre-compiled to avoid circular imports |
| `SCHEMA_SUFFIXES` / `SCHEMA_FILE_GLOBS` | `tuple` | Schema file discovery |
| Config key constants | `str` | `MODEL_VENDOR_KEY`, `PROMPT_KEY`, etc. |

`contains_dangerous_pattern()` uses `\b` word-boundary matching so `"exec"` blocks `exec(` but not `execution_status`. The `"__"` pattern is the sole exception — it uses substring matching.

---

## UDF Registry

```
┌──────────────────────────────────────────────────────┐
│                  UDF_REGISTRY                         │
│          (process-wide dict, guarded by RLock)        │
│                                                       │
│  "my_tool" → {                                        │
│    function: <callable>,                              │
│    module: "agent_actions._udfs.my_tool",             │
│    name: "my_tool",                                   │
│    file: "/path/to/my_tool.py",                       │
│    docstring: "...",                                   │
│    signature: <inspect.Signature>,                     │
│    granularity: Granularity.RECORD | Granularity.FILE  │
│  }                                                    │
└──────────────────────────────────────────────────────┘
         ▲                              │
   @udf_tool decorator            get_udf(name)
   (registration)                 (lookup, case-insensitive)
```

### Registration flow

1. User writes `@udf_tool` in `tools/{workflow}/my_tool.py`
2. `discover_and_load_udfs()` or `discover_and_load_udfs_recursive()` globs for `.py` files
3. `load_module_from_path()` loads via `importlib.util.spec_from_file_location` — **never mutates `sys.path`**
4. Module execution triggers the `@udf_tool` decorator, which registers into `UDF_REGISTRY`
5. Duplicate detection: same file + different import path = silently reuse; different file = `DuplicateFunctionError`

### module_loader.py design

- Uses `importlib.util.spec_from_file_location` + `exec_module` instead of `sys.path` manipulation
- Registers loaded modules under `sys.modules["agent_actions._udfs.{name}"]` so decorators resolve correctly
- Thread-safe via `threading.RLock`
- Module cache keyed by `"{module_name}:{module_path}"`
- If path-based load fails (broken code), `path_load_failed` flag blocks fallback import to prevent silent substitution

### clear_registry()

Cleans both `UDF_REGISTRY` and `sys.modules` entries for all registered module names. Used in tests.

---

## JSON Parsing

### parse_llm_json — 3-stage parser

```
LLM text response
     │
     ▼
Stage 1: json.loads()                    ← fast path, well-formed JSON
     │ (JSONDecodeError)
     ▼
Stage 2: strip_code_fences() + retry     ← removes ```json ... ``` wrappers
     │ (JSONDecodeError)
     ▼
Stage 3: json_repair (lazy import)       ← trailing commas, unquoted keys
     │
     ├── dict/list with content → return
     ├── empty {} or [] → REJECT         ← json_repair "repairs" prose into
     │                                      empty containers; guard blocks this
     └── all failed → return raw string
```

Return type is `dict | list | str`. Callers branch on the type: structured data means success, `str` means parse failure.

### ensure_json_safe — serialization boundary

Recursively converts non-JSON-safe types before handing data to SDK calls or JSONL writes:

- `float('nan')` / `float('inf')` → `None` (with warning)
- `bytes` → UTF-8 string
- `set` / `frozenset` / `tuple` → `list`
- `datetime` / `date` → ISO-8601 string
- Non-string dict keys → `str(key)`

---

## Filesystem & Path

### atomic_write.py

```
atomic_json_write(path, data)
  1. tempfile.mkstemp() in same directory as target
  2. json.dump() to temp file
  3. flush + fsync (optional, default on)
  4. atomic rename (temp → target)
  On failure: temp file unlinked, original untouched
```

Used by batch infrastructure (registry, context maps, recovery state) and HITL review persistence.

### path_utils.py

| Function | What it does |
|----------|-------------|
| `get_path_manager()` | Thread-safe singleton (double-checked locking) for `PathManager` |
| `set_path_manager(pm)` | DI injection point for scoped instances |
| `derive_workflow_root(path)` | Find workflow root from a path inside a workflow |
| `resolve_relative_to(path, base)` | Safe relative resolution (avoids silent discard on absolute paths) |
| `find_project_root()` | Walk up looking for `agent_actions.yml` |

### derive_workflow_root — 3-strategy resolution

```
Input: any path inside a workflow (e.g. agent_io/target/extract/data.json)

Strategy 1 (fast path):
  Find "agent_io" in path parts → truncate to parent
  /project/agent_io/target/extract → /project

Strategy 2 (walk-up):
  Resolve path, walk up checking for agent_config/ sibling directory

Strategy 3 (fallback):
  Return path itself (if dir) or path.parent (if file) + log warning
  Never blindly chains .parent — bounded by the walk-up termination
```

### path_safety.py

- `assert_path_contained(child, parent)` — resolves symlinks, raises `ValueError` on traversal escape
- `sanitize_path_component(name)` — replaces separators/null bytes, truncates with hash suffix if > 200 bytes

---

## Passthrough Transformation

```
PassthroughTransformer.transform_with_passthrough()
     │
     ▼
Strategy dispatch (first match wins — ORDER IS LOAD-BEARING):
     │
     ├── 1. PrecomputedStructuredStrategy    ← passthrough_fields + already structured
     ├── 2. PrecomputedUnstructuredStrategy   ← passthrough_fields + flat data
     ├── 3. ContextScopeStructuredStrategy   ← context_scope.passthrough + structured
     ├── 4. ContextScopeUnstructuredStrategy ← context_scope.passthrough + flat
     ├── 5. NoOpStrategy                     ← no passthrough configured
     └── 6. DefaultStructureStrategy         ← catch-all fallback
           │
           ▼
     Strategy returns flat action output dicts
           │
           ▼
     RecordEnvelope.build() wraps under action namespace
     + preserves upstream namespaces
           │
           ▼
     FieldManager.ensure_required_fields() guarantees metadata
```

Strategies are evaluated in list order. `PrecomputedStructuredStrategy` must come before `ContextScopeStructuredStrategy` because pre-computed passthrough fields (from `field_context`) take precedence over raw `context_scope` config — they carry ancestry-resolved data that `context_scope` alone cannot reconstruct.

---

## Content Helpers

```
content.py — namespaced content model

wrap_content(action_name, output, existing)
  → delegates to RecordEnvelope.build_content() (lazy import)
  → {**existing_namespaces, action_name: output}

read_namespace(record, action_name, field)
  → record["content"][action_name][field]

get_existing_content(record, is_first_stage=False)
  → PRIMARY ENTRY POINT for both batch and online paths
  │
  ├── record has "content" dict → return it
  ├── is_first_stage=True → synthesize {"source": {non-framework fields}}
  └── else → return {}
```

`get_existing_content` is critical for first-stage actions (the first action in a workflow). Raw input records have no `"content"` key — they are flat dicts of user data. This function synthesizes a `{"source": ...}` namespace so downstream code can treat all records uniformly. Both batch preparator and online strategy call this function. Never bypass it with `record.get("content")`.

---

## Safe Error Formatting

`safe_format.py` provides crash-proof exception formatting:

| Function | Purpose |
|----------|---------|
| `safe_format_error(exc)` | `str()` → `repr()` → type name → last resort string. Never raises. |
| `extract_root_cause(exc)` | Walks `__cause__` / `__context__` chain with cycle detection (max depth 10) |
| `get_error_chain(exc)` | Returns full chain as list, outermost to root |
| `format_exception_chain_for_debug(exc)` | Multi-line formatted chain with context for logging |

---

## File Index

### Core utilities
| File | Role |
|------|------|
| `constants.py` | Shared constants — public API surface for the entire codebase |
| `content.py` | Namespaced content model (wrap, read, synthesize for first-stage) |
| `atomic_write.py` | Crash-safe JSON file writes (temp + fsync + rename) |
| `json_parsing.py` | 3-stage LLM JSON parser (json.loads → fence strip → json_repair) |
| `json_safety.py` | Recursive JSON serialization safety (NaN, bytes, datetime, etc.) |
| `safe_format.py` | Crash-proof exception formatting and chain walking |
| `dict.py` | `get_nested_value` — dot-separated field access on nested dicts |
| `graph_utils.py` | `topological_sort` for action dependency resolution |
| `schema_utils.py` | Schema file loading and format detection |
| `schema_echo.py` | Detects when an LLM returns its schema definition instead of data |
| `template_escape.py` | Jinja2 template escaping utilities |

### Path and filesystem
| File | Role |
|------|------|
| `path_utils.py` | PathManager singleton, `derive_workflow_root`, path resolution |
| `path_safety.py` | Containment assertion, path component sanitization |
| `path_security.py` | Path security validation |
| `file_handler.py` | Recursive file/folder discovery (stdlib only) |
| `file_utils.py` | Additional file utilities |
| `project_root.py` | Project root detection (`find_project_root`, `ensure_in_project`) |
| `tools_resolver.py` | Normalizes `tools` / `tool_path` config syntax |

### Identity and tracking
| File | Role |
|------|------|
| `id_generation/generator.py` | UUID4/UUID5 generation for target_id, node_id, source_guid, content_hash |
| `lineage/builder.py` | Lineage chain construction and ancestry propagation |
| `correlation/version_id.py` | Deterministic version correlation IDs (LRU-capped, thread-safe) |
| `field_management/manager.py` | Ensures required metadata fields on every output record |

### UDF system
| File | Role |
|------|------|
| `module_loader.py` | Thread-safe module loading via importlib (no sys.path mutation) |
| `udf_management/registry.py` | `UDF_REGISTRY` dict, `@udf_tool` decorator, lookup functions |
| `udf_management/tooling.py` | UDF execution, error wrapping, `FileUDFResult` validation |

### Transformation
| File | Role |
|------|------|
| `transformation/passthrough.py` | `PassthroughTransformer` — strategy dispatch orchestrator |
| `transformation/strategies/` | Six strategies: Precomputed/ContextScope x Structured/Unstructured + NoOp + Default |
| `passthrough_builder.py` | `PassthroughItemBuilder` — builds normalized passthrough records with metadata |

### Error handling
| File | Role |
|------|------|
| `error_handler.py` | Configuration and validation error utilities |
| `error_wrap.py` | Decorator for wrapping validation errors with context |

---

## Caveats

1. **constants.py is public API.** Imported by ~57 files. Renaming or removing any constant is a breaking change across the entire codebase. Treat every export as a stable interface.

2. **`generate_content_hash` is a checkpoint key.** The UUID5 hash produced by `IDGenerator.generate_content_hash()` is used for deduplication and incremental checkpointing. Changing the hash algorithm or serialization order would invalidate all existing checkpoints.

3. **`UDF_REGISTRY` is process-wide.** It assumes one workflow per process. Running concurrent workflows in the same process would share (and potentially corrupt) the registry. The `clear_registry()` function cleans both the dict and `sys.modules` entries.

4. **module_loader avoids sys.path mutation.** This is deliberate — `sys.path` manipulation is process-global and non-reversible in a meaningful way. Instead, `load_module_from_path` uses `importlib.util.spec_from_file_location` and registers under a synthetic `agent_actions._udfs.{name}` namespace.

5. **atomic_write requires the parent directory to exist.** `tempfile.mkstemp(dir=path.parent)` will raise `FileNotFoundError` if `path.parent` does not exist. Callers must ensure the directory exists before calling.

6. **derive_workflow_root fallback is intentionally conservative.** The third strategy returns `path` itself (or `path.parent`) rather than walking up indefinitely. This prevents silent misidentification of a random ancestor as the workflow root when neither `agent_io` nor `agent_config/` markers are found.

7. **Passthrough strategy order is load-bearing.** `PrecomputedStructuredStrategy` must precede `ContextScopeStructuredStrategy` because pre-computed fields carry ancestry-resolved data. Reordering the strategy list changes which passthrough source wins.

8. **get_existing_content synthesizes source namespace for first-stage.** When `is_first_stage=True` and the record has no `"content"` key, it builds `{"source": {non-framework fields}}`. This is the only place where raw input records are promoted into the namespaced content model. Bypassing this function with `record.get("content")` will lose the source namespace on first-stage records.

9. **json_repair empty-container guard.** `json_repair` aggressively "repairs" arbitrary prose into `{}` or `[]`. The guard in `parse_llm_json` rejects empty results from `json_repair` to prevent downstream code from treating garbage input as a valid empty response.

10. **VersionIdGenerator uses class-level state.** The `OrderedDict` registry and `RLock` live on the class, not on instances. All callers share the same registry. `clear()` must be called between test runs to avoid cross-test contamination.

11. **Content.py lazy imports are load-order sensitive.** Both `wrap_content` and `get_existing_content` import from `agent_actions.record.envelope` inside the function body. This breaks a circular dependency (`record` imports from `utils`, `utils/content.py` imports from `record`). Moving these to top-level imports would cause an `ImportError` at startup.
