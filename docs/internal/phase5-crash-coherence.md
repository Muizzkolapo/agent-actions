# Phase 5 Crash Coherence — Write Ordering and Recovery

## Happy Path Write Order

For each record batch in an action:

1. **Target JSON** — `write_target()` persists records with `_state` to SQLite `target_data` table
2. **Disposition** — `_safe_set_disposition()` writes the derived disposition to `record_disposition` table
3. **Node disposition** — executor writes `__node__` disposition after all records complete

## Crash Scenarios

### Crash after target write, before disposition write

**State:** Target JSON has correct `_state`. Disposition table is stale/missing.

**Recovery:** On next run, the executor's `_verify_completion_status()` detects missing output and re-runs the action. Re-run calls `write_target()` (overwrites) + `set_disposition()` (writes fresh). Dispositions are derived from `_state` via `derive_disposition()` — so re-running produces correct dispositions automatically.

**Manual cleanup:** None needed. Re-run self-heals.

### Crash after disposition write, before node disposition

**State:** Individual record dispositions are correct. Node-level `__node__` disposition is missing.

**Recovery:** On next run, executor sees no node disposition → treats action as incomplete → re-runs. Since target data already exists, `_verify_completion_status()` detects existing output and may skip (depending on freshness check). If it re-runs, the idempotent write path overwrites safely.

**Manual cleanup:** None needed.

### Crash mid-batch (some records written, others not)

**State:** Partial target data in SQLite. Some records have `_state`, others are missing entirely (not in target_data).

**Recovery:** On re-run, `write_target()` overwrites the entire batch file atomically (one row per `action_name + relative_path`). So partial writes are replaced with a complete batch on the next run.

**Manual cleanup:** None needed. The atomic write-per-file granularity prevents partial corruption.

## Key Invariants

1. **`_state` in target JSON is the authority.** Dispositions can always be re-derived from `_state` via `derive_disposition()`. If they diverge, `_state` wins.

2. **`write_target()` is atomic per file.** A single `INSERT OR REPLACE` covers the entire batch for a given `action_name/relative_path`. No partial row states.

3. **Re-run is always safe.** The framework is designed for idempotent re-runs. Stale data is overwritten, not appended.

4. **Dispositions are telemetry, not authority.** They exist for skip-evaluator lookups and operator dashboards. If lost, the pipeline still produces correct output on re-run.

## Logging Grep Hints

```bash
# Disposition write failures (elevated to ERROR in P5-053)
grep "Failed to write disposition" logs/

# Missing _state on read (fail-closed from P5-023)
grep "Record is missing '_state'" logs/

# Downstream reset events
grep "downstream_reset" logs/
```
