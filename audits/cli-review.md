# Code Review: agent_actions/cli/

**Date:** 2026-06-17
**Reviewer:** Claude (4-angle parallel review + 1-vote verification)
**Files reviewed:** 25 Python files
**Verdict:** 14 CONFIRMED, 1 PLAUSIBLE, 2 REFUTED

---

## Findings (ranked by severity)

### 1. CONFIRMED — inspect_base._load_workflow diverges from workflow_loader.load_workflow

- **File:** `agent_actions/cli/inspect_base.py:46,50`
- **Summary:** `_load_workflow` omits `project_root` arg on `find_config_file` and omits `output_dir` (rendered_workflows_dir) on `render_and_load_config`. All 4 inspect subcommands see a structurally different workflow object than run/retry.
- **Failure scenario:** User runs `agac inspect graph` then `agac run`. Inspect resolves config from CWD instead of project root on fallback path. Inspect renders config in-memory only (no persisted rendered YAML), while run persists it. The two commands operate on different representations of the same workflow.
- **Severity:** HIGH — silent behavioral divergence between inspect and run

### 2. CONFIRMED — Execution summary render errors silently swallowed

- **File:** `agent_actions/cli/run.py:119`
- **Summary:** ExecutionRenderer wrapped in `except Exception` logged only at DEBUG level. If build_execution_snapshot raises (e.g., after partial initialization failure), user sees no post-run summary with no indication anything went wrong.
- **Failure scenario:** After a workflow run, `build_execution_snapshot` raises AttributeError due to services structure change. User sees clean exit, no summary table, no error — appears as if run completed cleanly.
- **Severity:** HIGH — silent fallback, merge-blocking anti-pattern

### 3. CONFIRMED — Retry runs invisible to RunTracker/docs history

- **File:** `agent_actions/cli/retry.py:222`
- **Summary:** `workflow.run()` called without attaching a RunTracker. Unlike RunCommand which wires up RunTracker, retry runs are completely invisible to docs history and `tracker.finalize_workflow_run` is never called.
- **Failure scenario:** User retries a failed workflow successfully. Docs server shows only the original failed run as the last entry. Run duration and outcome for the retry are never persisted.
- **Severity:** HIGH — data integrity gap in run history

### 4. CONFIRMED — init.py TOCTOU race in _create_project_directory

- **File:** `agent_actions/cli/init.py:226`
- **Summary:** `mkdtemp()` creates temp dir, immediately `rmtree()` deletes it, then `rename()` moves project into the deleted path. Between rmtree and rename, another process can occupy the path.
- **Failure scenario:** `agac init --force existing_project` in a directory with concurrent file indexing. Another process creates backup_dir between rmtree and rename. rename fails with FileExistsError, and the project has already been moved away — user left with no project at either location.
- **Severity:** MEDIUM — race condition, data loss risk

### 5. CONFIRMED — dispositions.py column header mismatch

- **File:** `agent_actions/cli/dispositions.py:95`
- **Summary:** Table column header says "Quarantined" but displays `counts.get("unprocessed", 0)`. These are different disposition states.
- **Failure scenario:** User runs `agac dispositions -a workflow`. The "Quarantined" column shows unprocessed count, not quarantined count. Records actually in quarantined state are misrepresented.
- **Severity:** MEDIUM — misleading CLI output

### 6. CONFIRMED — inspect_base._analyze_dependencies omits 'drop' from context_scope

- **File:** `agent_actions/cli/inspect_base.py:110`
- **Summary:** context_scope dict only includes 'observe' and 'passthrough' keys. The 'drop' key is omitted from `agac inspect action --json` output.
- **Failure scenario:** User runs `agac inspect action --json` to analyze dependencies. Drop rules are invisible in the output. Downstream tooling parsing the JSON misses active drop rules.
- **Severity:** MEDIUM — incomplete data in CLI output

### 7. CONFIRMED — init.py silent network error swallowing

- **File:** `agent_actions/cli/init.py:96`
- **Summary:** README fetch errors caught as `except (click.ClickException, IndexError): pass` in `_list_remote_examples`. Network failures produce empty descriptions with no warning.
- **Failure scenario:** User runs `agac example list` on intermittent connection. All examples show empty descriptions, no indication that fetching failed.
- **Severity:** MEDIUM — silent fallback

### 8. CONFIRMED — docs.py raises click.Abort instead of ClickException

- **File:** `agent_actions/cli/docs.py:50`
- **Summary:** On failure paths (no workflows found, serve_docs fails), raises `click.Abort()` which prints "Aborted!" instead of an actionable error message. Abort is for Ctrl-C, not application failures.
- **Failure scenario:** User runs `agac docs` in empty project. Sees "No workflows found to document." followed by "Aborted!" — inconsistent with all other commands that raise ClickException.
- **Severity:** MEDIUM — poor UX, inconsistent error handling

### 9. CONFIRMED — docs.py run_tests dead in user projects

