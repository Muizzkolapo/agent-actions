# Efficiency Review: Branch `claude/reverent-shirley` vs `main`

**Scope:** Changes introducing `WorkflowSchemaService` across CLI, docs generator, and coordinator
**Date:** 2026-03-21
**Files reviewed:** 4 primary (inspect_base.py, generator.py, schema_service.py, coordinator.py)

---

## Finding 1 -- Double WorkflowSchemaService construction in inspect CLI path

**File:** `agent_actions/cli/inspect_base.py`, lines 46-66
**File:** `agent_actions/workflow/coordinator.py`, lines 35-43, 67-101
**Severity:** Medium -- doubles startup cost of every `inspect` subcommand

**Issue:**
`BaseInspectCommand._load_workflow()` calls `AgentWorkflow(config)` at line 46.
Inside `AgentWorkflow.__init__`, `_run_static_validation()` (line 43) constructs a
`WorkflowSchemaService`, builds the full `DataFlowGraph` (which loads schema YAML
files from disk, AST-scans Python tool files via `scan_tool_functions`, and runs
`infer_dependencies` for every action), then runs `analyze()`.

Immediately after that returns, `_load_workflow()` constructs a *second*
`WorkflowSchemaService` at lines 59-66 with the same workflow config. This second
instance rebuilds the entire `DataFlowGraph` from scratch -- re-reading schema
files, re-scanning tool functions, re-running dependency inference.

The first instance (inside coordinator) is discarded as a local variable in
`_run_static_validation`; none of its results are retained on `self`.

**Cost:**
- 2x schema YAML file reads (one per action with a `schema_name`)
- 2x AST scans of tool Python files (via `scan_tool_functions` inside
  `SchemaExtractor._get_tool_schemas`)
- 2x dependency inference for every action
- 2x graph build and edge computation

**Suggested fix:**
Either (a) expose the `WorkflowSchemaService` from `AgentWorkflow._run_static_validation`
by storing it on `self` so callers like `inspect_base` can reuse it, or (b) make the
inspect command skip constructing its own service when `AgentWorkflow` already performed
validation. Option (a) is simpler: add `self._schema_service = schema_service` at the
end of `_run_static_validation` and expose it via a property. Then `inspect_base` can
do `self.schema_service = workflow._schema_service` instead of building a new one.

---

## Finding 2 -- New WorkflowSchemaService per workflow in generator.py loop

**File:** `agent_actions/tooling/docs/generator.py`, lines 179, 33-48
**Severity:** Medium -- scales linearly with workflow count during doc generation

**Issue:**
`CatalogGenerator.generate()` iterates over all workflows (line 169). For each
workflow, `_build_schema_service(workflow)` constructs a new `WorkflowSchemaService`
(line 179). Each construction triggers a fresh `WorkflowStaticAnalyzer`, which in
turn creates a new `SchemaExtractor`.

`SchemaExtractor.__init__` (schema_extractor.py line 30) sets `self._tool_schemas = None`,
meaning tool function AST scanning is lazy-loaded per extractor. However, since each
workflow gets its own extractor, `scan_tool_functions` will be called once per workflow
that has any tool-type action -- even though the tool function registry is project-global
and workflow-independent.

**Cost for N workflows with tool actions:**
- N separate calls to `scan_tool_functions`, each doing AST parsing of all tool Python
  files in the project
- N separate `DataFlowGraph` builds (unavoidable per workflow, since graphs differ)
- N separate schema YAML file reads for schemas shared across workflows

**Suggested fix:**
Pre-scan tool functions once before the loop and pass the result into each
`WorkflowSchemaService` via `udf_registry`. The `_build_schema_service` method
already accepts a `project_root` but not `udf_registry`. Adding that parameter
would let `SchemaExtractor._get_tool_schemas` short-circuit on the pre-populated
registry.

Similarly, consider passing a single `SchemaLoader` instance (or a schema cache
dict) to avoid re-reading the same YAML files for schemas shared across workflows.

---

## Finding 3 -- _extract_field_metadata does O(N*M) linear scan for Format 1 schemas

**File:** `agent_actions/workflow/schema_service.py`, lines 139-161, called at line 227
**Severity:** Low -- only impacts schemas using the custom `fields` array format

