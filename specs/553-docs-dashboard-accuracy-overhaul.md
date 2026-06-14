# Docs Dashboard Accuracy Overhaul

**Status**: ready
**Priority**: HIGH
**Source**: Visual audit of `agac docs` dashboard against qanalabs-quiz-maker project

## Problem

The docs dashboard shows a **configuration-time** view of the project, not an **operational** view. It reads YAML configs statically but ignores runtime artifacts (manifest, run results, DB, event logs). The result: every data point that depends on runtime state is wrong or missing.

Audited against `qanalabs-quiz-maker` (2 workflows, 43 YAML actions → 52 runtime actions with version expansion, completed runs, 3.7MB DB).

## Discrepancies Found

### P0 — Data is wrong

| What | Dashboard shows | Reality | Root cause |
|------|----------------|---------|------------|
| **Action count** | 43 per workflow | 52 per workflow | Parser reads YAML (43 actions), doesn't expand `versions: {range: [1,2,3]}` into concrete actions. Manifest has 52. |
| **Workflow status** | "paused" | "completed" | Parser doesn't read `.manifest.json`. Status is hardcoded to "paused" when manifest is absent. |
| **Levels/stages** | "0 stages" | 36 levels | Same — manifest not read. Levels come from manifest, not YAML. |
| **Runs** | 0 | 4+ run results, 100 executions in prior catalog | `scan_runs()` looks in `agent_io/logs/` but `run_results.json` is in `agent_io/target/` (or `agent_io_changed/target/` for this project). Falls back silently. |
| **Logs/errors** | 0 errors, 0 warnings | events.json exists with data | Scanner may not be finding event files in the right location after the logs migration (spec 542 moved files to `agent_io/logs/`). |

### P1 — Data is incomplete

| What | Issue |
|------|-------|
| **Version expansion** | YAML defines `extract_raw_qa` with `versions: {range: [1,2,3]}`. Runtime creates `extract_raw_qa_1`, `extract_raw_qa_2`, `extract_raw_qa_3`. The graph should show all 52 runtime actions, not 43 YAML definitions. |
| **Manifest integration** | The manifest (`.manifest.json`) is the runtime's source of truth for execution order, levels, action indices, and completion status. The dashboard ignores it entirely. |
| **Per-action metrics** | The manifest contains per-action timing, token usage, and status. None of this surfaces in the dashboard. |
| **Dispositions** | The DB has record-level dispositions (SUCCESS, FAILED, FILTERED, etc.) per action. The dashboard doesn't query these. |

### P2 — UI issues

| What | Issue |
|------|-------|
| **Settings page** | Clicking Settings times out — no settings UI exists (report.json: FAIL) |
| **Tool detail** | Clicking a tool shows no back button (report.json: WARN) |
| **Home sparklines** | Runs sparkline shows a flat line (no data) — should be hidden when no runs exist |

## Fix Plan

### Phase 1: Make existing data correct (P0 fixes)

**1a. Read manifest for workflow status, levels, and expanded action count**

The manifest is already being read for `qanalabs_quiz_gen` (catalog shows 36 levels for that workflow). But it's not being read for `qanalabs_quiz_gen_batch` because the batch workflow has a different `agent_io` directory structure. Fix the manifest scanner to search all `agent_io*/` directories.

```
Files:
  - agent_actions/tooling/docs/scanner/workflow_scanners.py — scan_manifest()
  - agent_actions/tooling/docs/generator.py — integrate manifest data
```

**1b. Expand versioned actions in the parser**

The parser should detect `versions: {range: [1,2,3]}` on an action and expand it into concrete versioned actions (`action_1`, `action_2`, `action_3`), just like the runtime does via `yamlParser.ts` in the VS Code extension.

```
Files:
  - agent_actions/tooling/docs/parser.py — expand versions in parse_workflow()
```

**1c. Fix run scanning**

`scan_runs()` needs to search `agent_io/logs/run_results.json` (new location after spec 542) AND `agent_io/target/run_results.json` (legacy location) AND `agent_io_changed/target/run_results.json` (alternate agent_io dirs).

```
Files:
  - agent_actions/tooling/docs/scanner/data_scanners.py — scan_runs()
```

**1d. Fix log/event scanning**

Same path issue — event files may be in `agent_io/logs/` or `agent_io/target/` depending on when the project was last run. The scanner should check both.

```
Files:
  - agent_actions/tooling/docs/scanner/data_scanners.py — scan_logs()
```

### Phase 2: Surface runtime data (P1 fixes)

**2a. Per-action metrics from manifest**

The manifest contains `action_metadata` with timing, token counts, and provider info per action. Surface these in the action detail view and the workflow overview.

**2b. Disposition summary from DB**

Query the DB (via `scan_data()` or a new `scan_dispositions()`) to get per-action disposition counts (how many records succeeded, failed, were filtered, etc.). Show these in the action detail view and as a health indicator.

**2c. Prompt trace summary from DB**

Query prompt traces to show how many LLM calls each action made, average token usage, and cache hit rates. This is the operational data users need to optimize their workflows.

### Phase 3: UI fixes (P2)

**3a. Remove or implement Settings page**
**3b. Fix tool detail back navigation**
**3c. Hide sparklines when no data**

## Verification

After Phase 1, re-run `agac docs` on `qanalabs-quiz-maker` and verify:

```
Home page:
  - Actions: 104 (52 per workflow, not 86)
  - Runs: >0 (shows actual run count)
  - Workflow status: "completed" (not "paused")

Workflow detail:
  - 52 actions (not 43)
  - 36 levels (not 0)
  - Graph shows edges between all actions

Runs page:
  - Shows actual run history with status, duration, progress

Logs page:
  - Shows runtime errors and warnings from event files
```
