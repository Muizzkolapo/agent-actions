# State Management Manifest

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `environment_config.py` | Module | Environment configuration models with validation using pydantic-settings. | `errors` |
| `Environment` | Class | Supported environment types. | - |
| `LogLevel` | Class | Supported log levels. | - |
| `EnvironmentConfig` | Class | Environment configuration with validation. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate_api_keys` | Method | Validate API key format if provided. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate_database_url` | Method | Validate database URL format if provided. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `is_development` | Method | Check if running in development environment. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `is_production` | Method | Check if running in production environment. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_log_level` | Method | Get appropriate log level based on environment and debug setting. | - |
| `APIConfig` | Class | API-specific configuration extracted from environment config. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `from_environment` | Method | Create API config from environment configuration. | - |
| `PerformanceConfig` | Class | Performance-specific configuration extracted from environment config. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `from_environment` | Method | Create performance config from environment configuration. | - |
| `lineage_mixin.py` | Module | Lineage tracking mixin for processors. | `utilities` |
| `LineageTrackingMixin` | Class | Mixin class that provides standardized lineage tracking functionality. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `generate_node_id` | Method | Generate a node ID for this processor. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `add_lineage_to_item` | Method | Add lineage tracking to an item based on a source item. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `add_context_lineage_to_item` | Method | Add lineage tracking to an item based on context data. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `add_lineage_to_items` | Method | Add lineage tracking to multiple items with unique node IDs. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `create_processed_item_with_lineage` | Method | Create a processed item with lineage tracking. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `ensure_items_have_required_fields` | Method | Ensure all items have required fields (target_id, source_guid, node_id). | - |
| `path_config.py` | Module | Path configuration for agent-actions. | `errors` |
| `load_project_config` | Function | Load project-specific configuration from YAML files. | - |
| `path_manager.py` | Module | Centralized path management for agent-actions. | - |
| `PathType` | Class | Enumeration of standard path types in the agent-actions system. | - |
| `PathConfig` | Class | Configuration for path operations. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `for_environment` | Method | Get environment-specific configuration. | - |
| `PathManagerError` | Class | Base exception for PathManager errors. | - |
| `ProjectRootNotFoundError` | Class | Raised when project root cannot be located. | - |
| `PathValidationError` | Class | Raised when path validation fails. | - |
| `PathManager` | Class | Centralized path management for agent-actions. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_project_root` | Method | Find and return the project root directory. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_standard_path` | Method | Get a standard path based on type and parameters. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_agent_paths` | Method | Get all standard paths for a specific agent. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `ensure_path_exists` | Method | Ensure a path exists, creating directories as needed. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate_path` | Method | Validate a path against requirements. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate_standard_path` | Method | Validate a path against standard requirements for its type. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `normalize_path` | Method | Normalize a path to a resolved Path object. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `is_within_project` | Method | Check if a path is within the project root. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_relative_to_project` | Method | Get path relative to project root. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `find_files_by_pattern` | Method | Find files matching a pattern within the project or specified base path. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `clean_path` | Method | Clean/remove a path. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `create_mirror_path` | Method | Create a mirrored path by replacing source base with target base. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `clear_cache` | Method | Clear the internal path cache. | - |
