# Input Module Architecture

This document maps the moving parts of `agent_actions/input/` -- the module that handles everything before an LLM sees a record: file reading, format conversion, data source resolution, UDF discovery, field chunking, guard evaluation, context normalization, and the initial staging pipeline.

---

## High-Level Overview

```
                          agent_actions/input/
                               |
               +---------------+---------------+
               |               |               |
           context/        loaders/      preprocessing/
        (context_scope   (file I/O,     (staging, filtering,
         normalization)   UDF loading,    parsing, chunking,
                          data sources)   field resolution,
                                          transformation)
```

The module has **three packages**:

| Package | What it does |
|---------|-------------|
| `context/` | Normalizes `context_scope` directives (observe, drop, passthrough) and expands version references |
| `loaders/` | Reads files from disk (JSON, CSV, XLSX, XML, PDF, text), discovers UDFs, resolves data sources |
| `preprocessing/` | Staging pipeline, guard filter (WHERE clause AST), field reference resolution, chunking, and text transformation |

---

## Data Flow: From File to LLM-Ready Records

```
User data files (agent_io/staging/)
       |
       v
+---------------------+
| FileReader.read()   |     Format dispatch: .json, .csv, .xlsx,
| (loaders/file_reader)|     .xml, .pdf, .docx, .txt, .md, .html
+----------+----------+
           |
           v
+---------------------+
| Format loaders      |     JsonLoader, TabularLoader, XmlLoader
| (loaders/*.py)      |     convert raw content to list[dict]
+----------+----------+
           |
           v
+---------------------+
| Field validation    |     Rejects reserved field names
| (staging/           |     (source_guid, target_id, etc.)
|  field_validation)  |     in user-supplied data
+----------+----------+
           |
           v
+---------------------+
| Prompt validation   |     Validates staged data against
| (_validate_staged_  |     Jinja2 prompt template
|  data)              |     requirements before processing
+----------+----------+
           |
           v
+---------------------+
| Data preparation    |     Batch: assign batch_id, source_guid,
| (_prepare_batch_    |     target_id, node_id per record
|  data /             |     Online: chunk text, wrap JSON items
|  _prepare_online_   |
|  data)              |
+----------+----------+
           |
           v
+---------------------+
| Source save          |     Deduplicated write to agent_io/source/
| (UnifiedSource      |     via storage backend
|  DataSaver)         |
+----------+----------+
           |
           v
+---------------------+
| Processing dispatch |     Batch: BatchSubmissionService
|                     |     Online: UnifiedProcessor + OnlineLLMStrategy
+---------------------+
```

---

## Source Data Loading Pipeline (loaders/)

### FileReader -- format dispatch

`FileReader` is a thin dispatcher. Given a file path, it picks the handler by extension and returns the raw content:

```
FileReader(file_path)
  |
  +-- .json  --> json.load()        --> dict | list[dict]
  +-- .csv   --> csv.reader()       --> list[list[str]]
  +-- .xlsx  --> pandas read_excel  --> list[dict]
  +-- .xml   --> defusedxml parse   --> (tree, root) tuple
  +-- .pdf   --> pypdf extract_text --> str
  +-- .docx  --> python-docx        --> str (paragraphs joined)
  +-- .txt   --> file.read()        --> str
  +-- .md    --> file.read()        --> str
  +-- .html  --> BeautifulSoup      --> str (text content)
```

Note that CSV returns raw rows (list of lists), not dicts. The `TabularLoader` handles dict conversion downstream. XLSX returns `list[dict]` directly via pandas.

### SourceDataLoader -- storage backend reads

`SourceDataLoader` wraps the `StorageBackend` for reading/writing intermediate source data. It implements the `ISourceDataLoader` interface. Used by downstream actions that need to read a previous action's output as their input:

```
SourceDataLoader(agent_name, storage_backend)
  .load_source_data(relative_path)  --> storage_backend.read_source()
  .save_source_data(relative_path, data)  --> storage_backend.write_source()
```

### Data source resolution

`resolve_start_node_data_source()` determines *where* the initial data comes from:

```
data_source config value
       |
       +-- None / "staging" --> agent_io/staging/ directory
       +-- "/path/to/dir"   --> local folder (validated inside project root)
       +-- {type: "local", folder: "...", file_type: ["json"]}  --> filtered local
       +-- {type: "api", url: "https://...", headers: {...}}     --> fetch + cache
```

API responses are cached by fingerprint (SHA-256 of url + query + headers) under `_remote_cache/api/`. Delete the cache directory to force a refresh.

---

## UDF Discovery and Loading (loaders/udf.py)

UDFs (User-Defined Functions) are Python files in `tools/{workflow}/`. The discovery process:

