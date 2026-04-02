# Failure Propagation & Visibility Fixes

Root issue: per-item failures don't propagate to action status, circuit breaker never fires, operator sees misleading green output.

Reference: `failures.txt`, PR #67 (added circuit breaker but upstream never signals failure).

---

## Phase 1 — Bugfix: Accurate tally + level coloring (REVISED)

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

- [ ] **2.1** Add `completed_with_failures` status to state manager
  - New terminal status alongside `completed` and `failed`
  - Circuit breaker ignores this status (descendants run on partial output)
  - Tally counts it as `PARTIAL`
  - Verify: `pytest`, `ruff check .`

- [ ] **2.2** Item-level failure tracking in storage backend
  - Persist which items (by `source_guid` or index) failed and the error message
  - Storage schema addition (e.g., `item_failures` table or disposition record)
  - Verify: unit test asserting failed items are persisted and retrievable

- [ ] **2.3** Populate `completed_with_failures` from executor
  - After action runner returns: if `items_succeeded > 0 AND items_succeeded < items_attempted` → status `completed_with_failures`
  - Write item-level failures to storage backend
  - Verify: `pytest`, manual run with partial failure confirms new status + persisted failures

- [ ] **2.4** Surface partial failures in output
  - Action completion log: `"Action 'X': 9/10 items OK, 1 failed (see item failures)"`
  - Tally: `"8 OK | 1 PARTIAL | 0 SKIP | 2 ERROR"`
  - Level line: yellow for levels containing `completed_with_failures` actions
  - Verify: manual run, visual inspection

- [ ] **2.5** Tests for Phase 2
  - Test: partial failure → status is `completed_with_failures`, not `completed` or `failed`
  - Test: item-level failures are persisted with guid + error
  - Test: descendants of `completed_with_failures` action still run (not skipped)
  - Test: tally shows PARTIAL count
  - Verify: `pytest`

---

## Phase 3 — UX: Pause-and-surface + retry

**Goal:** Workflow pauses on partial failure (default), user can retry failed items or continue. Configurable retry policy.

- [ ] **3.1** Pause-and-surface on partial failure (default behavior)
  - After a level containing `completed_with_failures` actions, pause workflow
  - Print summary: `"9/10 OK, 1 failed. Run 'agac retry <action>' or 'agac run --continue'"`
  - List failed items with truncated error messages
  - Verify: manual run with partial failure → workflow pauses with clear message

- [ ] **3.2** `on_partial_failure` config option
  - Per-action or workflow-level config: `on_partial_failure: pause | continue`
  - Default: `pause`
  - `continue`: skip the pause, proceed with partial results (for automated pipelines)
  - Verify: `pytest`, manual run with `continue` config → no pause

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
