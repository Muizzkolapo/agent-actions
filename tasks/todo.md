# Failure Propagation & Visibility Fixes

Root issue: per-item failures don't propagate to action status, circuit breaker never fires, operator sees misleading green output.

Reference: `failures.txt`, PR #67 (added circuit breaker but upstream never signals failure).

---

## Phase 1 — Bugfix: Accurate tally + level coloring (DONE — PR #80)

**Discovery:** PR #67 already added the zero-output check at `pipeline.py:493-508`. The total-wipeout case (0/N items) already propagates as `"failed"`. The remaining bugs were:
- `_handle_dependency_skip` used `status="failed"` → tally showed 0 SKIP
- Level completion line was always green

**Approach:** Introduced `"skipped"` as a proper terminal status for dependency-skipped actions.

- [x] **1.1** Add `is_skipped()` to state manager, update terminal sets
  - Added `is_skipped()` method to `ActionStateManager`
  - Updated `get_pending_actions` terminal: `{"completed", "failed", "skipped"}`
  - Updated `is_workflow_done` terminal: `{"completed", "failed", "skipped"}`

- [x] **1.2** Update executor: `_handle_dependency_skip` → `status="skipped"`
  - Added `DISPOSITION_SKIPPED` import
  - Added `_write_skipped_disposition()` method
  - Changed `_handle_dependency_skip`: state → "skipped", disposition → SKIPPED, result → "skipped"
  - Updated `_check_upstream_health`: checks `is_failed OR is_skipped`, checks both dispositions

- [x] **1.3** Fix level completion line coloring
  - `action_executor.py:355`: red if failed, yellow if skipped, green if all OK

- [x] **1.4** Tests
  - Updated all circuit breaker tests to expect "skipped"
  - Added `test_dep_skipped_via_state_manager` and `test_dep_skipped_via_disposition`
  - Added `TestWriteSkippedDisposition` test class
  - Added `TestIsSkipped`, `TestWorkflowDoneWithSkipped` in state extensions
  - All 4271 tests pass, ruff clean

---

## Phase 2 — Observability: Partial failure visibility

**Goal:** When K/N items succeed, action is `completed_with_failures`, item-level failures are persisted and surfaced.

- [x] **2.1** Storage backend: extend disposition with `input_snapshot`
  - Added `input_snapshot` param to abstract `set_disposition()` and `get_failed_items()` to base class
  - SQLite: added column, schema migration, 10KB cap with `__truncated__` sentinel for valid JSON
  - `get_disposition()` returns `input_snapshot` in results

- [x] **2.2** Result collector: write input snapshots for failed items
  - `collect_results()` serializes `source_snapshot or input_record` as JSON for FAILED items
  - Passes via `_safe_set_disposition(**kwargs)` — no return type change needed
  - Discovery: executor queries `get_failed_items()` directly from storage — no plumbing needed

- [x] **2.3** Executor: `completed_with_failures` status
  - `_resolve_completion_status()` queries storage for item-level failures after success
  - Used in online path + both batch paths (sync/async)
  - State manager: `is_completed_with_failures()`, updated all terminal sets
  - `is_completed()` includes partial, circuit breaker ignores it
  - 9 status checks across 6 files updated; extracted `COMPLETED_STATUSES` and `TERMINAL_STATUSES` constants

- [x] **2.4** Tally and display
  - `WorkflowCompleteEvent`: added `actions_partial`
  - Formatter: `"N OK | M PARTIAL | S SKIP | K ERROR"` with yellow coloring
  - Level line: yellow for levels with partial failures

- [x] **2.5** Tests + review fixes
  - 13 new tests: `_resolve_completion_status` (4 paths), `get_failed_items` sentinel filtering,
    circuit breaker ignores partial, `is_completed_with_failures`, terminal sets, level coloring
  - Review fixes: `is_completed()` includes partial, PARTIAL in COLORS dict, WARNING-level
    exception logging, valid JSON truncation, `mark_action_completed` accepts status,
    `dependency.py`/`manifest.py` accept partial, migration logging
  - PR #92, 4292 tests pass

---

## Phase 3 — UX: Pause-and-surface + retry

**Goal:** Workflow pauses on partial failure (default), user can retry failed items or continue. Configurable retry policy.

**PR A: Pause-and-surface + on_partial_failure config**

- [ ] **3.1** Config: `on_partial_failure` field (defaults + per-action inheritance)
  - `ActionConfig`: `on_partial_failure: Literal["continue", "pause"] = "continue"`
  - `DefaultsConfig`: `on_partial_failure: ... | None = None`
  - `SIMPLE_CONFIG_FIELDS`: `"on_partial_failure": "continue"`
  - `ActionConfigDict`: add field
  - `WorkflowState`: add `pause_reason: str | None = None`
  - `LevelExecutionParams`: add `on_partial_failure`, `workflow_state`, `storage_backend`

- [ ] **3.2** Pause logic: async + sequential paths
  - `execute_level_async`: detect partial + pause → print summary, set pause_reason, return False
  - Annotate batch-pending path with `pause_reason = "batch_pending"`
  - `_run_single_action`: detect partial + pause → print summary, set pause_reason, return True
  - Summary method: list action names, item counts, truncated errors

- [ ] **3.3** CLI: correct pause message per pause_reason
  - `run.py`: check `workflow.state.pause_reason` for message selection
  - "partial_failure" → partial-specific message
  - None/other → existing batch-pending message

- [ ] **3.4** Tests for PR A
  - Config schema + inheritance
  - Async pause (partial+pause → False, partial+continue → True, no partial → True)
  - Sequential pause
  - CLI message selection
  - Summary output

- [ ] **3.3** `agac retry` command / `--retry-failed` flag
  - `agac retry <action>`: re-run only failed items for the specified action
  - `agac run --retry-failed`: re-run failed items for all actions with failures
  - Uses persisted item-level failures (Phase 2) to filter input to only failed guids
  - On success: update item status, recalculate action status
  - Verify: manual run → fail items → retry → items succeed → action becomes `completed`

- [ ] **3.4** Configurable retry policy
  - Per-action config: `retry: {max_attempts: 3, backoff: exponential}`
  - Executor retries failed items inline up to `max_attempts` before finalizing
  - Only items still failing after all retries are persisted as failures
  - Verify: `pytest`, manual run with transient 429 error → retried automatically

- [ ] **3.5** Tests for Phase 3
  - Test: workflow pauses on partial failure by default
  - Test: `on_partial_failure: continue` skips pause
  - Test: retry command re-processes only failed items
  - Test: retry policy with backoff retries transient errors
  - Test: after successful retry, action status updates to `completed`
  - Verify: `pytest`

---

## Working Notes

- Circuit breaker code: `executor.py:416-432` (`_check_upstream_health`)
- Failure recording: `executor.py:377-397` (`_handle_run_failure`)
- Level completion line: `action_executor.py:356`
- Tally output: TBD — need to locate the exact counter logic
- Action runner item processing: TBD — need to trace where per-item errors are caught
- State manager: `managers/state.py` — `is_failed()`, `get_pending_actions()`
