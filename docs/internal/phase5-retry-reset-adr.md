# ADR: Retry Reset Policy (FM9)

## Decision

**Keep target JSON on retry. Use `_state` to decide what to reprocess.**

On retry (`--downstream` / `_reset_retryable_actions`):
1. Clear SQLite dispositions for retried actions
2. Do NOT delete target JSON
3. On re-run, the executor reads existing target records via `read_target()`:
   - `PROCESSED` / `COMMITTED` → already done, skip reprocessing
   - `FAILED` / `EXHAUSTED` → needs retry, reprocess
   - `ACTIVE` → in progress or reset, reprocess

This avoids wasted LLM calls reprocessing records that already succeeded.

## Rollback Posture

No rollback to pre-Phase-5. All changes land on `integration/implement-record-state-machine`, validated end-to-end (qanalabs smoke, 6282 tests) before merging to main.

## Consequences

- Target JSON is the authority. Dispositions are re-derivable telemetry.
- Re-run with cleared dispositions + existing target: executor's `_verify_completion_status()` sees target files exist → marks action complete without re-invoking LLM.
- If a record FAILED, its target JSON carries `_state: "failed"`. On retry, the executor resets it to ACTIVE (via `reset_for_downstream`) and the action reprocesses it.

## Alternatives Considered

1. **Delete target/ on retry** — Forces full reprocessing. Wastes API calls for records that already succeeded. Rejected.
2. **Infer _state from content structure** — Fragile, violates fail-closed principle (P5-023). Rejected.
3. **Separate retry-queue table** — Over-engineering for current scale. Could revisit if record counts exceed 10K per action.

## Modules Affected

- `agent_actions/workflow/coordinator.py` — `_reset_retryable_actions`
- `agent_actions/workflow/managers/state.py` — `reset_retryable`
- `agent_actions/storage/backends/sqlite_backend.py` — `clear_disposition`
- `agent_actions/workflow/executor.py` — `_verify_completion_status` (reads target, checks if action needs re-run)