```
discover_udfs(user_code_path)
  |
  1. discover_tool_files() -- rglob("*.py"), skip _-prefixed and test_-prefixed
  |
  2. For each .py file:
  |    a. Convert path to module name (dir separators -> dots)
  |    b. Skip if already in sys.modules (idempotent)
  |    c. importlib.util.spec_from_file_location() + exec_module()
  |    d. @udf_tool-decorated functions self-register into UDF_REGISTRY
  |
  3. Return UDF_REGISTRY (global dict: name -> {func, metadata})

validate_udf_references(config)
  |
  Walks config tree recursively, collects all "impl" string values,
  verifies each exists in UDF_REGISTRY via get_udf().
  Raises FunctionNotFoundError on miss.
```

The `@udf_tool` decorator (from `utils/udf_management/registry.py`) registers functions at import time. `discover_udfs` triggers the imports; after that, any action config with `impl: my_function` resolves through the global registry.

---

## Initial Pipeline (preprocessing/staging/initial_pipeline.py)

The `process_initial_stage()` function is the entry point for all first-stage data processing. It reads a file, prepares records, saves source data, and dispatches to either batch or online processing.

```
process_initial_stage(InitialStageContext)
  |
  1. FileReader.read() -- raw content + file_type
  2. validate_staging_field_names() -- reject reserved names
  3. _validate_staged_data() -- prompt template compatibility
  4. Branch on run_mode:
  |
  +-- BATCH: _prepare_batch_data()
  |     a. Generate batch_id, node_id
  |     b. Format dispatch (text->chunks, JSON->list, CSV/XLSX->rows, XML->records)
  |     c. _add_batch_metadata() per record:
  |          user payload wrapped under content.source (framework fields stay flat,
  |          so a user column named like a framework field can't be overwritten),
  |          source_guid, target_id, batch_id, batch_uuid,
  |          parent_target_id=None, root_target_id=target_id
  |     d. Apply record_limit slice
  |     e. _save_source_data()
  |     f. _process_batch_mode() --> BatchSubmissionService
  |
  +-- ONLINE: _prepare_online_data()
        a. Format dispatch (text->Tokenizer chunks, JSON->JsonLoader, etc.)
        b. Generate source_guid per item (online does NOT assign target_id here)
        c. Apply record_limit slice
        d. _save_source_data()
        e. _process_online_mode_with_record_processor() --> UnifiedProcessor
```

### source_guid and target_id assignment

In **batch mode**, every record gets `source_guid` and `target_id` assigned during preparation, before anything is sent to the LLM. First-stage records are their own root: `parent_target_id = None`, `root_target_id = target_id`.

In **online mode**, `source_guid` is generated for source saving, but `target_id` assignment happens later inside `UnifiedProcessor`. The source data items get `source_guid` so the source file can be written, but the raw `data_chunk` passed to the processor is *not mutated* -- `OnlineLLMStrategy` hashes raw items independently.

### Source save deduplication

`_should_save_source_items()` compares user-payload field counts (the `content.source` keys, via `_source_payload_keys()`) between new and existing source files. If the existing source data has more fields (richer), the save is skipped. This prevents subsequent runs from overwriting enriched source data with sparser versions.

---

## Context Normalization (context/)

The `normalizer.py` module handles `context_scope` expansion before processing begins:

```
context_scope:           version_base_map:
  observe:                 summarize: [summarize_v1, summarize_v2]
    - summarize.score
    - summarize.*         After expansion:
  drop:                     observe:
    - extraction.ssn          - summarize_v1.score
                              - summarize_v2.score
                              - summarize_v1.*
                              - summarize_v2.*
                            drop:
                              - extraction.ssn
```

`normalize_all_agent_configs()` mutates agent configs in place. It also detects YAML indentation errors where `observe`/`passthrough`/`drop` appear as sibling keys of `context_scope` instead of children (the `context_scope: null` + orphaned directives pattern).

---

## Guard Filtering (preprocessing/filtering/)

Guards control whether a record gets processed, skipped, or filtered out. The system has two layers:

### Layer 1: GuardFilter (guard_filter.py)

The low-level evaluation engine. Parses WHERE clauses into an AST and evaluates them against record data.

```
GuardFilter(cache_size=1000, default_timeout=5)
  |
  .filter_item(FilterItemRequest)
  |
  1. Circuit breaker: if condition previously failed with
  |  GuardSemanticError, return cached error immediately
  |
  2. Submit to ThreadPoolExecutor(max_workers=4)
  |
  3. _evaluate_guard_condition():
  |    a. _cached_parse() -- LRU cache on condition string
  |    b. WhereClauseParser.parse() --> ParseResult with AST
  |    c. ast.evaluate(data, functions) --> bool
  |
  4. Timeout protection: future.result(timeout=N)
  |    Timeout -> FilterResult(error_category=TIMEOUT)
  |
  Returns FilterResult:
    success: bool       -- did evaluation complete?
    matched: bool       -- did the condition match?
    error_category:     -- SEMANTIC | DATA | TIMEOUT
```

