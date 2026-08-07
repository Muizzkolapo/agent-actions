# Tooling Module Architecture

This document maps the moving parts of `agent_actions/tooling/` — the module that powers documentation generation, run tracking, the Language Server Protocol (LSP) experience, and shared rendering utilities.

---

## High-Level Overview

```
                        agent_actions/tooling/
                              |
          +-------------------+-------------------+
          |                   |                   |
      code_scanner.py      docs/              rendering/
      (AST introspection)  (docs generation    (data card
                            + run tracking      rendering)
                            + HTTP server)
          |                   |                   |
          |           +-------+-------+           |
          |           |       |       |           |
          |       scanner/  generator  server     |
          |       parser   run_tracker            |
          |                                       |
          +-------------------+-------------------+
                              |
                           lsp/
                     (Language Server
                      Protocol IDE
                      integration)
```

The module has **four packages**:

| Package | What it does |
|---------|-------------|
| `docs/` | Scans a user project, generates `catalog.json`, tracks workflow runs in `runs.json`, and serves a static documentation site |
| `lsp/` | Language Server Protocol server providing go-to-definition, hover, completions, diagnostics, semantic tokens, and code lenses for workflow YAML files |
| `rendering/` | Shared constants and markdown formatting for data cards, consumed by LSP hover, HITL approval UI, and the docs frontend |
| `code_scanner.py` | AST-based introspection of user tool scripts (`@udf_tool` functions and `TypedDict` schemas) — top-level to break a circular import |

---

## Documentation Generation Pipeline

The `agac docs` CLI command triggers `generate_docs()`, which runs a three-phase pipeline: scan, catalog, write.

```
Phase 1: SCAN                     Phase 2: CATALOG              Phase 3: WRITE
                                                                 
  scan_workflows()                  CatalogGenerator              atomic_json_write()
  scan_prompts()                      .generate()                   catalog.json
  scan_schemas()                                                    runs.json (init only)
  scan_tool_functions()             Enrichment:                   
  scan_runs()                       - Parse workflow YAML        
  scan_logs()                       - Build WorkflowSchemaService 
  scan_vendors()                    - Enrich actions with fields  
  scan_error_types()                - Cross-ref prompts/schemas   
  scan_event_types()                - Aggregate stats             
  scan_examples()                   - Copy README images          
  scan_data_loaders()                                             
  scan_processing_states()                                        
  scan_workflow_data()                                            
  scan_readmes()                                                  
```

### Scanner Organization

The `scanner/` package splits scanning by concern:

```
scanner/
  __init__.py               Orchestration: scan_workflows(), scan_readmes(), re-exports
  data_scanners.py          Project data: prompts, schemas, runs, logs, workflow output
  component_scanners.py     Framework introspection: vendors, error types, event types,
                            examples, data loaders, processing states
```

All scanners accept `project_root: Path` and return dicts. The code scanner (`code_scanner.py`) is imported by `scanner/__init__.py` for tool function discovery, and separately by the static analyzer for input schema inference.

### CatalogGenerator

`CatalogGenerator.generate()` takes all scanned data and produces the catalog structure:

```
catalog = {
  metadata:           {generated_at, total_workflows, generator_version, project_name}
  workflows:          {workflow_id: {actions, readme, latest_run, manifest, ...}}
  actions:            {workflow.action: {...}}   <-- flattened index for fast lookup
  prompts:            {name: {content, used_by: [...]}}
  schemas:            {name: {fields, used_by: [...]}}
  tool_functions:     {name: {signature, docstring, is_udf, input_schema}}
  runs:               {workflow_id: {latest_run, action_metrics, ...}}
  logs:               {validation_errors, validation_warnings, runtime_*}
  vendors:            ...
  error_types:        ...
  event_types:        ...
  examples:           ...
  data_loaders:       ...
  processing_states:  ...
  workflow_data:      ...
  stats:              {total_workflows, total_actions, ...}  <-- 16 counters
}
```

Key enrichment: for each action, the generator builds a `WorkflowSchemaService` to resolve field-level lineage (input fields from `context_scope`, output fields from schema files). This gives the docs frontend enough information to render data flow diagrams.

---

## Run Tracker System

`RunTracker` records workflow execution history to `artefact/runs.json`. It is used at runtime (not just during docs generation) to capture live run progress.

### State Machine

```
start_workflow_run()
       |
       v
  +----------+     record_action_start()     +---------------+
  | running  | ---------------------------->  | action running |
  +----------+                                +-------+-------+
       |                                              |
       |                              record_action_complete()
       |                                              |
       |                                      +-------v-------+
       |                                      | action done   |
       |                                      | (success/     |
       |                                      |  failed/      |
       |                                      |  skipped)     |
       |                                      +---------------+
       |
  finalize_workflow_run()
       |
       v
  +-----------+
  | completed |  (status: success or failed)
  +-----------+
```

### Concurrency and Locking

All mutations to `runs.json` use `portalocker.Lock` with exclusive non-blocking mode and a timeout. The pattern is atomic read-modify-write:

