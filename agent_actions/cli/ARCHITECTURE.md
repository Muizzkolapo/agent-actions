# CLI Module Architecture

This document maps the moving parts of `agent_actions/cli/` -- the Click-based command-line interface that bootstraps the framework, routes user commands, and renders output.

---

## High-Level Overview

```
                          agent_actions/cli/
                               │
            ┌──────────────────┼──────────────────┐
            │                  │                  │
        bootstrap          commands            renderers/
     (main.py,          (run, retry,        (execution_renderer,
      cli_decorators,    preview, schema,    schema_renderer)
      workflow_loader)   inspect, init, ...)
```

The module is a **Click group** (`agent-actions`) with 17 registered commands. Every command follows the same structural pattern:

1. A `@click.command()` function handles Click options/arguments
2. A companion `*Command` class (e.g., `RunCommand`, `RetryCommand`) holds the business logic in an `execute()` method
3. Two decorators -- `@handles_user_errors` and `@requires_project` -- wrap most commands

| Layer | What it does |
|-------|-------------|
| `main.py` | CLI bootstrap, Click group creation, logging init, signal handlers, top-level error catch |
| `cli_decorators.py` | `@handles_user_errors` (error formatting) + `@requires_project` (project root injection) |
| `workflow_loader.py` | Shared `load_workflow()` helper used by run, retry, schema, dispositions |
| `inspect_base.py` | `BaseInspectCommand` base class for all inspect subcommands |
| `renderers/` | Rich terminal output: `ExecutionRenderer` (post-run summary), `SchemaRenderer` (schema tables) |

---

## Bootstrap Flow

What happens when a user types `agac run -a my_workflow`:

```
main_entrypoint()                           ← entry point (pyproject.toml console_scripts)
  │
  ├─ find_project_root_dir()                ← walk up looking for agent_actions.yml
  ├─ load_dotenv(.env)                      ← load environment variables
  │
  └─ CLI()                                  ← instantiate Click application
       │
       ├─ fire_event(CLIInitStartEvent)     ← structured event
       ├─ _create_click_group()             ← @click.group with --debug/--verbose/--quiet
       ├─ _register_commands()              ← add_command() for all 17 commands
       ├─ _register_signal_handlers()       ← SIGINT, SIGTERM, SIGBREAK
       └─ fire_event(CLIInitCompleteEvent)
       │
       └─ execute(argv)
            │
            ├─ _configure_logging()         ← Phase 2: defaults before Click callback
            ├─ fire_event(CLIArgumentParsingEvent)
            │
            └─ click_group.main(argv)       ← Click dispatches to command
                 │
                 ├─ group callback           ← Phase 3: --debug/--verbose/--quiet override
                 │   └─ _configure_logging(debug=True)
                 │
                 └─ command function          ← e.g., run()
                      │
                      ├─ @requires_project   ← find + inject project_root
                      ├─ @handles_user_errors ← catch AgentActionsError → ClickException
                      │
                      └─ RunCommand.execute()
```

### Logging Initialization Order (3 Phases)

Logging is initialized multiple times because CLI flags are not available until Click parses them:

```
Phase 1: CLI() constructor
  └─ logging.getLogger(__name__)        ← bare Python logger, no config yet

Phase 2: CLI.execute() — before Click dispatch
  └─ _configure_logging()              ← LoggerFactory.initialize() with env defaults
     (LoggingConfig.from_environment() reads AGAC_LOG_LEVEL, AGAC_LOG_FORMAT, etc.)

Phase 3: Click group callback — after arg parsing
  └─ _configure_logging(debug=True)    ← re-initialize with --debug/--verbose/--quiet
     (force=True overwrites Phase 2)

Phase 4 (run command only): after workflow loads
  └─ LoggerFactory.initialize(output_dir=..., workflow_name=..., invocation_id=...)
     (adds file handler in agent_io/target/ for run logs)
```

Phase 1 events (CLIInitStartEvent) use a bare logger. If you add logging before Phase 2, messages may be lost or go to stderr with default formatting.

---

## Decorator Stack

Every command that operates on a project uses two decorators. **Order matters.**

```python
@click.command()
@click.option(...)
@handles_user_errors("run")      # ← outer: catches exceptions from everything below
@requires_project                 # ← inner: runs first, injects project_root
def run(..., project_root=None):
    ...
```

### Why order matters

Click decorators execute bottom-up. `@requires_project` runs first, calling `ensure_in_project()` to find the project root. If it fails with `ProjectNotFoundError`, the error propagates up through `@handles_user_errors`, which catches `AgentActionsError` subclasses and converts them to `click.ClickException` with formatted messages.