### Layer 2: GuardEvaluator (evaluator.py)

The high-level coordinator. Maps `FilterResult` to `GuardResult` using the guard behavior policy.

```
GuardEvaluator.evaluate(item, guard_config, context)
  |
  1. Build evaluation context (merge item + upstream data)
  2. Evaluate conditional_clause (legacy UDF path)
  3. _evaluate_guard():
  |    a. Parse behavior from config: skip | filter | warn
  |    b. Call GuardFilter.filter_item()
  |    c. Reclassify missing-field errors for namespaced content
  |    d. Map FilterResult to GuardResult via behavior policy:
  |
  |    FilterResult        Behavior    GuardResult
  |    -----------------------------------------------
  |    success + matched   any         passed (execute)
  |    success + !matched  skip        skipped (passthrough)
  |    success + !matched  filter      filtered (exclude)
  |    success + !matched  warn        warned (execute + log)
  |    error (SEMANTIC)    any         behavior applies (bypasses passthrough_on_error)
  |    error (DATA)        poe=True    passed (execute anyway)
  |    error (DATA)        poe=False   behavior applies
  |    error (TIMEOUT)     poe=True    passed (execute anyway)
  |    error (TIMEOUT)     poe=False   behavior applies
```

Both `GuardFilter` and `GuardEvaluator` are per-process singletons, accessed via `get_global_guard_filter()` and `get_guard_evaluator()`. The `GuardFilter` executor is cleaned up via `atexit`.

---

## WHERE Clause Parsing (preprocessing/parsing/)

The parser converts guard condition strings into an evaluable AST.

```
"status == 'active' AND score > 0.8"
       |
       v
WhereClauseParser.parse()
       |
       v
  LogicalNode(AND)
   /          \
ComparisonNode  ComparisonNode
(status EQ      (score GT
 'active')       0.8)
```

### Grammar

Built with pyparsing's `infix_notation` for operator precedence:

| Precedence | Operators |
|-----------|-----------|
| Highest | NOT (unary prefix) |
| | IS NULL, IS NOT NULL (unary postfix) |
| | ==, !=, <, <=, >, >=, IN, NOT IN, LIKE, BETWEEN, CONTAINS |
| | AND |
| Lowest | OR |

### AST node types

| Node | Fields | Evaluate |
|------|--------|----------|
| `LiteralNode` | value (str, number, bool, None, list) | Returns value |
| `FieldNode` | field_path (dotted string) | Looks up `data[path]` via `get_nested_value()` |
| `ComparisonNode` | left, operator, right? | Dispatches to `OPERATORS[op]` |
| `LogicalNode` | operator, left, right? | Short-circuit AND/OR/NOT |
| `FunctionNode` | name, args | Dispatches to `FUNCTIONS[name]` |

Field lookup raises `MissingFieldError` (DATA category) when the path does not exist. Unquoted string literals on the RHS of a comparison raise `GuardSemanticError` (SEMANTIC category) so the circuit breaker can fast-fail on subsequent records.

### Caching

- `WhereClauseParser.parse_cached()` -- LRU cache (1000 entries) on the condition string
- `GuardFilter._cached_parse()` -- second LRU cache layer for the filter's own parse calls
- Parser uses pyparsing's packrat caching (`ParserElement.enable_packrat()`)

---

## Field Resolution (preprocessing/field_resolution/)

`ReferenceParser` handles the three syntaxes used across the system for referring to another action's output fields:

```
Format       Example                  Where used
------       -------                  ----------
SELECTOR     action.field             guard clauses, context_scope
TEMPLATE     {action.field}           legacy prompt templates
JINJA        {{ action.field }}       modern prompt templates
```

Parsing splits on the first dot: everything before is `action_name`, everything after is `field_path` (supports nested dotted paths like `action.nested.child`).

```
ReferenceParser.parse("extraction.tags")
  --> ParsedReference(
        action_name="extraction",
        field_path=["tags"],
        format_type=SELECTOR
      )

ReferenceParser.parse_batch(prompt_text)
  --> [ParsedReference, ...]   (all references found in text)
```

The resolver (`resolver.py`) and validator (`validator.py`) use parsed references to:
- Resolve field values from upstream action outputs
- Validate that referenced actions and fields exist in the workflow graph
- Detect typos via fuzzy matching suggestions

