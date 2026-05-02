# Phase 5 Invariant Table: RecordState x ProcessingStatus x executed

This table is **normative**. If code disagrees with this table, the code is wrong.

## Outcome Table

| # | Outcome | RecordState | ProcessingStatus | executed | Enricher runs? | Strategy path |
|---|---------|-------------|-----------------|----------|---------------|---------------|
| 1 | Online LLM success | PROCESSED | SUCCESS | true | Yes | `online_llm.py:420` |
| 2 | Online guard skip (behavior=skip) | GUARD_SKIPPED | SKIPPED | false | No | `online_llm.py:256` |
| 3 | Online guard filter (behavior=filter) | — (not in output) | FILTERED | false | No | `online_llm.py:241` |
| 4 | Online upstream unprocessed (cascade) | CASCADE_SKIPPED | UNPROCESSED | false | No | `online_llm.py:225` |
| 5 | Online LLM-layer filter (no response) | — (not in output) | FILTERED | false | No | `online_llm.py:329` |
| 6 | Online LLM-layer skip (guard=skip post-invoke) | GUARD_SKIPPED | SKIPPED | false | No | `online_llm.py:343` |
| 7 | Online LLM error / exception | — (not in output) | FAILED | false | No | `online_llm.py:156` |
| 8 | Retry exhausted (return_last) | EXHAUSTED | EXHAUSTED | false | No | `online_llm.py:311` |
| 9 | Retry exhausted (raise) | — (exception) | EXHAUSTED | false | No | `result_collector.py:526` |
| 10 | Guard deferred (HITL / batch queue) | — (not in output) | DEFERRED | false | No | `online_llm.py:299` |
| 11 | FILE guard prefilter skip | CASCADE_SKIPPED | UNPROCESSED | false | No | `unified.py:186` |
| 12 | FILE tool success | PROCESSED | SUCCESS | true | Yes | `file_tool.py:85` |
| 13 | FILE tool error | — (not in output) | FAILED | false | No | `file_tool.py:68` |
| 14 | Batch success | PROCESSED | SUCCESS | true | Yes | `batch_result_strategy.py:287` |
| 15 | Batch guard skip | GUARD_SKIPPED | SKIPPED | false | No | `unified.py:132` |
| 16 | Batch upstream unprocessed | CASCADE_SKIPPED | UNPROCESSED | false | No | `batch_result_strategy.py:474` |
| 17 | Batch not returned (missing from response) | CASCADE_SKIPPED | UNPROCESSED | false | No | `batch_result_strategy.py:495` |
| 18 | Batch error | — (not in output) | FAILED | false | No | `batch_result_strategy.py:316` |
| 19 | Batch retry exhausted (return_last) | EXHAUSTED | EXHAUSTED | false | No | `batch_result_strategy.py:387` |
| 20 | Batch retry exhausted (raise) | — (exception) | — | — | — | `batch_result_strategy.py:436` |

## Column Semantics

- **RecordState** — the state stamped by `ResultCollector._stamp()` before writing to target. "—" means the record is not written to output (filtered, failed without data, or exception raised).
- **ProcessingStatus** — the enum value on `ProcessingResult.status`.
- **executed** — whether the LLM/tool was actually invoked. Determines enricher eligibility.
- **Enricher runs?** — `MetadataEnricher` runs only when `result.executed == True` (`enrichment.py:131`).

## RecordState Mapping Rules

| ProcessingStatus | RecordState | Rationale |
|-----------------|-------------|-----------|
| SUCCESS | PROCESSED | Action completed, output produced |
| SKIPPED | GUARD_SKIPPED | Guard clause rejected, tombstone written |
| FILTERED | — (no output) | Guard rejected, record dropped entirely |
| UNPROCESSED | CASCADE_SKIPPED | Upstream dependency missing or guard-prefilter |
| EXHAUSTED | EXHAUSTED | Retries consumed, last attempt output preserved |
| FAILED | FAILED | Error during processing (stamped only if data written) |
| DEFERRED | — (no output) | Queued for batch/HITL, disposition tracked |

## Resolved Mismatches (P5-031)

1. **FILE guard prefilter uses UNPROCESSED — intentional (FM13).** `unified.py:186` returns `ProcessingResult.unprocessed()` for FILE guard skips. This preserves `guard_results + invocation_results` merge ordering. Changing to `skipped()` would collapse the two list sources and risk FM13 regression. FILE prefilter skips remain CASCADE_SKIPPED by design.

2. **Online post-invoke guard skip — FIXED.** `online_llm.py:343` now returns `ProcessingResult.skipped()` instead of `unprocessed()`. This is a guard decision (not a cascade), so GUARD_SKIPPED is correct. Aligns with pre-invoke guard skip behavior.

3. **FAILED records without data are invisible — accepted.** Failure is tracked via disposition only. No record enters target storage. This is correct: failed records have no valid output to persist.

## Enricher Behavior

The `MetadataEnricher` (`enrichment.py`) runs when:
- `result.executed == True`
- This means only SUCCESS paths get metadata enrichment (lineage, node_id, etc.)

All non-executed paths (guards, cascades, exhaustion, failures) preserve whatever metadata the input record carried — they do not get fresh enrichment.

## Notes

- GUARD_DEFERRED exists in RecordState but is not currently produced by any strategy. It is reserved for future HITL guard deferral where the record stays in output pending human review.
- Batch results use `processing_context` for enrichment instead of inline enrichment. The enricher is called by the batch service after result collection.
- Retry exhausted with `on_exhausted=raise` throws before ResultCollector runs — no record is written, no state is stamped.
