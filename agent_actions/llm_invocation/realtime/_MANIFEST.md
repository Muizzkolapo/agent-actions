# Realtime Manifest

## Sub-Modules

| Sub-Module | Description |
|------------|-------------|
| [services](services/_MANIFEST.md) | Agent builder service modules. |

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `agent_builder.py` | Module | Agent builder module for dynamic LLM agent invocation. | `utilities` |
| `create_dynamic_agent` | Function | Build and execute a prompt against the selected vendor. | - |
| `agent_handlers.py` | Module | - | `errors`, `file_io` |
| `AgentManager` | Class | A class for managing agent directories and configurations. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `find_project_root` | Method | Find the project root directory by searching for a marker file. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `clean_agent_directories` | Method | Deletes all files under the source and target folders for the specified agent. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `clean_agent_output` | Method | Cleans the agent output by applying a specified function to each JSON file | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `agent_exists` | Method | Check if an agent exists. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_agent_paths` | Method | Construct and return key paths related to the agent. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `clean_directory` | Method | Clean a specific directory for an agent. | - |
| `cleaner.py` | Module | - | `errors`, `llm_invocation` |
| `Cleaner` | Class | Encapsulates the cleaning workflow for an agent. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `run` | Method | Run the cleaning workflow and surface meaningful ClickExceptions. | - |
| `config_handler.py` | Module | Module for Configuration Validation Functions. | `errors`, `prompt_generation`, `response_processing`, `state_management`, `utilities`, `validation` |
| `ConfigManager` | Class | - | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `load_configs` | Method | - | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `find_agent_name` | Method | Find the name of the agent from the configuration. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate_agent_name` | Method | - | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `check_child_pipeline` | Method | - | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_user_agents` | Method | - | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `merge_agent_configs` | Method | - | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `determine_execution_order` | Method | Determines the execution order of agents based on their dependencies, | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `load_environment_config` | Method | Load and validate environment configuration. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_agent_config` | Method | Get typed agent configuration by agent type. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_all_agent_configs` | Method | Get all typed agent configurations. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_all_agent_configs_as_dicts` | Method | Get all agent configurations as dictionaries for backward compatibility. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `create_workflow_config` | Method | Create a typed workflow configuration from dictionary data. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `create_pipeline_config` | Method | Create a typed pipeline configuration from dictionary data. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate_all_configs` | Method | Validate all loaded configurations. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_configuration_summary` | Method | Get a summary of all loaded configurations. | - |
| `DuplicateAgentError` | Class | Raised when duplicate agents are found in the configuration. | - |
| `output_handler.py` | Module | Module for handling output data saving operations. | `errors`, `file_io` |
| `OutputHandler` | Class | Responsible for saving output data to appropriate locations. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `save_main_output` | Method | Save main output data to the output directory. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `save_side_output` | Method | Save side output data to the side_output directory. | - |