If you swap the order, `@handles_user_errors` would wrap the Click option processing but NOT the project root resolution, so `ProjectNotFoundError` would escape to the top-level catch in `CLI.execute()`.

```
Decorator application order (bottom-up):

  @handles_user_errors        ← applied last, wraps everything
    @requires_project          ← applied first, runs first at call time
      def command(...)

Call-time execution order (top-down):

  handles_user_errors wrapper
    └─ requires_project wrapper
         └─ command body
```

### `@handles_user_errors(command_name)`

- Catches `AgentActionsError` → formats via `format_user_error()` → raises `click.ClickException`
- Passes through `click.ClickException` unchanged (already formatted)
- Passes through unexpected `Exception` for the top-level catch in `CLI.execute()`
- Checks `_already_displayed` flag to avoid double-printing errors

### `@requires_project`

- Calls `ensure_in_project()` → walks up directories looking for `agent_actions.yml`
- Injects `project_root: Path` as a keyword argument into the wrapped function
- Prints the project root path to stderr for user feedback

---

## Read-Only vs Write Commands

Commands split into two categories based on whether they mutate the filesystem:

```
Write commands (auto_create=True, default):
  run          → creates agent_io/target/, writes output, logs
  compile      → renders Jinja2 templates to disk
  init         → creates entire project directory
  clean        → deletes target/staging directories
  retry        → clears dispositions, re-runs workflow

Read-only commands (auto_create=False):
  inspect *    → reads config, no side effects
  schema       → reads config + schema files
  preview      → reads SQLite database
  status       → reads .agent_status.json
  dispositions → reads disposition table
```

The split is enforced at two points:

1. **`ProjectPathsFactory.create_project_paths(auto_create=False)`** -- skips `mkdir()` calls for output directories
2. **`ConfigRenderingService().render_and_load_config()` without `output_dir`** -- skips writing rendered config to disk

Read-only commands must pass `auto_create=False` explicitly. Forgetting this means `agac schema -a foo` would create empty `agent_io/target/` directories as a side effect.

They must also pass `read_only=True` to `load_workflow()`. Forgetting *that* is
worse than a stray directory: `AgentWorkflow.__init__` otherwise resets every
retryable action to PENDING and clears its dispositions, so the command destroys
the state it was opened to read.

---

## `load_workflow()` Shared Helper

`workflow_loader.py` provides a single function used by `run`, `retry`, `schema`, and `dispositions`:

```
load_workflow(agent_name, paths, project_root, ...)
  │
  ├─ find_config_file()         ← resolve agent_config/{name}.yml (with alternatives)
  ├─ ConfigRenderingService()   ← render Jinja2 templates in the config
  │   .render_and_load_config()
  │
  └─ AgentWorkflow(             ← construct the workflow object
       WorkflowRuntimeConfig(
         paths=WorkflowPaths(...),
         use_tools=...,
         fresh=...,
         verify_keys=...,
         project_root=...,
       ),
       read_only=...,            ← suppresses the startup state reset
     )
```

| command | `read_only` | why |
|---------|-------------|-----|
| `run` | `False` | reset-before-execute is the intent |
| `schema`, `dispositions` | `True` | pure reads |
| `retry` | `True` | reads the disposition table *after* loading, then makes its own status transitions |

`retry` is the case that shows why this matters: it calls `_find_failures()`
after constructing the workflow, so with the reset in place it reported
"No failed records ... Nothing to retry" about rows its own constructor had
just deleted.

The inspect commands do NOT use this helper -- `BaseInspectCommand._load_workflow()` has its own copy of this logic because it omits `output_dir` from the rendering step and always sets `use_tools=False`.

---

## Command Execution Flows

### `run` -- Execute a Workflow

```
RunCommand.execute()
  │
  ├─ ProjectPathsFactory.create_project_paths()    ← auto_create=True (default)
  ├─ PromptValidator().validate()                   ← check prompt files exist
  ├─ load_workflow(... fresh=, verify_keys=)        ← load + validate config
  │
  ├─ RunTracker.start_workflow_run()                ← docs tracking (run_results.json)
  ├─ LoggerFactory.initialize(output_dir=...)       ← Phase 4 logging init
  │
  ├─ _determine_execution_mode()                    ← auto/parallel/sequential
  │   └─ should_use_parallel_execution()            ← checks dependency graph
  │
  ├─ workflow.run() or asyncio.run(workflow.async_run())
  │
  ├─ build_execution_snapshot() + ExecutionRenderer  ← post-run summary
  │   (wrapped in try/except -- failures are swallowed to logger.debug)
  │
  ├─ State check: is_workflow_complete / is_workflow_done / batch pending
  │
  └─ tracker.finalize_workflow_run()
     └─ LoggerFactory.flush()
```