1. Acquire exclusive lock (LOCK_EX | LOCK_NB, with timeout)
2. Read JSON from file handle
3. Modify in memory
4. Seek to 0, truncate, write back
5. Lock released on context manager exit

Write operations that contend on the lock use a `@retry` decorator with exponential backoff (3 attempts, 2s backoff). The file is `touch()`ed before locking to handle the initial-creation race.

### runs.json Structure

```json
{
  "metadata": {"generated_at": "...", "total_runs": N, "schema_version": "1.0"},
  "executions": [
    {
      "id": "run_{workflow_id}_{hex8}",
      "status": "running|success|failed",
      "actions": {
        "action_name": {
          "status": "running|success|failed|skipped",
          "duration_seconds": 1.23,
          "tokens": {"prompt_tokens": N, "completion_tokens": N, "total_tokens": N}
        }
      }
    }
  ],
  "workflow_metrics": {
    "workflow_id": {
      "total_runs": N, "successful_runs": N, "failed_runs": N,
      "success_rate": 0.95, "avg_duration_seconds": 12.3, "total_tokens": N
    }
  }
}
```

Executions are capped at 100 entries (newest first). Workflow metrics are recalculated on every `finalize_workflow_run()` call.

---

## HTTP Server

`serve_docs()` starts a local HTTP server that multiplexes two filesystem roots through a single port:

```
Browser request              DocsRequestHandler.translate_path()
     |
     +-- /artefact/catalog.json  -->  {user_project}/artefact/catalog.json
     +-- /artefact/runs.json     -->  {user_project}/artefact/runs.json
     +-- /artefact/images/...    -->  {user_project}/artefact/images/...
     +-- /index.html             -->  {package}/docs/docs_site/index.html
     +-- /static/...             -->  {package}/docs/docs_site/static/...
     +-- everything else         -->  {package}/docs/docs_site/{path}
```

The `docs_site/` directory under the package contains a pre-built static frontend (Next.js export). The `artefact/` directory in the user's project contains the generated data files.

Path traversal is guarded: `_guard_path()` resolves the target and verifies it is inside its designated root directory, returning an empty string (which becomes a 404) if the path escapes.

---

## LSP Architecture

The LSP server provides IDE integration for agent-actions workflow YAML files, prompt markdown, and tool Python scripts.

### Indexer

`build_index()` creates a `ProjectIndex` by scanning four artifact types:

```
build_index(project_root)
     |
     +-- _index_workflows()  --> actions, dependencies, context_scope, guards, versions
     +-- _index_prompts()    --> prompt names and content previews
     +-- _index_tools()      --> @udf_tool function signatures and docstrings
     +-- _index_schemas()    --> schema field definitions
```

The index supports multi-root workspaces: `find_all_project_roots()` discovers all `agent_actions.yml` files across workspace folders (searching both upward and downward up to 3 levels). Each project gets its own `ProjectIndex`, and `_index_for_file()` routes requests to the deepest matching root.

### Capabilities

| Capability | What it does |
|-----------|-------------|
| Go-to-definition | Jump from `$workflow.PromptName` to the prompt file, `impl: func` to the Python function, `schema: name` to the YAML file, dependency names to their action definitions |
| Hover | Show prompt previews, tool signatures/docstrings, schema fields, action metadata |
| Completions | Prompt names (after `$`), tool functions (after `impl:`), schema names (after `schema:`), action names (in `dependencies`), context scope fields, guard variables, versions keys |
| Diagnostics | Validate references exist, detect duplicate action names, check guard variable availability |
| Document symbols | Outline view showing actions in workflow files, sections in prompt markdown |
| Document highlight | Highlight all references to the symbol under cursor |
| Semantic tokens | Colorize prompt refs, tool refs, schema refs, action refs, seed file refs, context fields |
| Code lenses | Inline summaries for `guard:` and `versions:` blocks |
| Signature help | Available guard/validation variables when typing conditions |
| File watchers | Dynamic registration for workflow YAML, prompts, tools, and schemas |

### Models

`ProjectIndex` is the central data structure:

```
ProjectIndex
  root: Path
  actions:                 {action_name -> Location}
  prompts:                 {"file.PromptName" -> PromptDefinition}
  tools:                   {function_name -> ToolDefinition}
  schemas:                 {schema_name -> SchemaDefinition}
  workflows:               {workflow_name -> directory Path}
  file_actions:            {file_path -> {action_name -> ActionMetadata}}
  workflow_actions:         {workflow_name -> {action_name -> Location}}
  references_by_file:      {file_path -> [Reference]}
  duplicate_actions_by_file: {file_path -> {action_name}}
```

Lookup methods (`get_action`, `get_action_metadata`) resolve with increasing scope: same file, same workflow, then global (flat layout only). This prevents cross-workflow leakage in multi-workflow projects.

---

## Rendering Module

`rendering/data_card.py` provides shared data card formatting used in three places:

