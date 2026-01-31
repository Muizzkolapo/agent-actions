# Cli Manifest

## Sub-Modules

| Sub-Module | Description |
|------------|-------------|
| [commands](commands/_MANIFEST.md) | CLI command implementations, including low-level runners and utilities. |
| [renderers](renderers/_MANIFEST.md) | CLI renderers for agent-actions. |
| [utils](utils/_MANIFEST.md) | - |

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `cli_decorators.py` | Module | CLI decorators for agent-actions commands. | `cli`, `shared` |
| `handles_user_errors` | Function | Decorator that standardizes error handling for CLI commands. | - |
| `requires_project` | Function | Decorator for CLI commands that require being in a project. | - |
| `compile.py` | Module | Render command for the Agent Actions CLI. | `cli`, `errors`, `prompt_generation`, `validation` |
| `RenderCommand` | Class | Implementation of the render command. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `execute` | Method | Execute the render command. | - |
| `render` | Function | Render Jinja2 templates in agent configuration files. | - |
| `docs.py` | Module | Documentation commands for agent-actions CLI. | `cli`, `docs` |
| `docs` | Function | Generate and serve workflow documentation. | - |
| `generate` | Function | Generate documentation data files. | - |
| `serve` | Function | Start HTTP server to view documentation. | - |
| `run_tests` | Function | Run Playwright tests to verify documentation site. | - |
| `dev` | Function | Start development environment. | - |
| `init.py` | Module | Initialize command for the Agent Actions CLI. | `cli`, `configuration`, `errors`, `validation` |
| `InitCommand` | Class | Implementation of the init command. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `execute` | Method | Execute the init command. | - |
| `init` | Function | Initialize a new Agent Actions project. | - |
| `inspect.py` | Module | Inspect commands for the Agent Actions CLI. | `cli`, `errors`, `orchestration`, `prompt_generation`, `response_processing`, `services`, `utilities`, `validation` |
| `BaseInspectCommand` | Class | Base class for inspect commands with common functionality. | - |
| `DependenciesCommand` | Class | Show dependency analysis in table format. | - |
| `GraphCommand` | Class | Show workflow structure as a visual dependency graph. | - |
| `ActionCommand` | Class | Show detailed information about a single action. | - |
| `ContextCommand` | Class | Show context debug information for a specific action. | - |
| `inspect` | Function | Inspect workflow structure and data flow (command group). | - |
| `dependencies` | Function | Analyze workflow dependencies and auto-inferred context. | - |
| `graph` | Function | Show workflow structure as a dependency graph. | - |
| `action` | Function | Show details for a specific action. | - |
| `context` | Function | Show context debug information for a specific action. | - |
| `list_udfs.py` | Module | list-udfs command for the Agent Actions CLI. | `cli`, `input_loading`, `utilities` |
| `ListUDFsCommand` | Class | Implementation of the list-udfs command. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `execute` | Method | Execute the list-udfs command. | - |
| `list_udfs_cmd` | Function | List all discovered User-Defined Functions (UDFs). | - |
| `main.py` | Module | Main entry point for the Agent Actions CLI. | `cli`, `errors`, `llm_invocation`, `logging`, `shared`, `utilities`, `validation` |
| `CLI` | Class | Agent Actions CLI application. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `execute` | Method | Execute the CLI application with the provided arguments. | - |
| `main_entrypoint` | Function | Main entry point for the CLI application. | - |
| `main` | Function | Entry point for the CLI tool when run from the command line. | - |
| `project_paths_factory.py` | Module | Project paths factory service. | `errors`, `file_io`, `state_management`, `utilities`, `validation` |
| `ProjectPaths` | Class | Container for project directory paths. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `to_dict` | Method | Convert paths to a dictionary of strings. | - |
| `ProjectPathsFactory` | Class | Factory for creating project paths. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_agent_paths` | Method | Get the agent paths using the FileHandler. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `create_project_paths` | Method | Create project paths for the given agent. | - |
| `project_root.py` | Module | Project root detection utilities. | `errors` |
| `find_project_root` | Function | Find the project root by walking up directories to locate agent_actions.yml. | - |
| `ensure_in_project` | Function | Ensure the current working directory is within an agent-actions project. | - |
| `get_project_root_or_cwd` | Function | Get project root if in a project, otherwise return current directory. | - |
| `is_in_project` | Function | Check if current directory is within an agent-actions project. | - |
| `run.py` | Module | Run command for the Agent Actions CLI. | `cli`, `docs`, `errors`, `orchestration`, `prompt_generation`, `validation` |
| `RunCommand` | Class | Implementation of the run command. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `execute_validation_only` | Method | Execute pre-flight validation only, without running the workflow. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `execute` | Method | Execute the run command. | - |
| `run` | Function | Run agents with a specified agent configuration. | - |
| `schema.py` | Module | Schema command for the Agent Actions CLI. | `cli`, `errors`, `orchestration`, `prompt_generation`, `response_processing`, `services`, `utilities` |
| `SchemaCommand` | Class | Implementation of the schema command. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `execute` | Method | Execute the schema command. | - |
| `schema` | Function | Display input and output schemas for all actions in a workflow. | - |
| `skills.py` | Module | Skills management CLI commands. | `cli` |
| `get_bundled_skills_path` | Function | Get the path to bundled skills in the package. | - |
| `get_target_path` | Function | Get the target path for skills based on tool choice. | - |
| `skills` | Function | Manage AI coding assistant skills (Claude Code / OpenAI Codex). | - |
| `install` | Function | Install bundled skills to your project. | - |
| `list_skills` | Function | List available bundled skills. | - |
| `status.py` | Module | Status command for the Agent Actions CLI. | `cli`, `validation` |
| `StatusCommand` | Class | Implementation of the status command. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `execute` | Method | Execute the status command. | - |
| `status` | Function | Display the status of an agent workflow. | - |
| `test.py` | Module | Clean command for the Agent Actions CLI. | `cli`, `llm_invocation`, `validation` |
| `clean_cli` | Function | CLI entrypoint for 'clean'. | - |
