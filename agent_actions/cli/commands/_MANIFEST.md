# Commands Manifest

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `clean.py` | Module | Clean command implementation that removes temporary agent work directories via `Cleaner`. | `cli`, `llm.realtime`, `validation` |
| `clean_cli` | Function | Click entrypoint for `agent-actions clean` that wires options into `CleanCommandArgs`. | `llm.realtime`, `validation` |
| `compile.py` | Module | Render command that renders agent YAML templates with Jinja2 and emits the result. | `cli`, `errors`, `prompt_generation`, `validation` |
| `RenderCommand` | Class | Encapsulates template rendering, path resolution, and logging for the render CLI command. | `prompt_generation` |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `_render_template` | Method | Render a template from the agent configuration while capturing diagnostics. | `prompt_generation`, `errors` |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `execute` | Method | Load the target agent config and print the rendered template. | `cli` |
| `render` | Function | Click command that validates arguments and delegates rendering to `RenderCommand`. | `validation` |
| `docs.py` | Module | Documentation command group for generating, serving, and testing workflow docs. | `cli`, `tooling.docs` |
| `docs` | Function | Click command group stub for `agent-actions docs`. | `tooling.docs` |
| `generate` | Function | Generate workflow documentation artefacts into a target directory. | `tooling.docs.generator` |
| `serve` | Function | Serve the documentation site over HTTP from the generated artefact. | `tooling.docs.server` |
| `run_tests` | Function | Run Playwright smoke tests against a running docs server. | `tooling.docs`, `subprocess` |
| `dev` | Function | Temporary placeholder for a docs development mode that explains current workflow. | `tooling.docs` |
| `init.py` | Module | Project initialization command that bootstraps a new Agent Actions project. | `cli`, `configuration`, `errors`, `logging`, `validation` |
| `InitCommand` | Class | Handles validation, directory creation, and template scaffolding for `agent-actions init`. | `configuration`, `validation`, `logging` |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `_validate_output_dir` | Method | Sanitize the output directory, preventing traversal and system paths. | `errors`, `validation` |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `_get_available_templates` | Method | Enumerate the supported project templates. | `configuration` |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `_create_project_directory` | Method | Create (or replace) the target project folder. | `errors`, `configuration` |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `_initialize_project` | Method | Delegate scaffolding to `ProjectInitializer`. | `configuration`, `errors` |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `execute` | Method | Run validation, directory creation, initialization, and logging events. | `logging`, `configuration`, `validation` |
| `init` | Function | Click command that builds `InitCommandArgs` and runs initialization. | `validation` |
| `inspect.py` | Module | Workflow inspection commands for analyzing dependencies and context. | `cli`, `errors`, `orchestration`, `prompt_generation`, `response_processing`, `services`, `utilities`, `validation` |
| `BaseInspectCommand` | Class | Shared helpers for loading workflows, configuration files, and console output. | `workflow.coordinator`, `cli`, `prompt_generation` |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `_find_config_file` | Method | Locate workflow YAML files and raise a `FileLoadError` if missing. | `errors` |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `_load_workflow` | Method | Render the workflow config and instantiate `AgentWorkflow`. | `prompt_generation`, `workflow.coordinator` |
| `DependenciesCommand` | Class | Analyzes action dependencies and context scope, then formats the output. | `workflow.coordinator`, `prompt.context`, `prompt.renderer` |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `execute` | Method | Load a workflow and emit dependency diagnostics in rich or JSON form. | `utils.rich`, `click` |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `_analyze_dependencies` | Method | Infer explicit and implicit dependencies per action. | `prompt.context` |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `_output_json` | Method | Serialize dependency info into JSON for programmatic use. | `json` |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `_output_rich` | Method | Format tables and panels with Rich for user-friendly display. | `rich` |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `_show_action_detail` | Method | Print an action-specific dependency tree with warnings. | `rich` |
| `dependencies` | Function | Click command that wires dependency options into `DependenciesCommand`. | `validation`, `cli` |
| `list_udfs.py` | Module | Lists discovered user-defined functions, supporting JSON or table output. | `cli`, `input_loading`, `utils.udf_management` |
| `ListUDFsCommand` | Class | Discovers and logs UDF metadata before presenting it to the CLI. | `input_loading`, `utils.udf_management` |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `execute` | Method | Discover UDFs, choose JSON vs table output, and render results. | `click`, `rich` |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `_output_json` | Method | Emit the discovered UDF metadata as formatted JSON. | `json` |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `_output_table` | Method | Render the UDF registry as a Rich table with optional details. | `rich` |
| `list_udfs_cmd` | Function | Click entrypoint for `agent-actions list-udfs`. | `validation` |
| `run.py` | Module | Workflow execution command with validation, tracking, and run management. | `cli`, `docs`, `errors`, `orchestration`, `prompt_generation`, `validation`, `workflow.coordinator`, `tooling.docs.run_tracker` |
| `RunCommand` | Class | Coordinates pre-flight validation, workflow execution, and run tracking. | `workflow.coordinator`, `validation`, `tooling.docs.run_tracker` |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `_find_config_file` | Method | Locate agent YAML files with fallback search hints. | `errors` |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `_determine_execution_mode` | Method | Decide between parallel, sequential, or auto execution paths. | `workflow.coordinator` |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `_run_workflow_execution` | Method | Launch the workflow in the requested concurrency mode. | `asyncio` |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `_setup_validation_workflow` | Method | Render configuration and instantiate workflow for validation-only runs. | `prompt_generation`, `workflow.coordinator` |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `_collect_issues_from_validator` | Method | Flatten validator issues into error and warning lists. | `validation` |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `_validate_vendors` | Method | Validate every agent config against vendor compatibility rules. | `validation` |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `_run_static_analysis` | Method | Run static type analysis over field references. | `validation` |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `_report_validation_results` | Method | Print a colored summary of pre-flight validation. | `click` |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `execute_validation_only` | Method | Run validator-only workflow that exits with status codes. | `validation` |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `execute` | Method | Execute the workflow, track runs, and finalize status. | `tooling.docs.run_tracker`, `workflow.coordinator` |
| `run` | Function | Click entrypoint for running workflows, toggling validation-only mode. | `validation`, `click` |
| `schema.py` | Module | Schema inspection command that summarizes inputs/outputs for each action. | `cli`, `errors`, `workflow.coordinator`, `WorkflowSchemaService` |
| `SchemaCommand` | Class | Loads workflow schemas, resolves UDF registry, and renders output. | `WorkflowSchemaService`, `output.response.loader`, `prompt.renderer` |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `_find_config_file` | Method | Ensure the requested YAML config exists. | `errors` |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `execute` | Method | Render schema tables or JSON using the service and renderer. | `SchemaRenderer` |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `_output_json` | Method | Serialize schema metadata for machine consumption. | `json`, `WorkflowSchemaService` |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `_output_rich` | Method | Use the unified renderer to print tables and panels. | `SchemaRenderer` |
| `schema` | Function | Click command to surface action schemas with optional verbosity. | `validation` |
| `skills.py` | Module | CLI helpers for managing bundled skills for Claude or Codex assistants. | `cli`, `project_root` |
| `get_bundled_skills_path` | Function | Resolve the path to packaged skills inside the CLI package. | `pathlib` |
| `get_target_path` | Function | Translate a tool choice into the appropriate `.claude`/`.codex` target. | `project_root` |
| `skills` | Function | Click command group for skill management. | `cli` |
| `install` | Function | Copy bundled skills into the requested tool directory, handling conflicts. | `shutil`, `project_root` |
| `list_skills` | Function | List available bundled skills with snippets from their `SKILL.md`. | `click`, `pathlib` |
| `status.py` | Module | Status command that reads workflow state from `.agent_status.json`. | `cli`, `validation` |
| `StatusCommand` | Class | Wraps status file loading and Rich table rendering. | `validation`, `project_paths_factory` |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `execute` | Method | Print a rich table with each agent's workflow status. | `rich` |
| `status` | Function | Click entrypoint that instantiates `StatusCommand`. | `validation` |
| `preview.py` | Module | Preview command for displaying data stored in the SQLite storage backend. | `cli`, `storage`, `validation` |
| `PreviewCommand` | Class | Implementation of the preview command with support for multiple output formats. | `storage`, `rich`, `project_paths_factory` |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `execute` | Method | Load data from storage backend and render in table/json/raw format. | `rich`, `storage` |
| `preview` | Function | Click entrypoint for `agent-actions preview` that shows stored workflow data. | `validation`, `cli` |