1. **LSP hover** -- renders a record as markdown when hovering over output data
2. **HITL approval UI** -- renders records in the Flask-based human review interface
3. **Docs frontend** -- JavaScript mirrors the same field classification logic

### Field Classification

Every record field is classified into one of three groups:

```
IDENTITY:  source_guid, target_id
CONTENT:   everything not in METADATA_KEYS or IDENTITY_KEYS
METADATA:  lineage, node_id, _state, _state_history, _recovery, etc.
```

`METADATA_KEYS` is defined as a `frozenset` of 13 keys. `LONG_FORM_HINTS` identifies fields like `reasoning`, `description`, `summary` that get block-quote rendering instead of inline display.

### render_card_markdown()

```
Input: record dict + optional action_name
       |
       +-- Unwrap namespaced content if action_name provided
       +-- classify_record() -> {identity: [...], content: [...], metadata: [...]}
       |
       v
Output: markdown string
       **Source Guid**: `abc123...`
       ---
       **Field Label**: value
       **Long Field**:
       > block quoted text...
       ---
       _metadata: lineage, node_id, ..._
```

Content fields are capped at `max_fields` (default 12) with a "...and N more fields" overflow notice. Values are truncated at 80-120 characters depending on context.

---

## File Index

### Top-level
| File | Role |
|------|------|
| `code_scanner.py` | AST-based `@udf_tool` and TypedDict extraction (top-level to break circular import) |

### docs/
| File | Role |
|------|------|
| `__init__.py` | Package docstring only — import `generate_docs`, `serve_docs`, `RunTracker` from their submodules |
| `generator.py` | `CatalogGenerator` + `generate_docs()` orchestration |
| `parser.py` | `WorkflowParser` -- YAML parsing and field extraction for catalog |
| `run_tracker.py` | `RunTracker` -- concurrent-safe run recording with file locking |
| `server.py` | `DocsRequestHandler` + `serve_docs()` HTTP server |
| `scanner/__init__.py` | Scanner orchestration: `scan_workflows()`, `scan_readmes()`, re-exports |
| `scanner/data_scanners.py` | Project data scanners: prompts, schemas, runs, logs, workflow output |
| `scanner/component_scanners.py` | Framework introspection: vendors, errors, events, examples, loaders, states |

### lsp/
| File | Role |
|------|------|
| `__init__.py` | Package marker |
| `__main__.py` | `python -m agent_actions.tooling.lsp` entry point |
| `server.py` | `AgentActionsLanguageServer` + all LSP request/notification handlers |
| `indexer.py` | `build_index()`, `find_project_root()`, `find_all_project_roots()` |
| `models.py` | `ProjectIndex`, `ActionMetadata`, `Reference`, `ReferenceType`, `Location`, etc. |
| `resolver.py` | Reference resolution: map a reference to a file location |
| `handlers.py` | Hover content, semantic tokens, document symbols, reference finding |
| `completions.py` | Completion item builders for context scope, guards, versions |
| `diagnostics.py` | Diagnostic publishing, guard variable collection |
| `utils.py` | `uri_to_path()`, `is_in_dependencies_context()` |

### rendering/
| File | Role |
|------|------|
| `__init__.py` | Package marker |
| `data_card.py` | `METADATA_KEYS`, `classify_record()`, `render_card_markdown()` |

---

## Caveats

1. **`code_scanner.py` lives at the top level** to break a circular import chain: `generator.py` -> `schema_service` -> `static_analyzer` -> `schema_extractor` -> `docs.scanner` -> `docs.__init__` -> `generator.py`. Moving it into `docs/scanner/` would re-create this cycle.

2. **`docs_site/` is a build artifact.** It contains the pre-built static frontend (Next.js export). Do not edit files inside it directly -- rebuild from `agent_actions/tooling/docs/frontend/` instead.

3. **`runs.json` is owned by `RunTracker`.** The docs generator only initializes it if it does not exist. All subsequent writes come from `RunTracker` during live workflow execution. Never write to `runs.json` outside of `RunTracker` -- its locking protocol assumes exclusive ownership.

4. **`METADATA_KEYS` is mirrored in 3 places.** The source of truth is `rendering/data_card.py`. The same set must be kept in sync in:
   - `rendering/data_card.py` (Python -- LSP hover, HITL server)
   - `docs/frontend/lib/data-card-utils.ts` (TypeScript -- docs UI)
   - `llm/providers/hitl/approval.html` (injected via server context)

   If you add or remove a metadata key, update all three or fields will be misclassified in one of the surfaces.

5. **LSP multi-root routing uses deepest-match.** When a file belongs to nested projects (e.g., monorepo), `_index_for_file()` picks the project root with the most path components. This prevents a parent project from accidentally claiming files that belong to a child project.

6. **Scanner collision policy is last-write-wins.** Both `scan_workflows()` and `scan_readmes()` use `rglob` ordering (filesystem-dependent). If two `agent_config/` directories contain the same workflow stem, the last one discovered wins. This is by design -- it matches how the catalog pairs READMEs with workflows.