### `retry` -- Retry Failed Records

```
RetryCommand.execute()
  │
  ├─ ProjectPathsFactory.create_project_paths(auto_create=False)
  ├─ get_storage_backend() + initialize()
  │
  ├─ Check for prior retry manifest (crash recovery)
  │   └─ If found: restore dispositions from snapshot → delete manifest
  │
  ├─ load_workflow()
  ├─ _find_failures()                               ← query FAILURE_DISPOSITIONS
  │
  ├─ Resolve from_action (explicit or earliest failure)
  ├─ _display_retry_plan()                          ← Rich table of what will be retried
  │
  ├─ (dry_run? → stop here)
  │
  ├─ Snapshot dispositions → _write_manifest()      ← crash-safe: written BEFORE clearing
  ├─ clear_disposition() per record per downstream action
  ├─ clear_disposition(NODE_LEVEL_RECORD_ID)        ← clear action-level FAILED/SKIPPED
  ├─ clear_checkpoint_records()                     ← clear stale partial output
  │
  ├─ Reset downstream ActionStatus → PENDING
  ├─ workflow.run()
  │
  └─ _delete_manifest()                             ← only after successful completion
```

### `inspect` -- Command Group

```
@click.group("inspect")
  ├─ action           ← ActionCommand (BaseInspectCommand)
  └─ context          ← ContextCommand (BaseInspectCommand)
```

All inherit from `BaseInspectCommand` which provides:
- `_load_inspector()` — read-only workflow load + preflight (`verify_keys=False`)
- `_analyze_dependencies()` for inferring data flow
- `_get_action_schema()`, `_get_output_fields()` helpers

### `preview` -- Read SQLite Storage

```
PreviewCommand.execute()
  │
  ├─ ProjectPathsFactory.create_project_paths(auto_create=False)
  ├─ Check db_path exists (agent_io/store/{name}.db)
  ├─ get_storage_backend(backend_type="sqlite")
  │
  ├─ stats_only? → _show_stats()
  ├─ action specified? → _preview_action()
  │   └─ _unwrap_records()    ← strip namespace: content[action_name] → content
  └─ no action? → _list_actions()
```

### `schema` -- Display Action Schemas

```
SchemaCommand.execute()
  │
  ├─ ProjectPathsFactory.create_project_paths(auto_create=False)
  ├─ load_workflow()
  ├─ WorkflowSchemaService.build_workflow_config()
  ├─ WorkflowSchemaService(...).get_all_schemas()
  │
  ├─ json_output? → click.echo(json.dumps(...))
  └─ rich output? → SchemaRenderer.render_summary_table()
                    SchemaRenderer.render_data_flow_panel() (if --verbose)
```

### `init` -- Create a New Project

```
init (Click group with _InitGroup routing)
  │
  ├─ new     → InitCommand.execute()
  │   ├─ ProjectValidator.validate()
  │   ├─ _create_project_directory() (with backup/rollback on failure)
  │   └─ ProjectInitializer.init_project()
  │
  ├─ list    → _list_remote_examples() (GitHub API)
  │
  └─ example → _fetch_example() (download tarball, extract, inject project_name)
```

Note: `init` does NOT use `@requires_project` since it creates the project. It only uses `@handles_user_errors`.

---

## Error Propagation Model

Errors flow through three layers, each catching progressively broader exception types:

```
Layer 1: @handles_user_errors (per-command)
  │  Catches: AgentActionsError → click.ClickException
  │  Passes: click.ClickException, unexpected Exception
  │
Layer 2: CLI.execute() (application-level)
  │  Catches:
  │    click.Abort → exit 130
  │    click.UsageError → "Error: ..." to stderr, exit 2
  │    click.ClickException → formatted message, exit 1
  │    ProjectNotFoundError → special multi-line message with solutions
  │    Exception (catch-all) → format_user_error() + optional --debug traceback
  │
Layer 3: main_entrypoint() / main()
     sys.exit(return_code)
```

