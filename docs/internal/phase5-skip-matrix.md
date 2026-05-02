# Phase 5 Skip Matrix — Action-Level vs Record-Level

## Action-Level Skip

An action is "skipped" when the executor decides to not run it at all:

| Trigger | RecordState impact | Skip reason | Source |
|---------|-------------------|-------------|--------|
| Upstream dependency FAILED | All records cascade | `"Upstream dependency '{dep}' failed"` | `executor.py:636` |
| Upstream dependency SKIPPED | All records cascade | `"Upstream dependency '{dep}' skipped"` | `executor.py:636` |
| Skip evaluator (no new input) | N/A (action not invoked) | `"No new input to process"` | `skip_evaluator.py` |

Action-level skips write a `__node__` disposition (DISPOSITION_SKIPPED or DISPOSITION_FAILED) and do NOT produce per-record target output.

## Record-Level Skip (within a running action)

An action runs but individual records get different outcomes:

| Outcome | RecordState | ProcessingStatus | Disposition | Resettable? |
|---------|-------------|-----------------|-------------|-------------|
| LLM success | PROCESSED | SUCCESS | success | Yes (→ACTIVE) |
| Guard skip (pre-invoke) | GUARD_SKIPPED | SKIPPED | passthrough | Yes (→ACTIVE) |
| Guard skip (FILE prefilter) | GUARD_SKIPPED | UNPROCESSED | passthrough | Yes (→ACTIVE) |
| Guard filter | — (not in output) | FILTERED | filtered | N/A |
| Cascade from upstream | CASCADE_SKIPPED | UNPROCESSED | unprocessed | No (blocks) |
| LLM failure | FAILED | FAILED | failed | No (blocks) |
| Retry exhausted | EXHAUSTED | EXHAUSTED | exhausted | No (blocks) |
| Batch deferred | — (queued) | DEFERRED | deferred | N/A |

## Telemetry Mapping

| Event field | Derived from | Notes |
|-------------|-------------|-------|
| `total_success` | count(PROCESSED) | via `CollectionStats.success` |
| `total_failed` | count(FAILED) | via `CollectionStats.failed` |
| `total_skipped` | count(GUARD_SKIPPED) | via `CollectionStats.skipped` |
| `total_filtered` | count(FILTERED) | via `CollectionStats.filtered` |
| `total_exhausted` | count(EXHAUSTED) | via `CollectionStats.exhausted` |
| `total_unprocessed` | count(CASCADE_SKIPPED) | via `CollectionStats.unprocessed` — name kept for backwards compat |
| `total_deferred` | count(DEFERRED) | via `CollectionStats.deferred` |

## UPSTREAM_SKIP_PREFIX

`UPSTREAM_SKIP_PREFIX = "Upstream dependency"` is used by the executor to format action-level skip reasons and by the CLI renderer to detect upstream failures for display. This is a **display adapter** over the structured node-level disposition — not a source of truth. The source of truth is the `__node__` disposition value.

**Decision:** Keep as display adapter. No breaking change needed.
