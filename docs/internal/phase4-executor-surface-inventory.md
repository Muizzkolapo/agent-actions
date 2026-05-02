# Phase 4 Executor Surface Inventory

**Generated:** 2026-05-02
**Baseline commit:** main at ac96b92

---

## LOC baselines

| File | Lines | Target | Role |
|------|-------|--------|------|
| `workflow/executor.py` | 1,056 | ~500 | Simplify — extract batch lifecycle, success handler |
| `workflow/runner_file_processing.py` | 430 | ~300 | Simplify — input selection |
| `workflow/managers/batch.py` | 202 | ~350 | Grows — receives batch lifecycle |
| `workflow/managers/loop.py` | 462 | ~462 | Keep — version correlation |
| `workflow/managers/output.py` | 237 | ~200 | Minor simplification |
| `workflow/managers/state.py` | 213 | ~213 | Keep — clean |
| **Total** | **2,600** | **~2,025** | |

---

## Executor method inventory

### Sequencing (pure orchestration, ~130 LOC)

| Method | Lines | Role |
|--------|-------|------|
| `execute_action_sync` | 671–731 | Main sync entry: verify → skip? → health? → run → handle result |
| `execute_action_async` | 733–794 | Async mirror of above |
| `_execute_action_run` | 988–1011 | Sets RUNNING, resolves input, delegates to action_runner |
| `_execute_action_run_async` | 1013–1037 | Async wrapper via asyncio.to_thread |

### Status management (~100 LOC)

| Method | Lines | Role |
|--------|-------|------|
| `_maybe_invalidate_completed_status` | 153–172 | Resets COMPLETED→PENDING if config changed |
| `verify_completion_status` | 174–183 | Public API: should action run again? |
| `_verify_completion_status` | 185–248 | Checks disposition + storage output |
| `_resolve_completion_status` | 474–510 | Determines SKIPPED vs COMPLETED vs WITH_FAILURES |

### Circuit breaker / skip logic (~160 LOC)

| Method | Lines | Role |
|--------|-------|------|
| `_check_upstream_health` | 542–618 | Checks deps + version sources for failures |
| `_handle_dependency_skip` | 620–669 | Marks SKIPPED when upstream fails |
| `_handle_action_skip` | 250–298 | WHERE clause skip |

### Batch lifecycle (~230 LOC, extraction target)

| Method | Lines | Role |
|--------|-------|------|
| `_handle_batch_check` | 812–897 | Sync: poll batch, process results, fire events |
| `_handle_batch_check_async` | 899–986 | Async: same as above |
| `_check_batch_submission` | 1042–1056 | Detect if batch was submitted post-run |
| `_compute_batch_wall_clock` | 796–810 | Calculate elapsed from submitted_at timestamp |

### Success/failure handlers (~180 LOC, simplification target)

| Method | Lines | Role |
|--------|-------|------|
| `_handle_run_success` | 320–436 | Batch detection, passthrough, status, metrics, events |
| `_handle_run_failure` | 512–540 | Write disposition, record failure event |

### Disposition writes (~40 LOC)

| Method | Lines | Role |
|--------|-------|------|
| `_write_failed_disposition` | 438–454 | Writes DISPOSITION_FAILED |
| `_write_skipped_disposition` | 456–472 | Writes DISPOSITION_SKIPPED |

### Other (~30 LOC)

| Method | Lines | Role |
|--------|-------|------|
| `_track_action_start` | 300–318 | Records action start in run_tracker |
| `_limit_metadata` | 145–151 | Extracts limit config |

---

## Events fired by executor

| Event | Location(s) | Trigger |
|-------|-------------|---------|
| `ActionSkipEvent` | 276, 380, 647 | WHERE clause skip, guard-all-skipped, dependency skip |
| `BatchSubmittedEvent` | 334, 865, 954 | Initial batch submission, recovery batch submission |
| `BatchCompleteEvent` | 846, 881, 935, 970 | Batch completed (4 paths: sync success, sync fail, async success, async fail) |