Key design decisions:
- `AgentActionsError` (application errors) are formatted prettily at Layer 1
- `ProjectNotFoundError` gets special treatment at Layer 2 with a multi-line message showing the search path and suggesting solutions
- Unexpected exceptions (bugs) escape Layer 1 and are caught at Layer 2 with `format_user_error()` -- raw tracebacks only appear with `--debug`
- `_already_displayed` flag on exceptions prevents double-printing when errors have already been shown to the user

---

## Inspect Command Group Architecture

`inspect` is a Click group with two subcommands plus the default form,
all sharing a base class:

```
BaseInspectCommand
  │
  │  Fields: agent, agent_name, user_code, json_output, console
  │  Fields set by _load_inspector(): paths, schema_service
  │
  │  _load_inspector(project_root)     ← read-only, verify_keys=False
  │  _analyze_dependencies(inspector)  ← infer_dependencies() per action
  │  _get_action_schema(name)          ← via schema_service
  │  _get_output_fields(config)        ← schema properties → field names
  │  _get_action_type(inputs, ctx)     ← Source/Transform/Merge classification
  │
  ├── InspectCommand        ← default: flat validated action list
  ├── ActionCommand         ← detailed view of a single action
  └── ContextCommand        ← template-variable namespaces
```

All subcommands use `@handles_user_errors` and `@requires_project`. Each implements its own `execute()` that calls `self._load_inspector()` from the base class.

---

## Renderers Sub-Module

```
renderers/
  ├─ __init__.py              ← exports SchemaRenderer
  ├─ execution_renderer.py    ← post-run workflow summary
  └─ schema_renderer.py       ← schema display tables
```

### ExecutionRenderer

Renders a structured post-run summary with execution levels, status icons, kind badges, provider info, and latency. Used only by `RunCommand`.

```
build_execution_snapshot(workflow, elapsed)    ← reads action_configs + state_manager
  └─ WorkflowExecutionSnapshot                ← frozen dataclass

ExecutionRenderer(console).render(snapshot)
  ├─ _render_header()      ← workflow name, version, action/vendor counts
  ├─ _render_levels()      ← per-level: sequential or parallel box
  │   ├─ _render_sequential_action()   ← "├─ ✓ action_name  llm  openai  1.2s"
  │   └─ _render_parallel_level()      ← boxed group of concurrent actions
  └─ _render_footer()      ← "✓ Done in 5.2s (3 completed, 1 skipped)"
```

### SchemaRenderer

Renders schema summary tables and data flow panels for the `schema` command. Imported from `renderers/__init__.py`.

---

## File Index

### Bootstrap

| File | Role |
|------|------|
| `main.py` | CLI entry point, Click group, logging init, signal handlers, top-level error handling, `_LazyCLI` proxy |
| `cli_decorators.py` | `@handles_user_errors` + `@requires_project` decorators |
| `workflow_loader.py` | `load_workflow()` shared helper + `validate_action_exists()` |

### Shared / Base

| File | Role |
|------|------|
| `inspect_base.py` | `BaseInspectCommand` base class for all inspect subcommands |
| `inspect.py` | Click group for `inspect` + subcommand registration |

### Write Commands (mutate filesystem)

| File | Role |
|------|------|
| `run.py` | `RunCommand` -- full workflow execution with tracking + parallel/sequential modes |
| `retry.py` | `RetryCommand` -- retry failed records with crash-safe manifest |
| `compile.py` | `RenderCommand` -- render Jinja2 templates in agent config |
| `init.py` | `InitCommand` -- project scaffolding + GitHub example fetching |
| `clean.py` | `clean_cli` -- delete target/staging/store directories |

### Read Commands (no side effects)

| File | Role |
|------|------|
| `preview.py` | `PreviewCommand` -- SQLite data viewer with table/json/raw formats |
| `schema.py` | `SchemaCommand` -- display input/output schemas per action |
| `status.py` | `StatusCommand` -- read `.agent_status.json` |
| `dispositions.py` | `DispositionsCommand` -- per-action disposition breakdown |
| `inspect_action.py` | `ActionCommand` + `ContextCommand` -- action detail + context debug |

### Utility

| File | Role |
|------|------|
| `list_udfs.py` | `ListUDFsCommand` -- discover and list UDF scripts |
| `docs.py` | Documentation generation + dev server |
| `example.py` | Browse and install example projects |
| `skills.py` | Install AI coding assistant skills (Claude Code, Codex) |

### Renderers

| File | Role |
|------|------|
| `renderers/__init__.py` | Exports `SchemaRenderer` |
| `renderers/execution_renderer.py` | `ExecutionRenderer` + `build_execution_snapshot()` -- post-run visual summary |
| `renderers/schema_renderer.py` | `SchemaRenderer` -- schema tables and data flow panels |

