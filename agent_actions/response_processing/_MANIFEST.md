# Response Processing Manifest

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `action_expander.py` | Module | Workflow format converter for expanding action-based configurations. | `errors`, `llm_invocation`, `response_processing`, `utilities` |
| `ActionExpander` | Class | Converts action-based workflow configurations to agent configurations. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `expand_actions_to_agents` | Method | Convert action-based configuration to agent-based configuration with loop expansion. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate_guard_references` | Method | Validate that guard conditions only reference valid upstream actions. | - |
| `base.py` | Module | Base classes and utilities for response interceptors. | - |
| `InterceptorResult` | Class | Result from an interceptor's processing. | - |
| `ResponseInterceptor` | Class | Base class for all response interceptors. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `intercept` | Method | Process the response and determine next action. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `configure` | Method | Configure the interceptor from agent config. | - |
| `InterceptorChain` | Class | Manages the chain of interceptors. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `process` | Method | Run response through all interceptors. | - |
| `config_field_definitions.py` | Module | Centralized config field definitions for ActionExpander. | - |
| `inherit_simple_fields` | Function | Automatically inherit simple config fields from action/defaults. | - |
| `config_schema.py` | Module | Configuration schema models for agent response processing. | `errors` |
| `FilterScope` | Class | Scope for WHERE clause filtering. | - |
| `WhereClauseBehavior` | Class | Behavior when WHERE clause condition fails. | - |
| `WhereClauseConfig` | Class | Configuration for WHERE clause filtering. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate_clause` | Method | Validate the WHERE clause syntax. | - |
| `SkipConditionConfig` | Class | Configuration for agent skip conditions (safe replacement for eval-based skip_if). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate_expression` | Method | Validate custom expressions for safety. | - |
| `DefaultAgentConfig` | Class | Default settings applied to each agent configuration. | - |
| `AgentConfig` | Class | Schema for an individual agent configuration entry. | - |
| `config_types.py` | Module | Type definitions for agent configuration structures. | - |
| `AgentEntryDict` | Class | Typed representation of a single agent configuration entry. | - |
| `consolidated_guard.py` | Module | Consolidated guard configuration with explicit behavior control. | `errors` |
| `GuardBehavior` | Class | Behavior options when guard condition fails. | - |
| `GuardConfig` | Class | Consolidated guard configuration with condition and behavior control. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `is_udf_condition` | Method | Check if condition is a UDF expression. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `is_sql_condition` | Method | Check if condition is a SQL-like expression. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_condition_expression` | Method | Get the clean condition expression (without udf: prefix). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `from_dict` | Method | Create GuardConfig from dictionary (YAML format). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `from_string` | Method | Create GuardConfig from legacy string format. | - |
| `parse_guard_config` | Function | Parse guard configuration from various formats. | - |
| `factory.py` | Module | Factory for creating response interceptors from configuration. | `errors`, `reprompting`, `validation` |
| `InterceptorFactory` | Class | Factory for creating interceptors from configuration. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `create_interceptor` | Method | Create an interceptor instance from configuration. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `build_chain` | Method | Build an interceptor chain from a list of configurations. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `register_interceptor` | Method | Register a new interceptor type. | - |
| `guard_parser.py` | Module | Guard expression parser for handling both UDF and SQL-like conditions. | `errors` |
| `GuardType` | Class | Types of guard expressions. | - |
| `GuardExpression` | Class | Parsed guard expression. | - |
| `GuardParser` | Class | Parser for guard expressions supporting both SQL-like and UDF syntax. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `parse` | Method | Parse a guard expression and determine its type. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `is_udf_guard` | Method | Check if a guard expression is a UDF. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `is_sql_guard` | Method | Check if a guard expression is SQL-like. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `parse_consolidated` | Method | Parse consolidated guard configuration. | - |
| `parse_guard` | Function | Convenience function to parse guard expressions. | - |
| `pipeline_config.py` | Module | Pipeline configuration models for workflow and stage management. | `errors` |
| `ExecutionMode` | Class | Pipeline execution modes. | - |
| `ErrorHandlingStrategy` | Class | Error handling strategies for pipeline execution. | - |
| `StageType` | Class | Types of pipeline stages. | - |
| `StageConfig` | Class | Configuration for a pipeline stage. | - |
| `AgentStageConfig` | Class | Configuration for agent-based pipeline stages. | - |
| `WorkflowConfig` | Class | Configuration for agent workflow execution. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate_execution_order` | Method | Validate that all agents in execution order are defined. | - |
| `PipelineConfig` | Class | Main pipeline configuration. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `add_stage` | Method | Add a stage to the pipeline. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_stage` | Method | Get a stage by name. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `remove_stage` | Method | Remove a stage from the pipeline. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate_dependencies` | Method | Validate stage dependencies are satisfied. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_execution_order` | Method | Get stage execution order based on dependencies. | - |
| `PipelineRegistry` | Class | Registry for pipeline configurations. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `register_pipeline` | Method | Register a pipeline configuration. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `register_workflow` | Method | Register a workflow configuration. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_pipeline` | Method | Get a pipeline configuration. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_workflow` | Method | Get a workflow configuration. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `list_pipelines` | Method | List all registered pipeline names. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `list_workflows` | Method | List all registered workflow names. | - |
| `schema_change.py` | Module | Schema compilation and transformation utilities for multi-vendor support. | `errors`, `prompt_generation`, `response_processing`, `utilities` |
| `compile_field` | Function | Convert a single unified field into the shape required by the target system. | - |
| `compile_unified_schema` | Function | Convert a unified YAML/JSON definition into the schema dialect required by | - |
| `prepare_schema_unified` | Function | Unified schema preparation for both online and batch modes. | - |
| `schema_loader.py` | Module | Schema loading utilities. | `file_io`, `prompt_generation` |
| `SchemaLoader` | Class | A class for loading schemas. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `return_schema` | Method | Return the set of schema names used by an agent. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `load_schema` | Method | Load a schema from YAML file. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate_schemas_exist` | Method | Validates that each schema file exists anywhere in the project. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `construct_schema_from_dict` | Method | Construct a unified schema from a simple key-value dictionary. | - |
