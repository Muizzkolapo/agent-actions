# Context Scope Manifest

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `context_scope_processor.py` | Module | Context Scope Processor - Field flow control for LLM context and output. | `input_loading`, `preprocessing`, `state_management`, `utilities` |
| `ContextScopeProcessor` | Class | Processes context_scope configuration for field flow control. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `parse_field_reference` | Method | Parse field reference in 'action.field' format, returning (action_name, field_name). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `extract_field_names_from_references` | Method | Extract field names from list of field references. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `extract_field_value` | Method | Extract field value from nested field_context structure, returning None if not found. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `apply_context_scope` | Method | Apply context_scope rules, returning (prompt_context, llm_context, passthrough_fields). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `format_llm_context` | Method | Format llm_context dict as readable text for LLM message injection. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `merge_passthrough_fields` | Method | Merge passthrough fields into LLM response. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `build_field_context_with_history` | Method | Build field context with agent namespaces, auto-loading previous actions from lineage. | - |
| `llm_context_builder.py` | Module | LLM Context Builder - Mode-specific implementations for batch and realtime. | `preprocessing`, `utilities` |
| `LLMContextBuilder` | Class | Unified builder for LLM context across batch and realtime modes. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `build_llm_context_for_batch` | Method | Build LLM context for batch mode. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `build_llm_context_for_realtime` | Method | Build LLM context for realtime mode. | - |
| `llm_context_utils.py` | Module | LLM Context Computation Utilities. | - |
| `LLMContextUtils` | Class | Utility class for computing LLM context from agent configurations. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `compute_llm_context` | Method | Compute the fields that will be available to the next agent's LLM. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `compute_output_fields` | Method | Compute the fields that will be in the agent's output. | - |
| `static_data_loader.py` | Module | Static Data Loader for external reference files in context_scope configuration. | `errors` |
| `StaticDataLoadError` | Class | Exception raised during static data loading. | - |
| `StaticDataLoader` | Class | Loads static/seed data files with caching and path validation. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `load_static_data` | Method | Load all static data files specified in context_scope.static_data. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `clear_cache` | Method | Clear the file cache. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_cache_stats` | Method | Get cache statistics for debugging. | - |