---

## Caveats

1. **`auto_create=False` is not the default.** `ProjectPathsFactory.create_project_paths()` defaults to `auto_create=True`. Every read-only command must pass `auto_create=False` explicitly, or it will create empty `agent_io/target/` directories as a side effect of being run.

2. **Decorator order matters.** `@handles_user_errors` must be the outer decorator (listed first/above `@requires_project` in source). Swapping them means `ProjectNotFoundError` from `@requires_project` escapes the error formatter and falls through to `CLI.execute()`'s catch-all, which produces a different (less informative for some error types) message.

3. **`project_root` injection.** `@requires_project` injects `project_root` as a keyword argument. The wrapped function's signature must accept `project_root: Path | None = None` or the call will fail with a `TypeError`. Commands that do not need project root (like `init new`) must not use `@requires_project`.

4. **Retry manifest crash safety.** `RetryCommand` writes a manifest of snapshotted dispositions BEFORE clearing them from the database. If the process crashes between clearing and re-run completion, the next `retry` invocation detects the manifest, restores the dispositions, deletes the manifest, and proceeds. The manifest is only deleted on successful completion.

5. **`NODE_LEVEL_RECORD_ID` clearing.** During retry, in addition to clearing per-record dispositions, the code clears `NODE_LEVEL_RECORD_ID` -- a synthetic record ID used for action-level status. Without this, the executor would see a stale action-level FAILED signal and skip the action entirely.

6. **Checkpoint clearing on retry.** `backend.clear_checkpoint_records(action)` is called for each downstream action during retry. Without this, stale partial output from a prior interrupted run would be carried forward instead of reprocessing the records.

7. **`ExecutionRenderer` failures are swallowed.** The post-run summary render in `RunCommand._execute_single()` is wrapped in a bare `try/except` that logs to `logger.debug`. If the renderer crashes (e.g., accessing state that was cleaned up), the user never sees the summary but the run still succeeds. This is intentional -- the summary is informational, not functional.

8. **Logging is initialized 3-4 times.** See "Logging Initialization Order" above. Each call to `LoggerFactory.initialize(force=True)` replaces the previous configuration. Events fired before Phase 2 use a bare logger. The Phase 4 init (run command only) adds a file handler after the workflow is loaded, so early log messages are not written to the run log file.

9. **`_LazyCLI` proxy.** `main.py` exports a module-level `cli` object that defers `CLI()` instantiation until first access. This exists so that tools importing the module (e.g., for testing or documentation) don't trigger the full bootstrap (signal handlers, event firing) on import.

10. **`BaseInspectCommand._load_workflow()` duplicates `load_workflow()`.** The inspect base class has its own workflow loading logic instead of calling the shared `workflow_loader.load_workflow()`. This is because inspect commands omit `output_dir` from `ConfigRenderingService().render_and_load_config()` and always set `use_tools=False`. The duplication is intentional but means changes to config loading must be applied in both places.

11. **`init` uses `_InitGroup` for implicit routing.** `agac init my_project` works because `_InitGroup.resolve_command()` detects that `my_project` is not a known subcommand and routes it to the `new` subcommand. This means you cannot name a project `list`, `new`, or `example` without using the explicit `agac init new list` form.

12. **Preview unwraps namespaced content.** Records in storage use the additive model where `content` is `{"action_a": {...}, "action_b": {...}}`. `PreviewCommand._unwrap_records()` strips this namespace when previewing a specific action so the table shows flat fields. Guard-skipped actions have `content[action] = None`, which is replaced with `{}` rather than showing a sentinel.

13. **`retry` uses `auto_create=False` despite being a write command.** Even though retry re-runs the workflow (which writes output), the `ProjectPathsFactory` call uses `auto_create=False` because the directories must already exist from a prior run. The actual directory creation happens inside the workflow engine during re-execution.

14. **Signal handler registration can fail silently.** `_register_signal_handlers()` catches `AttributeError` and `ValueError` (e.g., when running in a non-main thread or certain embedded environments) and logs a warning instead of crashing. This means SIGINT handling may not work in all contexts.

15. **`--debug` flag detection in catch-all.** The top-level `Exception` handler in `CLI.execute()` checks for `"--debug" in argv` to decide whether to print the full traceback. This is a string match against raw argv, not a Click-parsed flag, because the exception may have occurred before Click finished parsing.