---

## File Index

### Loaders
| File | Role |
|------|------|
| `loaders/file_reader.py` | Format dispatcher -- reads any supported file type |
| `loaders/json.py` | JSON list/dict normalization |
| `loaders/tabular.py` | CSV/XLSX to list[dict] conversion |
| `loaders/xml.py` | XML to dict conversion |
| `loaders/text.py` | Text file handling |
| `loaders/source_data.py` | StorageBackend wrapper for source reads/writes |
| `loaders/data_source.py` | Start-node data source resolution (staging/local/API) |
| `loaders/udf.py` | UDF discovery, import, and validation |
| `loaders/base.py` | Abstract base classes for loaders |

### Context
| File | Role |
|------|------|
| `context/normalizer.py` | context_scope normalization, version expansion, orphan detection |

### Preprocessing -- staging
| File | Role |
|------|------|
| `preprocessing/staging/initial_pipeline.py` | Entry point: file read -> prepare -> save -> dispatch |
| `preprocessing/staging/field_validation.py` | Reserved field name validation for staged data |

### Preprocessing -- filtering
| File | Role |
|------|------|
| `preprocessing/filtering/guard_filter.py` | Low-level AST evaluation with timeout + circuit breaker |
| `preprocessing/filtering/evaluator.py` | High-level guard evaluation with behavior policy |

### Preprocessing -- parsing
| File | Role |
|------|------|
| `preprocessing/parsing/parser.py` | WHERE clause parser (pyparsing grammar + LRU cache) |
| `preprocessing/parsing/ast_nodes.py` | AST node types, evaluation logic, error types |
| `preprocessing/parsing/operators.py` | Operator and function registries |

### Preprocessing -- field resolution
| File | Role |
|------|------|
| `preprocessing/field_resolution/reference_parser.py` | Unified parser for selector/template/Jinja references |
| `preprocessing/field_resolution/resolver.py` | Resolves references to concrete field values |
| `preprocessing/field_resolution/validator.py` | Validates references against workflow graph |
| `preprocessing/field_resolution/schema_field_validator.py` | Schema-level field validation |
| `preprocessing/field_resolution/context_provider.py` | Evaluation context assembly |
| `preprocessing/field_resolution/exceptions.py` | InvalidReferenceError and related |

### Preprocessing -- transformation
| File | Role |
|------|------|
| `preprocessing/transformation/string_transformer.py` | Tokenizer: text splitting by token count |
| `preprocessing/transformation/transformer.py` | General data transformation utilities |

---

## Caveats

### Format-specific quirks

- **CSV**: `FileReader` returns `list[list[str]]` (raw rows), not `list[dict]`. The `TabularLoader` handles dict conversion using the first row as headers. The initial pipeline passes `content=None` and `file_path` to `TabularLoader` so it reads the file itself.
- **XML**: `FileReader` returns a `(tree, root)` tuple, not a string. Like CSV, the `XmlLoader` reads the file directly when invoked from the initial pipeline.
- **XLSX**: `FileReader` returns `list[dict]` via pandas, which means XLSX is the only tabular format where `FileReader` does the full conversion. CSV and XML do not.
- **JSON batch placeholders**: `FileReader._read_json()` rejects JSON files that look like batch job placeholders (`{"batch_job_id": ..., "status": "submitted"}`), raising an error to prevent re-processing in-flight batches.

### source_guid assignment timing

Batch mode assigns `source_guid` during `_add_batch_metadata()`, before source save and before LLM submission. Online mode generates `source_guid` for the source save copy, but the raw `data_chunk` is not mutated -- `OnlineLLMStrategy` independently hashes raw items to derive its own `source_guid`. The two GUIDs may differ because they serve different purposes (source lineage vs processing identity).

### Guard filter thread pool

`GuardFilter` uses a `ThreadPoolExecutor(max_workers=4)` to enforce evaluation timeouts. Every `filter_item()` call submits work to this pool and blocks on `future.result(timeout=N)`. The pool is a per-process singleton cleaned up via `atexit.register()`. In tests, call `reset_global_guard_filter()` to shut down and recreate the pool between test cases.

### Semantic error circuit breaker

When a guard condition raises `GuardSemanticError` (e.g., unquoted string literal), the error is cached by condition string. All subsequent evaluations of the same condition return the cached error immediately without re-evaluation. This prevents the same broken condition from logging thousands of warnings across a large dataset.

### Context scope orphan detection

A common YAML indentation mistake puts `observe`/`passthrough`/`drop` as siblings of `context_scope` instead of children. `normalize_all_agent_configs()` detects this pattern (null `context_scope` + orphaned directive keys) and raises `ConfigurationError` with a corrective YAML example.