- **File:** `agent_actions/cli/docs.py:58`
- **Summary:** `run_tests` expects Playwright .js test files in project root that are never distributed to user projects. Command immediately aborts for all real users.
- **Failure scenario:** User runs `agac docs test`, gets "Test files not found" and Aborted. Feature is discoverable via --help but non-functional outside framework development.
- **Severity:** MEDIUM — dead command in user-facing CLI

### 10. CONFIRMED — RunCommand uses click.echo while siblings use rich Console

- **File:** `agent_actions/cli/run.py:37`
- **Summary:** RunCommand uses `click.echo` throughout for status messages. All sibling commands (retry, status, dispositions, etc.) use rich Console. Inconsistent terminal output behavior.
- **Failure scenario:** On narrow terminals, rich-rendered output from ExecutionRenderer adapts to width while click.echo status lines do not. Piped output mixes rich formatting with raw click.echo lines.
- **Severity:** LOW — inconsistent output, no correctness impact

### 11. CONFIRMED — cli_decorators.py project root message pollutes JSON output

- **File:** `agent_actions/cli/cli_decorators.py:62`
- **Summary:** `click.echo('📁 Project root: ...', err=True)` emitted unconditionally, even in `--json` mode. Tools capturing stderr see non-JSON content.
- **Failure scenario:** CI script runs `agac inspect deps -a foo --json 2>&1 | jq '.'`. The project root line mixed into captured output causes jq to fail.
- **Severity:** LOW — pollutes stderr for machine consumers

### 12. CONFIRMED — Full AgentWorkflow constructed just to read execution_order

- **File:** `agent_actions/cli/dispositions.py:48`
- **Summary:** `load_workflow()` constructs full AgentWorkflow (storage backend, service graph) just to read `workflow.execution_order` — a static list from YAML config.
- **Failure scenario:** User runs `agac dispositions -a workflow` that has never been run (no SQLite DB). Storage init may log misleading errors for a command that only needs config.
- **Severity:** LOW — unnecessary overhead

### 13. CONFIRMED — example.py/init.py YAML injection block duplicated

- **File:** `agent_actions/cli/example.py:69` and `agent_actions/cli/init.py:422`
- **Summary:** project_name YAML injection block (yaml.safe_load, set key, yaml.safe_dump, exception handling) is character-for-character identical in both files. No shared helper.
- **Failure scenario:** Bug fix to injection logic in one file missed in the other. Two diverging code paths for the same operation.
- **Severity:** LOW — duplication maintenance risk

### 14. CONFIRMED — init.py downloads full repo tarball for single example

- **File:** `agent_actions/cli/init.py:113`
- **Summary:** `_fetch_example` downloads the entire repository tarball to extract one example subdirectory. On a misspelled name, a second full tarball request is also made.
- **Failure scenario:** User on slow connection runs `agac example install contract_reviewer`. Downloads entire repo (potentially tens of MB) for one small directory. Misspelled name doubles the wasted bandwidth.
- **Severity:** LOW — efficiency issue

### 15. CONFIRMED — schema_renderer dead public API

- **File:** `agent_actions/cli/renderers/schema_renderer.py:41`
- **Summary:** `render_flow_tree` and `render_action_detail` are public methods with zero external callers. `render_action_detail` has no callers anywhere.
- **Failure scenario:** Dead code accumulates drift. Method signatures and field assumptions diverge from the live schema without any test catching it.
- **Severity:** LOW — dead code

---

## PLAUSIBLE findings

### P1. Six command classes duplicate setup boilerplate

- **Files:** `status.py, run.py, retry.py, dispositions.py, schema.py, preview.py`
- **Summary:** Each independently does `Path(agent).stem`, `ProjectPathsFactory.create_project_paths()`, `Console()`. No shared base or factory.
- **Cost:** New parameter to ProjectPathsFactory requires updating 6 call sites independently.

---

## REFUTED

### R1. inspect.py backward-compat re-exports — REFUTED
- Actively used by main.py and tests. Not dead code.

### R2. compile.py alias duplication — REFUTED
- Two separate Click commands with identical options is the expected alias pattern, not duplication on a single command.

---

## Recommended fix priority

| Priority | Findings | Effort |
|----------|----------|--------|
| P0 (behavioral divergence) | #1 (inspect vs run workflow objects) | Medium — unify via workflow_loader |
| P0 (silent fallback) | #2 (execution summary swallowed) | Small — raise or log at warning |
| P0 (data integrity) | #3 (retry no RunTracker) | Medium — wire RunTracker into retry |
| P1 (data loss risk) | #4 (TOCTOU race) | Small — don't delete temp dir |
| P1 (wrong output) | #5 (column mismatch), #6 (missing drop) | Small — fix column/add drop key |
| P1 (silent fallback) | #7 (network swallowing) | Small — log warning on fetch failure |
| P2 (UX consistency) | #8, #9, #10, #11 (Abort/echo/JSON/dead cmd) | Small each |
| P3 (cleanup) | #12-#15 (overhead, duplication, dead code) | Varies |
