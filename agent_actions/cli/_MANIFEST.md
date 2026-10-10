# Cli Manifest

**[> Architecture Deep Dive (ARCHITECTURE.md)](ARCHITECTURE.md)** -- bootstrap flow, decorator stack, error propagation, command execution flows, caveats.

## Conventions

- **Read-only commands** (inspect, schema, status, preview) must pass `auto_create=False` to `ProjectPathsFactory.create_project_paths()` and omit `output_dir` from `ConfigRenderingService().render_and_load_config()` to avoid filesystem mutations.
- **Write commands** (run, init, compile) use the defaults (`auto_create=True`, explicit `output_dir`).

## Sub-Modules

| Sub-Module | Description |
|------------|-------------|
| [renderers](renderers/_MANIFEST.md) | CLI renderers for agent-actions. |

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `cli_decorators.py` | Module | CLI decorators for agent-actions commands. | `cli`, `shared` |
| `handles_user_errors` | Function | Decorator that standardizes error handling for CLI commands. | - |
| `requires_project` | Function | Decorator for CLI commands that require being in a project. Injects `project_root: Path` kwarg instead of calling `os.chdir`. | - |
| `compile.py` | Module | Render command for the Agent Actions CLI. | `cli`, `errors`, `prompt_generation`, `validation` |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `execute` | Method | Execute the render command. | - |
| `render` | Function | Render Jinja2 templates in agent configuration files. | - |
| `compile` | Function | Alias for render — compile workflow configuration. | - |
| `dispositions.py` | Module | Inspect record-level processing dispositions per action. | `cli`, `storage`, `validation` |
| `DispositionsCommand` | Class | Implementation of the dispositions command. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `execute` | Method | Execute the dispositions command. | - |
| `dispositions` | Function | Inspect record-level processing dispositions per action. | - |
| `docs.py` | Module | Documentation commands for agent-actions CLI. | `cli`, `docs` |
| `docs` | Function | Generate and serve workflow documentation. | - |
| `generate` | Function | Generate documentation data files. Accepts `project_root: Path \| None` (injected by `@requires_project`). | - |
| `serve` | Function | Start HTTP server to view documentation. Accepts `project_root: Path \| None` (injected by `@requires_project`). | - |
| `run_tests` | Function | Run Playwright tests to verify documentation site. Accepts `project_root: Path \| None` (injected by `@requires_project`). | - |
| `dev` | Function | Start development environment. | - |
| `example.py` | Module | Browse and install example projects. | `cli`, `configuration` |
| `example` | Function | Example command group. | - |
| `example_list` | Function | List available example projects from GitHub. | - |
| `example_install` | Function | Install an example project. | - |
| `expect.py` | Module | Inspect the expectation rules an action would run, and report the verdicts a run stored. | `cli`, `expectations`, `storage`, `validation` |
| `ExpectListCommand` | Class | Implementation of the expect list command. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `execute` | Method | Resolve each action's suite through the runner's own loader and print it. | - |
| `expect` | Function | Expect command group. | - |
| `list_rules` | Function | List the rules each action would run, as a table or JSON. Marks an action whose strategy never evaluates expectations, so inert rules are shown without being claimed to execute. | - |
| `ExpectReportCommand` | Class | Implementation of the expect report command. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `execute` | Method | Aggregate the verdicts stored for each action and render or emit them. | - |
| `report` | Function | Report stored expectation verdicts, as a table or JSON; `--fail-under` rates each action separately and exits non-zero when any falls short, or when no verdict was stored at all. | - |
| `init.py` | Module | Initialize command for the Agent Actions CLI. | `cli`, `configuration`, `errors`, `validation` |
| `InitCommand` | Class | Implementation of the init command. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `execute` | Method | Execute the init command. | - |
| `init` | Function | Initialize a new Agent Actions project. | - |
| `inspect.py` | Module | Inspect command group for the Agent Actions CLI. | `cli` |
| `inspect` | Function | Inspect workflow structure and data flow (command group). | - |
| `inspect_base.py` | Module | Shared base class for all inspect subcommands. | `cli`, `orchestration`, `validation` |
| `BaseInspectCommand` | Class | Base class for inspect commands with common functionality. | - |
| `inspect_action.py` | Module | Action and context inspect subcommands. | `cli`, `orchestration`, `prompt_generation` |
| `ActionCommand` | Class | Show detailed information about a single action. | - |
| `action` | Function | Show details for a specific action. | - |
| `ContextCommand` | Class | Show context debug information for a specific action. | - |
| `context` | Function | Show context debug information for a specific action. | - |
| `list_udfs.py` | Module | list-udfs command for the Agent Actions CLI. | `cli`, `input_loading`, `utilities` |
| `ListUDFsCommand` | Class | Implementation of the list-udfs command. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `execute` | Method | Execute the list-udfs command. | - |
| `list_udfs_cmd` | Function | List all discovered User-Defined Functions (UDFs). | - |
| `args.py` | Module | Pydantic argument models for the CLI commands (run, retry, init, clean, status, batch). | `cli`, `validation` |
| `main.py` | Module | Main entry point for the Agent Actions CLI. | `cli`, `errors`, `llm_invocation`, `logging`, `shared`, `utilities`, `validation` |
| `CLI` | Class | Agent Actions CLI application. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `execute` | Method | Execute the CLI application with the provided arguments. | - |
| `main_entrypoint` | Function | Main entry point for the CLI application. | - |
| `main` | Function | Entry point for the CLI tool when run from the command line. | - |
| `run.py` | Module | Run command for the Agent Actions CLI. `--record-limit` and `--file-limit` bound every action for the run — records per input file and input files per action — carried on the runtime config and stamped onto each action config so the per-action limit resolver reads them. | `cli`, `docs`, `errors`, `orchestration`, `prompt_generation`, `validation` |
| `RunCommand` | Class | Implementation of the run command. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `execute_validation_only` | Method | Execute pre-flight validation only, without running the workflow. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `execute` | Method | Execute the run command. | - |
| `run` | Function | Run agents with a specified agent configuration. | - |
| `retry.py` | Module | Retry failed/exhausted records from a specific action forward. Names the records it is re-running on the run, so a record limit admits them rather than cutting them loose and no file limit stops the walk before it reaches one. Classifies the finished workflow the way `run.py` does and exits 1 on a failed action. Refuses, before it clears anything, while an action in its range holds a batch nobody has collected: one still out, or one that finished and still holds a record nothing has answered (the repair clears the registry entry, which is all that names it). That is asked of the batch's records, read from its context map: one whose disposition is `deferred`, or which has none. `--abandon-in-flight` goes ahead and marks those records failed, so a later retry can still reach them. A record the batch holds without a `source_guid` is neither waited on nor marked: under its custom_id it would be a failure a later retry clears and cannot select. Refuses too, before the batch refusal, to narrow any action in the workflow (the run executes whatever is not complete, before its starting point as well) that holds no answer for some record — pending, running, interrupted, stopped while collecting, completed with its output gone, or failed by anything but reaching all of its input — since a plain run finishes it. A failure that reached all of its input (`EVERY_INPUT_FAILED`, or a batch action whose batches hold an answer or a failure for every record sent with a `source_guid`) is still refused while the action holds a row for a record that run did not reach (`target_row_identities` against its dispositions). Not refused: an action an interrupted retry put back to pending, which had finished before it — read from the `REPAIRED_BY` stamp that retry wrote beside the status, matched to its manifest's `created_at`, which a reset removes; an action holding an uncollected batch, and its readers, which the batch refusal decides; and one halted by `on_exhausted: raise`, which a plain run will not resume (#1267). An interrupted retry's snapshot goes back only on the actions it stamped, and only while one of them has not completed or its manifest is a finished re-run's `put_back`; its starting action's record failures go back even where it completed, since the next retry starts from them, but a node-level failure never goes back on a completed action, which a plain run would run again over its readers. `--dry-run` restores nothing and keeps the manifest, planning over the snapshot as if restored. After the re-run, a record the starting action never answered (`answered_by_repair`: found in a file processed to the end) and wrote nothing for gets back what was cleared for it at each action that did not decide it again, those actions are read again, and the record is named with a remedy that depends on whether it was in the input (`found_by_repair`) and whether the action finished. | `cli`, `storage`, `validation`, `llm`, `processing` |
| `RetryCommand` | Class | Implementation of the retry command. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `execute` | Method | Execute the retry command. | - |
| `retry` | Function | Retry failed/exhausted records from a specific action. | - |
| `workflow_loader.py` | Module | Shared workflow loading helper for CLI commands. | `cli`, `validation` |
| `load_workflow` | Function | Load and validate a workflow configuration. | - |
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
| `clean.py` | Module | Clean command for the Agent Actions CLI. | `cli`, `llm_invocation`, `validation` |
| `clean_cli` | Function | CLI entrypoint for 'clean'. | - |
| `preview.py` | Module | Preview command for viewing SQLite storage data. Unwraps namespaced `content[action_name]` when displaying action output. | `cli`, `storage`, `validation` |
| `PreviewCommand` | Class | Implementation of the preview command. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `execute` | Method | Execute the preview command. | - |
| `preview` | Function | Preview data stored in the SQLite storage backend. | - |

## Project Surface

| Symbol | File | Interaction | Config Key |
|--------|------|-------------|------------|
| `main_entrypoint()` | `.env` | Reads | — |
| `requires_project()` | `agent_actions.yml` | Reads | — |
| `ExpectListCommand.execute()` | `agent_config/{workflow}.yml` | Reads | — |
| `ExpectListCommand.execute()` | `schema/{workflow}/{action}.yml` | Reads | `schema` |
| `ExpectReportCommand.execute()` | `agent_io/store/` | Reads | — |
| `RunCommand.execute()` | `agent_config/{workflow}.yml` | Reads | — |
| `RunCommand.execute()` | `prompt_store/{workflow}.md` | Validates | — |
| `RunCommand.execute()` | `agent_io/target/{action}/` | Writes | — |
| `RunCommand.execute()` | `agent_io/target/events.json` | Writes | — |
| `RunCommand.execute()` | `agent_io/target/run_results.json` | Writes | — |
| `RunCommand.execute()` | `.agac/batch_state/` | Deletes | `--fresh` |
| `RunCommand.execute()` | `tools/{workflow}/*.py` | Reads | `user_code` |
| `InitCommand.execute()` | `agent_actions.yml` | Writes | `project_name` |
| `SchemaCommand.execute()` | `agent_config/{workflow}.yml` | Reads | — |
| `SchemaCommand.execute()` | `schema/{workflow}/{action}.yml` | Reads | `schema_name` |
| `StatusCommand.execute()` | `agent_io/staging/` | Reads | — |
| `ListUDFsCommand.execute()` | `tools/{workflow}/*.py` | Reads | — |
| `PreviewCommand.execute()` | `agent_io/target/{action}/` | Reads | — |
| `BaseInspectCommand._load_inspector()` | `agent_config/{workflow}.yml` | Reads | — |
| `clean_cli()` | `agent_io/source/` | Writes | — |
| `clean_cli()` | `agent_io/staging/` | Writes | — |
| `clean_cli()` | `agent_io/target/{action}/` | Writes | — |
| `clean_cli()` | `.agac/batch_state/` | Deletes | `--all` |

## Dependencies

| Package | Direction | Why |
|---------|-----------|-----|
| `config` | outbound | Reads project paths, config files, and project root resolution |
| `workflow` | outbound | Invokes AgentWorkflow for run, inspect, and schema commands |
| `logging` | outbound | Initializes LoggerFactory and fires structured events |
| `validation` | outbound | Validates command arguments and project structure |
| `prompt` | outbound | Renders Jinja2 templates and validates prompt files |
| `models` | outbound | Uses ActionSchema for inspect and schema display |
| `errors` | outbound | Catches and formats AgentActionsError for CLI output |
| `storage` | outbound | Reads the SQLite backend for the preview, dispositions and expect report commands |
| `llm` | outbound | Invokes Cleaner for clean command and batch CLI |
| `tooling` | outbound | Generates docs and tracks run results |
| `processing` | outbound | `retry` asks `answered_by_repair` and `found_by_repair` what its re-run reached; `expect` reads `bypasses_expectations` |
