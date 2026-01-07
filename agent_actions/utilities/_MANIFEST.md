# Utilities Manifest

## Sub-Modules

| Sub-Module | Description |
|------------|-------------|
| [context_scope](context_scope/_MANIFEST.md) | Field flow control and context scope management. |
| [correlation](correlation/_MANIFEST.md) | Loop correlation utilities for processors. |
| [field_management](field_management/_MANIFEST.md) | Field management utilities for processors. |
| [field_resolution](field_resolution/_MANIFEST.md) | Field Resolution Module - Centralized field reference parsing and resolution. |
| [id_generation](id_generation/_MANIFEST.md) | ID generation utilities for processors. |
| [lineage](lineage/_MANIFEST.md) | Lineage tracking utilities for processors. |
| [processor](processor/_MANIFEST.md) | Processor infrastructure and helpers. |
| [transformation](transformation/_MANIFEST.md) | Data transformation utilities for processors. |
| [udf_management](udf_management/_MANIFEST.md) | UDF registration and execution system. |

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `constants.py` | Module | Centralized configuration key constants. | - |
| `dict_utils.py` | Module | Common dictionary utility functions. | - |
| `get_nested_value` | Function | Get a nested value from a dictionary using dot notation. | - |
| `output_splitter.py` | Module | Utility for splitting outputs into main and side outputs. | - |
| `split_main_and_side_outputs` | Function | Split processed items into main and side outputs. | - |
| `passthrough_item_builder.py` | Module | Unified passthrough item construction for batch and online modes. | `utilities` |
| `PassthroughItemBuilder` | Class | Unified builder for passthrough items across batch and online modes. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `build_item` | Method | Build passthrough item with consistent structure. | - |
| `path_utils.py` | Module | Utility functions for common path operations. | `errors`, `state_management` |
| `get_path_manager` | Function | Get the global PathManager instance. | - |
| `ensure_directory_exists` | Function | Ensure a directory exists, creating it if necessary. | - |
| `create_side_output_directory` | Function | Create side output directory following the standard pattern. | - |
| `resolve_absolute_path` | Function | Resolve path to absolute Path object. | - |
| `check_path_exists` | Function | Check if a path exists. | - |
| `find_project_root` | Function | Find project root by looking for marker file. | - |
| `create_mirror_source_path` | Function | Create source path by mirroring target path structure. | - |
| `validate_path_permissions` | Function | Validate path permissions. | - |
| `clean_directory` | Function | Clean/remove a directory. | - |
| `get_relative_path` | Function | Get path relative to base directory. | - |
| `find_files_by_extension` | Function | Find all files with specific extension in directory. | - |
| `safe_path_join` | Function | Safely join path parts, ensuring result is within project bounds. | - |
| `create_agent_directory_structure` | Function | Create standard agent directory structure. | - |
| `mkdir_with_parents` | Function | Backward compatibility alias for ensure_directory_exists. | - |
| `get_absolute_path` | Function | Backward compatibility alias for resolve_absolute_path. | - |
| `topological_sort` | Function | Perform a topological sort on a dependency graph. | - |
| `retry.py` | Module | Unified retry utility for agent-actions. | - |
| `RetryStrategy` | Class | Configuration for retry behavior. | - |
| `retry` | Function | Decorator for adding retry logic to functions. | - |
| `safe_format.py` | Module | Safe error formatting utilities that never crash. | - |
| `safe_format_error` | Function | Safely format any exception without risk of cascading failures. | - |
| `extract_root_cause` | Function | Walk exception chain to find root cause, handling circular references safely. | - |
| `get_error_chain` | Function | Get the full exception chain as a list, from outermost to root cause. | - |
| `safe_get_exception_message` | Function | Safely extract just the message portion of an exception. | - |
| `format_exception_context` | Function | Safely format exception context (usually a dict). | - |
| `format_exception_chain_for_debug` | Function | Format the complete exception chain for debugging purposes. | - |
| `tools_resolver.py` | Module | Shared utility for resolving tools_path from agent configuration. | - |
| `resolve_tools_path` | Function | Resolve tools path from agent config. | - |