---

## Disposition writes

| Call site | Line | Condition |
|-----------|------|-----------|
| `_write_failed_disposition` | 523 | Action run threw exception |
| `_write_skipped_disposition` | 641 | Upstream dependency skip |
| `_write_failed_disposition` | 880 | Batch job failed (sync) |
| `_write_failed_disposition` | 969 | Batch job failed (async) |

---

## Batch lifecycle flow

```
execute_action_sync/async
  │
  ├─ Status == BATCH_SUBMITTED?
  │    └─ YES → _handle_batch_check → poll → process → finalize/continue
  │
  └─ Status != BATCH_SUBMITTED?
       └─ _execute_action_run → action_runner.run_action()
            └─ _check_batch_submission()
                 ├─ "batch_submitted" → BATCH_SUBMITTED status
                 ├─ "passthrough" → COMPLETED
                 └─ "no_batches" → COMPLETED
```

### _handle_batch_check internals (sync, 812–897)

```
1. update_status(CHECKING_BATCH)
2. batch_manager.handle_batch_agent(action_name, ...)
3. if result.is_complete:
   a. _resolve_completion_status → status
   b. fire BatchCompleteEvent(total, completed, failed, elapsed)
   c. update_status(resolved)
4. elif result.is_in_progress:
   a. update_status(BATCH_SUBMITTED)
   b. fire BatchSubmittedEvent (still processing)
5. elif result.is_failed:
   a. _write_failed_disposition
   b. fire BatchCompleteEvent (as failure)
   c. update_status(FAILED)
```

---

## runner_file_processing.py functions

| Function | Lines | Role |
|----------|-------|------|
| `is_target_directory` | 30–33 | Check if path is target/ (skip it) |
| `_file_limit_reached` | 35–42 | Check max_files config |
| `should_skip_item` | 44–63 | Skip logic: hidden files, target dirs, limits |
| `collect_files_from_upstream` | 65–88 | Walk upstream dirs for input files |
| `warn_no_files_found` | 90–110 | Log warning when no inputs found |
| `process_directory_files` | 112–149 | Process files from one upstream dir |
| `process_merged_files` | 151–230 | Merge multiple dirs into one pass |
| `process_from_storage_backend` | 232–362 | Read inputs from SQLite backend |
| `process_files` | 364–430 | Entry point: dispatches to above based on mode |

---

## Dependencies on service objects

| Service | Used by | Methods called |
|---------|---------|---------------|
| `state_manager` | executor | `get_status`, `update_status`, `get_status_details` |
| `batch_manager` | executor | `handle_batch_agent`, `check_batch_submission` |
| `action_runner` | executor | `run_action` |
| `output_manager` | executor | `resolve_correlated_input` |
| `skip_evaluator` | executor | `should_skip_action` |
| `run_tracker` | executor | `record_action_start/end/skip/failure` |
| `storage_backend` | executor, runner | `set_disposition`, `read_target`, `get_dispositions` |

---

## Test coverage by responsibility

| Responsibility | Test file(s) | Tests | Coverage |
|----------------|-------------|-------|----------|
| Orchestration flow | `test_executor_lifecycle.py` | 37 | Good |
| Circuit breaker | `test_circuit_breaker.py` | 43 | Excellent |
| Batch lifecycle | `test_executor_batch.py` | 3 | **Minimal** |
| Events | `test_executor_events.py` | ~10 | Moderate |
| Run tracker | `test_action_executor_run_tracker.py` | ~8 | Moderate |
| Batch dispositions | `managers/test_batch_lifecycle_disposition.py` | ~5 | Moderate |
| Runner file processing | — | — | **Zero direct tests** |

### Critical test gaps

- `_handle_batch_check` has only 3 tests (action_name injection)
- `_handle_batch_check_async` has minimal coverage
- Batch failure path (disposition write + event fire) weakly tested
- `runner_file_processing.py` has ZERO direct unit tests
- `_handle_run_success` guard-all-skipped path tested but metrics/passthrough path indirect
