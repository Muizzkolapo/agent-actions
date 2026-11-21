# Cli Manifest

**[> Architecture Deep Dive (ARCHITECTURE.md)](ARCHITECTURE.md)** -- bootstrap flow, decorator stack, error propagation, command execution flows, caveats.

## Conventions

- **Read-only commands** (inspect, schema, status, preview, traces) must pass `auto_create=False` to `ProjectPathsFactory.create_project_paths()` and omit `output_dir` from `ConfigRenderingService().render_and_load_config()` to avoid filesystem mutations.
- **Write commands** (run, init, compile) use the defaults (`auto_create=True`, explicit `output_dir`).

## Sub-Modules

| Sub-Module | Description |
|------------|-------------|
| [renderers](renderers/_MANIFEST.md) | CLI renderers for agent-actions. |

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `cli_decorators.py` | Module | CLI decorators for agent-actions commands. `handles_user_errors` passes the command's arguments to the error output as context, except `action_name`: the action a user typed is not the action an error is about. Every command takes the workflow as `-w/--workflow` and `-a/--agent` alike (`workflow_option`), and an action as `-A/--action` wherever it takes one. | `cli`, `shared` |
| `workflow_option` | Function | The workflow option of a command: `-w/--workflow`, with `-a/--agent` as the same option. | - |
| `action_option` | Function | `-A/--action` for `traces`, `records` and `preview`, which read the action from `-a`: `-a` still names it there, with a deprecation warning on stderr. The option is eager, so the warning is printed before `--help` and before an error in any other option. | - |
| `handles_user_errors` | Function | Decorator that standardizes error handling for CLI commands. | - |
| `requires_project` | Function | Decorator for CLI commands that require being in a project. Injects `project_root: Path` kwarg instead of calling `os.chdir`. | - |
| `enter_project` | Function | The project check and banner `requires_project` applies, as a call: a group callback that Click runs before a subcommand's `--help` (`docs`) calls it only when the group itself runs. | - |
| `compile.py` | Module | Render command for the Agent Actions CLI. | `cli`, `errors`, `prompt_generation`, `validation` |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `execute` | Method | Execute the render command. | - |
| `render` | Function | Render Jinja2 templates in agent configuration files. | - |
| `compile` | Function | Alias for render — compile workflow configuration. | - |
| `dispositions.py` | Module | Inspect record-level processing dispositions per action. `--quarantined` lists failed, exhausted and unprocessed records (`QUARANTINED_DISPOSITIONS`), the last with the reason no answer reached them. The summary splits unprocessed rows into `Guard skipped` (reason in `record.reasons.GUARD_SKIP_REASONS`, the same set the collector counts for the run line) and `Unprocessed` (the rest); the columns still add up to `Total`. The summary, `--quarantined` and action-level tables are printed at their full width (`renderers.whole_table.print_whole`), wider than a narrow terminal if they have to be, so no count, record ID or action name is cut short. `Failed checks` counts `success` rows with reason `expectations_failed`, taken out of `Success`. `--json` prints `dispositions_report` and nothing else on stdout; the summary table is drawn from the same report, so the two cannot disagree. `--json` refuses `--quarantined`. A `filtered` row with reason `sent_elsewhere` is counted in a **Sent elsewhere** column, shown only when some action has one, and in neither **Filtered** nor **Total**; the report has it as each action's `sent_elsewhere`. | `cli`, `storage`, `validation` |
| `dispositions_report` | Function | `(backend, workflow, actions) -> dict`: for each action its `name`, `counts` (every key of `COUNT_KEYS`, 0 where none: the table's columns in snake_case, then `skipped` and `deferred`), `total` and `sent_elsewhere` (the records it sent to another branch, outside `counts` and `total`), `records` (None when the store cannot count them) and `action_level` (its `__node__` rows as `state`, `halted`, `reason`). The shape scripts read: keys are added, never renamed or removed. | - |
| `DispositionsCommand` | Class | Implementation of the dispositions command. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `execute` | Method | Execute the dispositions command. | - |
| `dispositions` | Function | Inspect record-level processing dispositions per action. | - |
| `docs.py` | Module | Documentation commands for agent-actions CLI. The `docs` group checks for a project (`enter_project`) only when it runs with no subcommand, so `agac docs test --help` works outside a project; `docs test` checks for itself. | `cli`, `docs` |
| `docs` | Function | Generate and serve workflow documentation. | - |
| `generate` | Function | Generate documentation data files. Accepts `project_root: Path \| None` (injected by `@requires_project`). | - |
| `serve` | Function | Start HTTP server to view documentation. Accepts `project_root: Path \| None` (injected by `@requires_project`). | - |
| `run_tests` | Function | Run Playwright tests to verify documentation site. Accepts `project_root: Path \| None` (injected by `@requires_project`). | - |
| `dev` | Function | Start development environment. | - |
| `example.py` | Module | Browse and install example projects. | `cli`, `configuration` |
| `example` | Function | Example command group. | - |
| `example_list` | Function | List available example projects from GitHub. | - |
| `example_install` | Function | Install an example project. | - |
| `expect.py` | Module | Inspect the expectation rules an action would run, and report the verdicts a run stored. The report heading names each `warn`/`info` rule that failed (failed/checked), since only `error` rules gate the records-passed rate; JSON is unchanged. The heading is printed as its own line above a title-less table (`soft_wrap`), because Rich wraps a table title at the table's width. The report's per-rule table is printed at its full width (`renderers.whole_table.print_whole`), so a rule id or type is not cut short on a narrow terminal. | `cli`, `expectations`, `storage`, `validation` |
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
| `inspect.py` | Module | Inspect command group for the Agent Actions CLI. The workflow view counts actions, not include entries, and marks each included action `from branch <name>` (`from branch <name> as <instance>` for an include with `as:`); a host action prints as before. The workflow list shows a router as `route on <field>: <case> → <entries> · ... · default → <entries or filter>` and a join as `join of <actions>` (from `_builtin`). A loop is one line, under its name: `loop ×<max_iterations> max, until <until> (branch <branch>, result <result>)`; its iteration actions are left out of the list and the count (`config.loops.loop_of`, `is_loop_pick`). | `cli` |
| `inspect` | Function | Inspect workflow structure and data flow (command group). | - |
| `inspect_base.py` | Module | Shared base class for all inspect subcommands. `branch_of` reads the branch name and branch file of an included action from its `_include` origin, and for an include with `as:` its `instance` and short-name map `names`; None for a host action. `observe_as_written` shows an optional observe reference with its `?` in the `context_scope` that `inspect action` and `inspect context` print. | `cli`, `orchestration`, `validation` |
| `BaseInspectCommand` | Class | Base class for inspect commands with common functionality. | - |
| `inspect_action.py` | Module | Action and context inspect subcommands. For an included action, `inspect action` shows a `Branch` row and `inspect context` a `Branch:` line with the branch and the branch file, and `--json` adds `branch: {name, file}`; a host action shows neither. For an include with `as:` the row reads `<branch> as <instance>`, `inspect action` adds a `Names` row (`write → c2__write, ...`) and the JSON adds `instance` and `names`. | `cli`, `orchestration`, `prompt_generation` |
| `ActionCommand` | Class | Show detailed information about a single action. | - |
| `action` | Function | Show details for a specific action. | - |
| `ContextCommand` | Class | Show context debug information for a specific action. | - |
| `context` | Function | Show context debug information for a specific action. | - |
| `list_udfs.py` | Module | list-udfs command for the Agent Actions CLI. | `cli`, `input_loading`, `utilities` |
| `ListUDFsCommand` | Class | Implementation of the list-udfs command. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `execute` | Method | Execute the list-udfs command. | - |
| `list_udfs_cmd` | Function | List all discovered User-Defined Functions (UDFs). | - |
| `args.py` | Module | Pydantic argument models for the CLI commands (run, retry, init, clean, status, batch). | `cli`, `validation` |
| `exit_codes.py` | Module | How `agac run` and `agac retry` end. The exit codes are named here and nowhere else: `EXIT_SUCCESS` 0, `EXIT_FAILED` 1, `EXIT_RECORD_FAILURES` 3, `EXIT_PAUSED` 4, `EXIT_QUOTA_STOP` 5. `EXIT_CODES` maps each `RunOutcome` to its code, and `TRACKER_STATUSES` to the status the run history keeps (`SUCCESS`, `PAUSED`, `FAILED`: the documentation site reads no other, so a run that finished with record failures is still stored `SUCCESS`, and a quota stop `PAUSED`). | `cli` |
| `RunOutcome` | Class | What the action statuses say once a run or a retry has stopped: `SUCCESS`, `RECORD_FAILURES`, `PAUSED_FOR_BATCH`, `PAUSED`, `FAILED`; and `QUOTA_STOP`, which no status stands for: the command sets it when the run raised `ProviderQuotaStop`. | - |
| `run_status` | Function | The status the run history keeps for a state manager's action statuses: `SUCCESS` when every action completed (with or without record failures) or is terminal with none failed, `FAILED` when every action is terminal and one failed, else `PAUSED`. | - |
| `classify_outcome` | Function | The `RunOutcome` of a workflow, `run_status` told apart further: `FAILED` when every action is terminal and one failed; `PAUSED_FOR_BATCH` when an action is not terminal and one is `batch_submitted`, `PAUSED` when none is; otherwise `RECORD_FAILURES` when an action is `completed_with_failures` (it holds a `failed` or `exhausted` record, `storage.backend.FAILURE_DISPOSITIONS`), else `SUCCESS`. | - |
| `actions_with_record_failures` | Function | The actions whose status is `completed_with_failures`, in execution order. | - |
| `report_quota_stop` | Function | Prints a `ProviderQuotaStop` on stderr unless the workflow that raised it has shown it (`_already_displayed`), so the stop is reported once. | - |
| `main.py` | Module | Main entry point for the Agent Actions CLI. A usage error is printed as Click words it (`format_message`), so a missing option is named by its flags: `Missing option '-w' / '--workflow' / '-a' / '--agent'.` | `cli`, `errors`, `llm_invocation`, `logging`, `shared`, `utilities`, `validation` |
| `CLI` | Class | Agent Actions CLI application. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `execute` | Method | Execute the CLI application with the provided arguments. | - |
| `main_entrypoint` | Function | Main entry point for the CLI application. | - |
| `main` | Function | Entry point for the CLI tool when run from the command line. | - |
| `run.py` | Module | Run command for the Agent Actions CLI. It holds the workflow's run lock (`storage.run_lock.hold_run_lock`) from right after the project paths are built to the end of the command, before `load_workflow` (which `--fresh` clears the store in) and the prompt check after it, so a second run is refused before it loads, clears or submits anything. `--record-limit` and `--file-limit` bound every action for the run — records per input file and input files per action — carried on the runtime config and stamped onto each action config so the per-action limit resolver reads them. `--rerun` may be given more than once; every action it names, and each action reading one, is answered again in the one run. It classifies the finished workflow with `exit_codes.classify_outcome`, prints the sentence for that outcome and exits with its code (0, 1, 3 or 4), never reading the code from the sentence. `--wait` (`RunCommand._wait_for_batches`) repeats the pass a second `agac run` makes while the outcome is `PAUSED_FOR_BATCH`, sleeping `--poll` seconds between passes through the `sleep` the command was built with, and stops at `--wait-timeout`, counted from before the first pass, with exit 4 and the time it waited; a `PAUSED` outcome with no open batch is not waited on and says so; `--poll` is a whole number of seconds, at least 1; the last sleep is cut to the time left, the printed wait is the time slept, and no pass starts once the timeout has passed; the later passes drop `--fresh`, `--rerun` and `--verify-keys`, and the run lock is held from the first pass to the last. A `ProviderQuotaStop` from any pass ends the command with exit 5 (`RunOutcome.QUOTA_STOP`); the run history records the pass `PAUSED` with the stop's message. | `cli`, `docs`, `errors`, `orchestration`, `prompt_generation`, `storage`, `validation` |
| `RunCommand` | Class | Implementation of the run command. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `execute_validation_only` | Method | Execute pre-flight validation only, without running the workflow. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `execute` | Method | Execute the run command. | - |
| `run` | Function | Run agents with a specified agent configuration. | - |
| `retry.py` | Module | Retry failed/exhausted records from a specific action forward. Unless `--dry-run`, it holds the workflow's run lock for the whole command, taken before the store is opened; `--filter` (`retry_filter.py`) takes it the same way. Its plan counts and lists records only: an action's `__node__` failure is shown on its own "Action status" line, not as a record. Below the plan it names each FILE tool in its range (`replaces_its_file_whole`): the retry hands such a tool every record of each file holding a listed record, and the actions in its range below it in the stored dependency graph (`repair_lineage.actions_below`, what the run clears by) answer again every record whose row the tool writes differently (`_note_file_tools`). Names the records it is re-running on the run, so a record limit admits them rather than cutting them loose and no file limit stops the walk before it reaches one. Classifies the finished workflow with the classifier `run.py` uses (`exit_codes.classify_outcome`) and exits with the same codes: 1 on a failed action, 3 while an action holds a failed or exhausted record, 4 when it submitted a batch, 5 when a provider's quota stopped its re-run (`ProviderQuotaStop`; its manifest stays, as after an interrupt, so the next retry resumes it). A failed action holding no failure row and owing no batch failed where the store could not record it: the retry writes the node-level failure it would have stored (reason: its status's `error_message`; a dry run writes nothing) and re-runs it in full. Refuses, before it clears anything, while an action in its range holds a batch nobody has collected: one still out, or one that finished and still holds a record nothing has answered (the repair clears the registry entry, which is all that names it). That is asked of the batch's records, read from its context map: one whose disposition is `deferred`, or which has none. `--abandon-in-flight` goes ahead and marks those records failed, so a later retry can still reach them. A record the batch holds without a `source_guid` is neither waited on nor marked: under its custom_id it would be a failure a later retry clears and cannot select. Refuses too, before the batch refusal, to narrow any action in the workflow (the run executes whatever is not complete, before its starting point as well) that holds no answer for some record — pending, running, interrupted, stopped while collecting, completed with its output gone, or failed by anything but reaching all of its input — since a plain run finishes it. A failure that reached all of its input (`EVERY_INPUT_FAILED`, or a batch action whose batches hold an answer or a failure for every record sent with a `source_guid`) is still refused while the action holds a row for a record that run did not reach (`target_row_identities` against its dispositions). Not refused: an action an interrupted retry put back to pending, which had finished before it — read from the `REPAIRED_BY` stamp that retry wrote beside the status, matched to its manifest's `created_at`, which a reset removes; an action holding an uncollected batch, and its readers, which the batch refusal decides; and a halt by `on_exhausted: raise` the retry does not clear, which stays halted. A halt it would clear is refused even then, naming a retry from the halted action: one starting at a halt without `--record` names no record and runs that action, and every one after it, in full (halts read from the failures it plans over, `_halted_among`). An interrupted retry's snapshot goes back only on the actions it stamped, and only while one of them has not completed or its manifest is a finished re-run's `put_back`; its starting action's record failures go back even where it completed, since the next retry starts from them, but a node-level failure never goes back on a completed action, which a plain run would run again over its readers. Before it looks for failures, it writes, at each completed action, the dispositions a collect pass stored rows for but left `deferred` because the store refused them (`managers.batch.lost_dispositions`), so a failure among them is found; nothing is submitted again, and a dry run plans over them unwritten. `--dry-run` restores nothing and keeps the manifest, planning over the snapshot as if restored. A retry that restores keeps the manifest and its notes until it writes its own, so one refused or finding nothing to do leaves the interrupted retry resumable. A `--from` below the interrupted retry's starting action, while an action it put back to pending has not completed, is refused before anything is restored (`_refused_below_a_stopped_retry`; a dry run reports it). After the re-run, a record the starting action never answered (`answered_by_repair`: found in a file processed to the end) and wrote nothing for gets back what was cleared for it at each action that did not decide it again, those actions are read again, and the record is named with a remedy that depends on whether it was in the input (`found_by_repair`), whether the action finished, and whether it was skipped below a halt the retry does not clear (then the retry from the halted action is named). Clears checkpoint rows only for the records whose dispositions it clears (`_clear_for_the_rerun`): a record keeping its `success` keeps the answer the row is, so a resume carries it and a `--rerun`'s replacement is answered again. Keeps what its re-run notes below each split it re-runs in `_retry_repair_notes.json` beside the manifest (`repair_lineage.keep_notes_at`), deleted with it; resuming an interrupted retry, it notes them again for the actions that retry put back to pending and never completed (`_not_run_since_an_interrupted_retry`), so their rows built on what the stopped retry's split replaced are taken out. | `cli`, `storage`, `validation`, `llm`, `processing` |
| `RetryCommand` | Class | Implementation of the retry command. `_retry` is one retry and returns the `RunOutcome` of its re-run, or None when it re-ran nothing; `execute` turns that into the exit code. With `--all`, `_retry_while_it_helps` calls `_retry` pass after pass under one run lock, prints the count of open failures after each (`_open_failures`: the set of (action, record) pairs `_find_failures` finds over the workflow's actions, node-level failures included), and stops when none is left, when a pass closed none of the pairs it planned over, when a pass left a set an earlier pass left, at `--max-passes`, or when a pass paused. A pass that repairs records at one action and sees them fail at the next has closed pairs, so the loop goes on. Its exit code is the code of the last pass's outcome, and 3 whenever a failure is still open. With `--dry-run` it makes one dry pass and prints the count. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `execute` | Method | Execute the retry command. | - |
| `retry` | Function | Retry failed/exhausted records from a specific action. With `--filter ACTION:RECORD_ID` (repeatable, needs `--reason`, refuses `--from`/`--record`/`--abandon-in-flight`) it hands off to `RetryFilterCommand` instead and re-runs nothing. `--all [--max-passes N]` repeats the retry while the count of open failures goes down; it refuses `--from`, `--record` and `--filter`, and `--max-passes` is refused without it. | - |
| `retry_filter.py` | Module | `agac retry --filter`: marks failed or exhausted records `filtered` at their action with the operator's reason (detail names the command and date), as a guard's `on_false: filter` leaves them, so no retry selects them and readers drop them ("filter is authoritative"). Validates every target before writing anything, reading what an interrupted retry's restore would put back as written (`_snapshot_to_restore`); refuses an unknown action, `__node__`, a record with no disposition there, or one not failed/exhausted. Rewrites a live `_retry_manifest.json` first (the target's row becomes the filtered one; its `unprocessed` rows below go), so a resume keeps the filter. Below the action (stored graph, transitively via `repair_lineage.actions_below`) it clears the record's `unprocessed` disposition, checkpoint rows and tombstones; the action itself keeps its tombstone, since carry-forward re-asks a carried record it holds no row for — and warns when there is no row (its file was never written). A `completed_with_failures` action left with no failed item reads `completed`. Unless `--dry-run`, it holds the workflow's run lock (`storage.run_lock.hold_run_lock`) for the whole command, taken before the store is opened, as `retry.py` does. | `cli`, `storage` |
| `RetryFilterCommand` | Class | Implementation of `agac retry --filter`. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `execute` | Method | Validate every target, then filter them and what their failure left below. | - |
| `workflow_loader.py` | Module | Shared workflow loading helper for CLI commands. An error raised while `load_workflow` renders the config carries the workflow name (`agent`), taken from the config file's stem. | `cli`, `validation` |
| `load_workflow` | Function | Load and validate a workflow configuration. It renders the workflow file once and hands the rendered text to `AgentWorkflow` (`WorkflowRuntimeConfig.rendered_workflow`), so the config pipeline does not render it again and each render warning prints once. | - |
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
| `status.py` | Module | Status command for the Agent Actions CLI. Shows each action's status from `.agent_status.json`, and an Error column (the first line of `error_message`, cut to 200 characters) when a failed action holds one. `--json` prints `status_report` and nothing else on stdout; the table is drawn from the same report. It reads the status file alone, not the workflow config. An action entry that is not an object, or a status that is not an `ActionStatus` value, is refused as a corrupted status file. | `cli`, `validation`, `orchestration` |
| `status_report` | Function | `(agent, project_root) -> dict`: `workflow`, `run_status` and, for each action the status file holds, `name`, `status` and `error` (a failed action's whole `error_message`). `run_status` is what `exit_codes.run_status` gives those statuses (`SUCCESS`, `FAILED`, `PAUSED`), so it is the status the run history keeps for a `run` or a `retry` that ends with them (their exit code tells more: `exit_codes.classify_outcome`); None when no status is stored. A stored status that is not an `ActionStatus`, or an action entry that is not an object, raises the same `ClickException` as a corrupted file. The shape scripts read: keys are added, never renamed or removed. | - |
| `StatusCommand` | Class | Implementation of the status command. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `execute` | Method | Execute the status command. | - |
| `status` | Function | Display the status of an agent workflow. | - |
| `clean.py` | Module | Clean command for the Agent Actions CLI. | `cli`, `llm_invocation`, `validation` |
| `clean_cli` | Function | CLI entrypoint for 'clean'. | - |
| `preview.py` | Module | Preview command for viewing SQLite storage data. Unwraps namespaced `content[action_name]` when displaying action output. | `cli`, `storage`, `validation` |
| `PreviewCommand` | Class | Implementation of the preview command. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `execute` | Method | Execute the preview command. | - |
| `preview` | Function | Preview data stored in the SQLite storage backend. | - |
| `traces.py` | Module | `agac traces`: prints an action's prompt traces (prompt, context, response) as plain text or JSON, through a read-only store; the store keeps that text compressed. | `cli`, `storage` |
| `traces` | Function | Print the prompt traces of an action. | - |
| `records.py` | Module | `agac records`: prints an action's stored records as JSON through a read-only store (each with `_action` and `_file`; `--source-guid`, `--file`, `--field` narrow them), or with `--snapshots` the input each failed or exhausted record was processed with; the store keeps these payloads compressed. | `cli`, `storage` |
| `records` | Function | Print the records an action stored. | - |

## Project Surface

| Symbol | File | Interaction | Config Key |
|--------|------|-------------|------------|
| `main_entrypoint()` | `.env` | Reads | — |
| `CLI._resolve_logging_base()` | `agent_actions.yml` | Reads at boot, once per command; a file that does not load is reported on stderr and the defaults stand | `logging` |
| `requires_project()` | `agent_actions.yml` | Reads | — |
| `ExpectListCommand.execute()` | `agent_config/{workflow}.yml` | Reads | — |
| `ExpectListCommand.execute()` | `schema/{workflow}/{action}.yml` | Reads | `schema` |
| `ExpectReportCommand.execute()` | `agent_io/store/` | Reads | — |
| `RunCommand.execute()` | `agent_config/{workflow}.yml` | Reads | — |
| `RunCommand.execute()` | `prompt_store/**/*.md`, `agent_workflow/*/prompt_store/**/*.md` | Validates the prompt files that `load_workflow` read, after it returns or raises | — |
| `RunCommand.execute()` | `agent_io/target/{action}/` | Writes | — |
| `RunCommand.execute()` | `agent_io/target/events.json` | Writes | — |
| `RunCommand.execute()` | `agent_io/target/run_results.json` | Writes | — |
| `RunCommand.execute()` | `.agac/batch_state/` | Deletes | `--fresh` |
| `RunCommand.execute()` | `agent_io/store/{workflow_name}.db` | Writes | `--rerun` (clears the named actions' and their readers' dispositions, checkpoints, traces and batch state; repeatable) |
| `RunCommand.execute()` | `tools/{workflow}/*.py` | Reads | `user_code` |
| `InitCommand.execute()` | `agent_actions.yml` | Writes | `project_name` |
| `SchemaCommand.execute()` | `agent_config/{workflow}.yml` | Reads | — |
| `SchemaCommand.execute()` | `schema/{workflow}/{action}.yml` | Reads | `schema_name` |
| `status_report()` | `agent_io/.agent_status.json` | Reads | — |
| `RetryCommand.execute()` | `agent_io/store/{workflow}/_retry_repair_notes.json` | Reads, Deletes | — |
| `RetryFilterCommand.execute()` | `agent_io/store/` | Reads, Writes (dispositions, target tombstones and checkpoint rows of the filtered records) | `--filter` |
| `RetryFilterCommand.execute()` | `agent_io/store/{workflow}/_retry_manifest.json` | Reads, Writes | `--filter` |
| `RetryFilterCommand.execute()` | `agent_io/.agent_status.json` | Writes (`completed_with_failures` → `completed`) | `--filter` |
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
| `workflow` | outbound | Invokes AgentWorkflow for run, inspect, and schema commands; `status` classifies stored statuses with the status sets of `managers.state` |
| `logging` | outbound | Initializes LoggerFactory and fires structured events |
| `validation` | outbound | Validates command arguments and project structure |
| `prompt` | outbound | Renders Jinja2 templates and validates prompt files |
| `models` | outbound | Uses ActionSchema for inspect and schema display |
| `errors` | outbound | Catches and formats AgentActionsError for CLI output |
| `storage` | outbound | Reads the SQLite backend for the preview, traces, records, dispositions and expect report commands; `retry --filter` writes dispositions and target rows through it |
| `llm` | outbound | Invokes Cleaner for clean command and batch CLI |
| `tooling` | outbound | Generates docs and tracks run results |
| `processing` | outbound | `retry` asks `answered_by_repair` and `found_by_repair` what its re-run reached; `expect` reads `bypasses_expectations` |
