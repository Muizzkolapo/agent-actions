# Static Analyzer Manifest

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
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
| `OutputSchema` | Class | Represents the output schema of an agent. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `available_fields` | Method | Compute available fields. | - |
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
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `add_edge` | Method | Add an edge to the graph. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_node` | Method | Get a node by name. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `has_node` | Method | Check if a node exists. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `is_special_namespace` | Method | Check if name is a special namespace (source, version, etc.). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_upstream_nodes` | Method | Get all nodes that this agent depends on. | - |
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
| `reference_extractor.py` | Module | Extract field references from agent configurations. | - |
| `ReferenceExtractor` | Class | Extracts field references from agent prompts, guards, and directives. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `extract_from_agent` | Method | Extract all field references from an agent configuration. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_referenced_agents` | Method | Get set of all agents referenced (excluding special namespaces). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `extract_from_workflow` | Method | Extract references from all agents in a workflow. | - |
| `schema_extractor.py` | Module | Extract output schemas from agent configurations (LLM, tool, HITL). | `docs`, `response_processing` |
| `SchemaExtractor` | Class | Extracts output schemas from various agent types. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `extract_schema` | Method | Extract output schema from agent config. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `extract_input_schema` | Method | Extract input schema from agent config. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `extract_fields_from_json_schema` | Method | Extract top-level field names from a JSON schema dict. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `extract_from_workflow` | Method | Extract schemas from all agents in a workflow. | - |
| `type_checker.py` | Module | Static type checker for workflow field references. | - |
| `StaticTypeChecker` | Class | Performs static type checking on workflow data flow graph. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `check_all` | Method | Run all static type checks on the graph. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `check_unused_dependencies` | Method | Find declared dependencies that are never referenced. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `check_missing_dependencies` | Method | Find agents that are referenced but not declared in dependencies. | - |
| `workflow_static_analyzer.py` | Module | Main workflow static analyzer that orchestrates all components. | - |
| `WorkflowStaticAnalyzer` | Class | Static analyzer for workflow type checking. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `analyze` | Method | Perform static analysis of the workflow. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_graph` | Method | Return the data flow graph for inspection. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_agent_schema` | Method | Get the output schema for a specific agent. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_agent_input_schema` | Method | Get the input schema for a specific agent. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_action_schemas` | Method | Get input and output schemas for all actions. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `format_action_schemas` | Method | Format action schemas as a readable string. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_data_flow_summary` | Method | Get a summary of data flow in the workflow. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `from_workflow_file` | Method | Create analyzer from workflow file path. | - |
| `analyze_workflow` | Function | Convenience function to analyze a workflow configuration. | - |
