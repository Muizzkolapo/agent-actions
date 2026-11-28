# Static Analyzer Manifest

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `cache_checks.py` | Module | Prompt-caching checks: record data in a cached prompt and `{% cache_point %}` tags. | - |
| `PromptCacheChecksMixin` | Class | `WorkflowStaticAnalyzer` mixin: `_check_prompt_caching_on_record_data`, `_check_cache_points`. | - |
| `conflict_detector.py` | Module | Conflict detector for workflow field name collisions. | - |
| `ConflictSeverity` | Class | Severity level of a conflict. | - |
| `ConflictType` | Class | Type of conflict detected. | - |
| `FieldProducer` | Class | Information about an action that produces a field. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `to_dict` | Method | Convert to dictionary for JSON serialization. | - |
| `AffectedReference` | Class | A reference affected by a conflict. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `to_dict` | Method | Convert to dictionary for JSON serialization. | - |
| `Conflict` | Class | Base class for all conflict types. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `to_dict` | Method | Convert to dictionary for JSON serialization. | - |
| `ConflictAnalysisResult` | Class | Result of conflict analysis. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `has_conflicts` | Method | Check if any conflicts were detected. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `error_count` | Method | Count of error-level conflicts. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `warning_count` | Method | Count of warning-level conflicts. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `filter_by_action` | Method | Filter conflicts to those affecting a specific action. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `to_dict` | Method | Convert to dictionary for JSON serialization. | - |
| `ConflictDetector` | Class | Detects field name conflicts in workflows. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `detect_all` | Method | Detect all conflicts in the workflow. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_shadowed_fields` | Method | Get mapping of shadowed fields to their producers. | - |
| `data_flow_graph.py` | Module | Data flow graph for workflow static analysis. | - |
| `ActionKind` | Class | Type of agent node (LLM, TOOL, HITL, SOURCE, SEED). | - |
| `OutputSchema` | Class | Represents the output schema of an agent. Forwarding and drop directives are held as `(namespace, field)` refs (`observe_refs`, `passthrough_refs`, `dropped_refs`) because the runtime pops `prompt_context[ns][field]` — a bare-name set cannot tell `a.score` from `b.score` and cancels every field of that name. `observe_fields` / `passthrough_fields` / `dropped_fields` are bare-name views over them. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `available_fields` | Method | Compute available fields: everything the action produces, plus what it forwards minus the refs it drops. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `drops_field` | Method | Whether `drop` keeps a field out of what the action forwards. Never true for a field the action produces, nor for one a sibling namespace still forwards. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `has_field` | Method | Check if field is available in output. | - |
| `InputSchema` | Class | Represents the input schema of an agent. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `all_fields` | Method | Get all input fields (required + optional). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `requires_field` | Method | Check if a field is required. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `accepts_field` | Method | Check if a field is accepted (required or optional). | - |
| `InputRequirement` | Class | A field reference requirement from an agent. | - |
| `DataFlowNode` | Class | Node in the data flow graph representing an agent. | - |
| `DataFlowEdge` | Class | Edge representing data flow from one agent to another. | - |
| `DataFlowGraph` | Class | Graph representation of workflow data flow. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `add_node` | Method | Add a node to the graph. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_node` | Method | Get a node by name. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `is_special_namespace` | Method | Check if name is a special namespace (source, version, etc.). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_downstream_nodes` | Method | Get all nodes that depend on this agent. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `topological_sort` | Method | Return nodes in topological order (Kahn's algorithm, O(n) via pre-built adjacency map). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `build_edges_from_requirements` | Method | Build edges based on input requirements of each node. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_all_agent_names` | Method | Get names of all non-special nodes. | - |
| `errors.py` | Module | Error classes for static type checking. | `errors` |
| `ErrorSeverity` | Class | Severity level for static type errors. | - |
| `FieldLocation` | Class | Location of a field reference in config. | - |
| `StaticTypeIssue` | Class | Base class for static type checking issues. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `format_message` | Method | Format error for display. | - |
| `StaticTypeError` | Class | Blocking error that prevents workflow execution. | - |
| `StaticTypeWarning` | Class | Non-blocking warning that doesn't prevent execution. | - |
| `StaticValidationResult` | Class | Aggregated result of static type checking. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `is_valid` | Method | Returns True if no blocking errors exist. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `add_error` | Method | Add a blocking error. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `add_warning` | Method | Add a non-blocking warning. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `set_strict_mode` | Method | Enable strict mode where warnings are treated as errors. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `format_report` | Method | Format full validation report. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `raise_if_invalid` | Method | Raise exception if validation failed. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `merge` | Method | Merge another result into this one. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `to_dict` | Method | Convert result to dictionary for JSON serialization. | - |
| `read_through_reserved_name` | Function | The problem and fix text for a read through `action`, `prompt` or `schema`, shared by the type checker and the guard check: `action.<name>.<field>` drops the prefix, `action.<field>` (the docs' old placeholder) names `<action name>` in its place. | - |
| `field_flow_analyzer.py` | Module | Field flow analyzer for workflow data lineage tracking. | - |
| `FieldConsumer` | Class | A consumer of a field. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `to_dict` | Method | Convert to dictionary for JSON serialization. | - |
| `FieldLineage` | Class | Represents a field's journey through the workflow. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `to_dict` | Method | Convert to dictionary for JSON serialization. | - |
| `OutputFieldInfo` | Class | Information about an action's output fields. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `to_dict` | Method | Convert to dictionary for JSON serialization. | - |
| `FieldReference` | Class | A field reference from an upstream agent. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `to_dict` | Method | Convert to dictionary for JSON serialization. | - |
| `InputSchemaInfo` | Class | Information about an action's input schema (for tools). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `to_dict` | Method | Convert to dictionary for JSON serialization. | - |
| `ActionFlowInfo` | Class | Field flow information for a single action. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `to_dict` | Method | Convert to dictionary for JSON serialization. | - |
| `WorkflowFlow` | Class | Complete field flow for a workflow. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `to_dict` | Method | Convert to dictionary for JSON serialization. | - |
| `FieldFlowAnalyzer` | Class | Analyzes field lineage and flow through a workflow. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_full_flow` | Method | Get complete field flow for the entire workflow. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_field_lineage` | Method | Trace a single field from production to all consumption points. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_action_flow_info` | Method | Get field flow info for a single action. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `to_dict` | Method | Convert full analysis to dictionary for JSON serialization. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `filter_to_field` | Method | Filter analysis to a specific field. | - |
| `file_mode_checks.py` | Module | FILE-granularity checks: first-stage FILE actions and flat observed-key collisions. | - |
| `FileModeChecksMixin` | Class | `WorkflowStaticAnalyzer` mixin: `_check_first_stage_file_granularity`, `_check_file_tool_observe_collision` and their helpers `_is_file_mode_bus_action`, `_observed_namespace_fields`. | - |
| `graph_reporting.py` | Module | Read-only views of the analyzer's data flow graph: schemas, summaries, execution order. | - |
| `GraphReportingMixin` | Class | `WorkflowStaticAnalyzer` mixin holding the graph views; each builds the graph first if needed. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_graph` | Method | Return the data flow graph for inspection. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_agent_schema` | Method | Get the output schema for a specific agent. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_agent_input_schema` | Method | Get the input schema for a specific agent. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_action_schemas` | Method | Get input and output schemas for all actions. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `format_action_schemas` | Method | Format action schemas as a readable string. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_data_flow_summary` | Method | Get a summary of data flow in the workflow. | - |
| `guard_checks.py` | Module | Guard checks: literal type mismatches and null namespaces left by skip/filter guards. | - |
| `GuardChecksMixin` | Class | `WorkflowStaticAnalyzer` mixin: `_check_guard_literal_type_mismatch`, `_check_guard_skipped_observe_refs`, `_check_filter_fanin_observe_hazard`, and `_extract_field_types_from_schema`, which `apply_guard_nullable_schema_fixes` also reads. | - |
| `guard_clause_and_behavior` | Function | A guard's clause and `on_false` behavior from an expanded (`clause`, `behavior`) or raw (`condition`, `on_false`) config, or None without a clause. The guard warnings (skip-guarded observes, filter fan-in, literal-type mismatch) and `apply_guard_nullable_schema_fixes` read guards through it (1526). | - |
| `lineage_checks.py` | Module | Lineage checks: drop targets and observed fields reachable through the dependency chain. | - |
| `LineageChecksMixin` | Class | `WorkflowStaticAnalyzer` mixin: `_check_drop_directives`, `_check_lineage_reachability`, `_trace_field_through_chain`. | - |
| `reference_extractor.py` | Module | Extract field references from agent configurations. | - |
| `ReferenceExtractor` | Class | Extracts field references from agent prompts, guards, and directives. A name a top-level `{% set a = b %}` binds to the bare name `b` (`prompt_aliases`, the alias header of an `as:` include) reads `b`: `a.x` and `a.items()` are reported under `b`, unless a loop variable or macro argument of that name hides it; a single-brace match that is the inside of a `{{x.y}}` tag is not reported again. A prompt call of a dict method on a namespace (`ns.items()`, `ns.keys()`) references the namespace whole (`*`), not a field named after the method; `ns.get('f', ...)` with a literal key references `f`. A bare `ns.items` is still the field `items`. A reference is reported under the name it is written with: `action.producer.field`, `action.producer.items()` and a whole `{{ action }}` (likewise `prompt`, `schema`) report the source `action`, for the type checker to refuse, never `producer.field` (1512). A version param of that name (`versions: {param: schema}`) is on the record, so a prompt reading it is not reported; single-brace text names nothing. A SQL guard's references are read from its parsed clause (`clause` once expanded, `condition` raw), location `guard`: each `namespace.field` path, leaving out the names the guard context promotes (record fields, version keys and params) but not a read through a reserved name, which is reported for the type checker to refuse unless a version param of that name is on the record; a UDF guard or an unparseable clause yields none (1516). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `extract_from_agent` | Method | Extract all field references from an agent configuration. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_referenced_agents` | Method | Get set of all agents referenced (excluding special namespaces). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `extract_from_workflow` | Method | Extract references from all agents in a workflow. | - |
| `schema_checks.py` | Module | Output-schema checks: named schemas load, structures are valid, json_mode sends them. | - |
| `SchemaChecksMixin` | Class | `WorkflowStaticAnalyzer` mixin: `_check_named_schemas_load`, `_check_schema_structures`, `_check_json_mode_schema_mismatch`. | - |
| `schema_extractor.py` | Module | Extract output schemas from agent configurations (LLM, tool, HITL). A named schema that cannot be loaded leaves the loader's reason in `load_error` and its name in `failed_schema`, for LLM and tool actions alike. A `dispatch_task()` schema loads every name in `schema_options`: its fields are their union, and each option keeps its own fields in `option_fields`. A tool's observe reference marked optional is listed under its input schema's `optional_fields`. | `docs`, `response_processing` |
| `SchemaExtractor` | Class | Extracts output schemas from various agent types. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `extract_schema` | Method | Extract output schema from agent config. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `extract_input_schema` | Method | Extract input schema from agent config. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `extract_fields_from_json_schema` | Method | Extract top-level field names from a JSON schema dict. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `extract_from_workflow` | Method | Extract schemas from all agents in a workflow. | - |
| `scope_checks.py` | Module | Context-scope checks: wildcard expansion, required scope, template and seed coverage. | - |
| `retrieve_checks.py` | Module | `RetrieveChecksMixin._check_retrieve_corpus_fields`: each `text`, `title`, `id` and `where` field of a retrieve step that searches an earlier action is an output field of that action (its schema fields and passthrough fields), and a `text` field is not an object or a list of objects. Skips a schemaless or dynamic schema. | `llm.providers.tools` |
| `ContextScopeChecksMixin` | Class | `WorkflowStaticAnalyzer` mixin: `_expand_wildcards`, `_check_context_scope_required`, `_check_template_scope_coverage`, `_check_seed_reference_misuse`, `_check_seed_template_observe_overlap`. Logs under the analyzer's module logger. | - |
| `type_checker.py` | Module | Static type checker for workflow field references. A read of a field that some of a dispatched schema's options lack is a warning that names the options that hold it and the ones that do not. | - |
| `StaticTypeChecker` | Class | Performs static type checking on workflow data flow graph. A reference through a name in `RESERVED_NAMES_NO_RECORD_HAS` (`action`, `prompt`, `schema`) is an error naming the spelling to write, checked before the built-in namespaces are let through (1512). An action that does not exist is answered with the closest names (`difflib`). For a `guard` reference, a read of the guarded action itself or of one not upstream is left to `dep_observe_validator.find_reads_not_upstream`; the field is checked against what the action produces (`schema_fields`) plus the `expect` verdict, not what it observes or passes through, which its stored namespace never holds; and a field that an open schema (`additionalProperties`) admits without listing is a warning, not an error (1516). A `prompt` reference and a `context_scope.observe` or `context_scope.passthrough` entry read the same stored namespace and are checked against the same fields, an open schema's unlisted field included (a warning, not an error); a `drop` entry is checked against what the action forwards (1526). It alone checks `observe` and `passthrough` entries, whole path included: past the first key, `_nested_path_problem` walks the field's schema as the runtime's `get_nested_value` walks dicts, refusing a key under a scalar or a list, or one a closed object does not list (a digit is a key like any other there); an object that sets `additionalProperties` or a field with no deeper schema is left alone. Without this, `observe: [prep.text.sub]` failed every record and a `passthrough` of it forwarded nothing: the analyzer's own context-scope check, which reported each bad entry a second time and measured it against what the upstream forwards, is gone. A field the upstream only forwards is answered with the namespace it is stored under (`source.page_content`), and a field another action's schema lists with that action; a reference to an action whose named schema failed to load adds nothing, because the analyzer already refuses that action once at `schema`. A `json_mode: false` action's `output_field` is a known field, not a schemaless one, and a wildcard on a schemaless or dynamic upstream is not warned about. `check_missing_dependencies` is gone: an action reached through `dependencies` is on the record, and one that is not is already refused (1536). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `check_all` | Method | Run all static type checks on the graph. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `check_unused_dependencies` | Method | Find declared dependencies that are never referenced. | - |
| `workflow_static_analyzer.py` | Module | Main workflow static analyzer that orchestrates all components. Keeps `analyze()`, which fixes the order the checks run and their findings are reported in, graph building and the module-level helpers; the checks and graph views live in the mixin modules `WorkflowStaticAnalyzer` is composed of (`scope_checks`, `file_mode_checks`, `schema_checks`, `guard_checks`, `lineage_checks`, `cache_checks`, `graph_reporting`); `guard_clause_and_behavior` and every name the module exported before are still importable from it. Refuses, once per action, a named schema that cannot be loaded, at `config_field="schema"`. Warns once per Anthropic action with `enable_prompt_caching` (once for all versions of an action, under its name) when its prompt reads record data or its schema calls `dispatch_task`, naming each in one message: that prompt is sent without a cache mark. A prompt with `{% cache_point %}` tags is checked by `_check_cache_points` instead, once per action: an error for an Anthropic action with caching on whose template holds more than 3 tags or one in a loop, a macro or a block that captures its text; a warning where the tags are not sent (caching not on, or another vendor), where the schema calls `dispatch_task`, and where the text before the last tag reads a value that changes on every render or a field of an upstream action or per-record seed (whether records of one source share it is not known at load). The fan-in observe hazard (`_check_filter_fanin_observe_hazard`) is not reported for an action that sends the records its guard filters elsewhere (`record.elsewhere`): such a record stays out of a fan-in below it, except at an action that gathers. The skip-guard `may be null at runtime` warning and the filter fan-in hazard warning pass over a reference the action observes as optional (`context_scope.optional`); both hints name the optional form. | - |
| `WorkflowStaticAnalyzer` | Class | Static analyzer for workflow type checking. A schema loaded by name reaches it as the schema file (`{name, fields}`), whose field types the literal-type check now reads; it read none, so it never fired for a named schema. The guard-nullable warning is gone: a filter removes the record from every action below it, a skip is reported by the skip-observe warning on the same entry, and `apply_guard_nullable_schema_fixes` makes the tool's schema accept the null; it also followed passed-through fields under the forwarding action, where they are never stored, and ran after wildcard expansion, so it warned about wildcards (1536). A guard reference to a direct dependency's `output_field`, or any guard reference below a FILE version-merge tool that spreads its output flat (`spreads_output_flat`), is dropped before type checking: the guard context promotes those names, so they are not actions (1516). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `analyze` | Method | Perform static analysis of the workflow. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `from_workflow_file` | Method | Create analyzer from workflow file path. | - |
| `analyze_workflow` | Function | Convenience function to analyze a workflow configuration. | - |
| `apply_guard_nullable_schema_fixes` | Function | Makes a tool's `json_output_schema` accept null for each field it observes that may be null: any field of a filter- or skip-guarded action, and, carried forward until nothing changes, a field a tool returns under the name of one it read that may be null (a relay). Without the carry, `cons` reading `mid.text`, where `mid` returns the skipped `g.text`, failed its output schema on the skipped record and lost it (1536). | - |