**Issue:**
`_extract_field_metadata` is called once per field in `out.schema_fields` during
`_build_action_schema` (line 227). For Format 1 schemas (those with a `fields`
list), the method does a linear scan of `json_schema["fields"]` for each call.
If an action has F output fields and the `fields` array has M entries, this is
O(F * M).

Additionally, the Format 1 branch has a nested check: for each `field_def` in the
array, if it is an array type with `items.properties`, it also scans those properties.
This adds another layer of iteration.

**Suggested fix:**
Build a lookup dict from the `fields` array once (keyed by `id`) at the top of
`_build_action_schema`, then pass it into `_extract_field_metadata` or replace the
per-field call with a batch extraction. This makes it O(F + M) instead of O(F * M).

For typical action schemas (5-20 fields), this is unlikely to be measurable. Flag
this for monitoring if schemas grow larger.

---

## Finding 4 -- Static validation added to AgentWorkflow.__init__ hot path

**File:** `agent_actions/workflow/coordinator.py`, lines 42-43, 67-101
**Severity:** Medium-High -- adds blocking I/O to every workflow startup

**Issue:**
`_run_static_validation()` is called unconditionally in `AgentWorkflow.__init__`
(line 43), which means every workflow instantiation -- whether for actual execution,
CLI inspect, or doc generation -- now pays the cost of:

1. Building a `WorkflowSchemaService` (constructs `WorkflowStaticAnalyzer`)
2. Importing and checking `UDF_REGISTRY` (line 80-85)
3. Building the full `DataFlowGraph` (reads schema files, scans tool functions, infers dependencies)
4. Running `analyze()` which invokes the type checker, context scope checker, schema structure validator, and unused dependency checker

This is significant new blocking work on the initialization hot path. For small
workflows (3-5 actions, simple schemas), this may add 50-200ms. For larger
workflows with many tool actions requiring AST scanning, it could be notably more.

**Suggested fix:**
Consider one or more of:
- **Lazy validation:** Only run static validation when explicitly requested or on
  first `run()`/`async_run()`, not during `__init__`. The inspect CLI does not need
  this validation to succeed (it has its own schema service).
- **Opt-in flag:** Add `validate: bool = True` to `WorkflowConfig` so callers that
  don't need validation (like inspect commands with `use_tools=False`) can skip it.
- **Cache the result:** At minimum, store the built `WorkflowSchemaService` on
  `self` so downstream code (like Finding 1's inspect path) can reuse it.

---

## Finding 5 -- generator.py _build_schema_service does not pass schema_dir

**File:** `agent_actions/tooling/docs/generator.py`, lines 42-48
**Severity:** Low -- correctness/efficiency gap

**Issue:**
`_build_schema_service` passes `project_root=self.project_path` but does not pass
`schema_dir`. This means `SchemaExtractor.__init__` defaults `schema_dir` to
`Path.cwd() / "schema"` (schema_extractor.py line 28). If the docs generator is
run from a directory different from the project root, schema file lookups will
target the wrong directory, causing unnecessary `FileNotFoundError` exceptions
(caught and logged, but still wasted I/O attempts).

By contrast, `coordinator.py` correctly computes `schema_dir = project_root / "schema"`
and passes it explicitly (line 74, 93).

**Suggested fix:**
Pass `schema_dir=self.project_path / "schema"` (or use the project config to resolve
the schema directory) in `_build_schema_service`.

---

## Summary

| # | Finding | Severity | Wasted Work |
|---|---------|----------|-------------|
| 1 | Double `WorkflowSchemaService` in inspect path | Medium | 2x full graph build + I/O |
| 2 | Per-workflow tool function re-scanning in generator | Medium | N x AST parse of all tool files |
| 3 | O(N*M) linear scan in `_extract_field_metadata` | Low | Quadratic per action for Format 1 |
| 4 | Static validation on `__init__` hot path | Medium-High | Blocks every instantiation |
| 5 | Missing `schema_dir` in generator service construction | Low | Wasted failed I/O lookups |

**Top 3 items to address:**

1. **Finding 4** -- Move static validation out of `__init__` or make it opt-in. This
   has the largest impact since it affects every code path that creates an `AgentWorkflow`.

2. **Finding 1** -- Eliminate the double construction by storing the schema service
   from validation and exposing it. This is a straightforward refactor with no risk.

3. **Finding 2** -- Pre-scan tool functions once in the generator loop. This scales
   with the number of workflows and is simple to implement via a shared `udf_registry`.
