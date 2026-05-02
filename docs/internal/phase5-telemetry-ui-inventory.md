# Phase 5 — Telemetry, UI & Disposition Inventory

Single checklist for Milestones B–K. Every row must be accounted for by the milestone that touches it.

---

## 1. Reason String Zoo

Every bare string literal used as a skip/guard/cascade/disposition reason in production code.

| String | File | Line(s) | Used as |
|--------|------|---------|---------|
| `"guard_skip"` | `processing/unified.py` | 136, 142 | tombstone reason, ProcessingResult.skipped reason |
| `"guard_skip"` | `processing/strategies/online_llm.py` | 347, 352 | ProcessingResult.unprocessed reason |
| `"guard_skip"` | `llm/batch/processing/batch_result_strategy.py` | 477 | passthrough reason when filter_phase is SKIPPED |
| `"guard_skip"` | `processing/result_collector.py` | 328 | disposition fallback reason |
| `"guard_prefilter_skip"` | `processing/unified.py` | 197 | ProcessingResult.unprocessed reason (FILE mode) |
| `f"guard_{prepared.guard_behavior}"` | `processing/strategies/online_llm.py` | 255, 261, 266 | filter event, tombstone, ProcessingResult.skipped |
| `"guard_filter"` | `processing/strategies/online_llm.py` | 240 | RecordFilteredEvent filter_reason |
| `"guard_filter"` | `processing/result_collector.py` | 413 | disposition fallback reason |
| `"llm_layer_guard_skip"` | `processing/strategies/online_llm.py` | 341 | RecordFilteredEvent filter_reason |
| `"llm_layer_guard_filter"` | `processing/strategies/online_llm.py` | 327 | RecordFilteredEvent filter_reason |
| `"upstream_unprocessed"` | `processing/strategies/online_llm.py` | 227 | ProcessingResult.unprocessed reason |
| `"upstream_unprocessed"` | `llm/batch/processing/batch_result_strategy.py` | 474–475 | FILTER_PHASE dispatch + reason |
| `"upstream_unprocessed"` | `llm/batch/processing/preparator.py` | 177 | FILTER_PHASE value |
| `"unified"` | `llm/batch/processing/preparator.py` | 186, 195 | FILTER_PHASE value |
| `"batch_not_returned"` | `llm/batch/processing/batch_result_strategy.py` | 479 | passthrough reason fallback |
| `"evaluation_exhausted:{validation}"` | `processing/result_collector.py` | 177 | disposition reason (f-string) |
| `"retry_exhausted"` | `processing/result_collector.py` | 185 | disposition reason |
| `"retry_exhausted"` | `processing/record_helpers.py` | 75–76 | metadata.reason + metadata key |
| `"retry_exhausted"` | `processing/exhausted_builder.py` | 55 | metadata key (via dict literal) |
| `"unprocessed"` | `processing/result_collector.py` | 188, 438 | disposition reason fallback |
| `"parse_error"` | `processing/result_collector.py` | 280 | disposition reason |
| `"All records guard-filtered — no output produced"` | `workflow/executor.py` | 372, 384, 394 | skip_reason (3× same string, no constant) |
| `"WHERE clause — action skipped"` | `workflow/executor.py` | 37 | `WHERE_SKIP_REASON` constant (good) |
| `"Upstream dependency"` | `workflow/executor.py` | 34 | `UPSTREAM_SKIP_PREFIX` constant (good) |
| `"skip_condition evaluated to True"` | `workflow/managers/skip.py` | 77 | skip_reason |
| `"error occurred and passthrough_on_error=False"` | `workflow/managers/skip.py` | 121 | skip_reason |
| `"guard condition not met"` | `workflow/managers/skip.py` | 204 | skip_reason |
| `"legacy skip_if condition matched"` | `workflow/managers/skip.py` | 259 | skip_reason |
| `"already completed"` | `workflow/execution_events.py` | 87 | skip_reason |
| `"return_last"` | `config/schema.py` | 84, 104 | on_exhausted default |
| `"return_last"` | `llm/batch/processing/batch_result_strategy.py` | 423, 426 | on_exhausted default + config read |
| `"raise"` | `llm/batch/processing/batch_result_strategy.py` | 435 | on_exhausted comparison |
| `"skipped_by_where_clause"` | `utils/passthrough_builder.py` | 82 | metadata mapping |
| `"skipped_by_conditional"` | `utils/passthrough_builder.py` | 81 | metadata mapping |

**Milestone B** defines constants for all of these. Only `WHERE_SKIP_REASON` and `UPSTREAM_SKIP_PREFIX` are currently constantized.

---

## 2. Framework Field Lists

| Field | `RECORD_TRACKING_FIELDS` | `RECORD_STAGE_FIELDS` | `_RECORD_METADATA_KEYS` | `METADATA_KEYS` (py) | `METADATA_KEYS` (ts) | `METADATA_KEYS` (vscode) |
|-------|:---:|:---:|:---:|:---:|:---:|:---:|
| `source_guid` | ✓ | — | ✓ | ✓ | ✓ | ✓ |
| `version_correlation_id` | ✓ | — | **✗** | **✗** | **✗** | **✗** |
| `target_id` | — | ✓ | ✓ | ✓ | ✓ | ✓ |
| `node_id` | — | ✓ | ✓ | ✓ | ✓ | ✓ |
| `lineage` | — | ✓ | ✓ | ✓ | ✓ | ✓ |
| `metadata` | — | ✓ | ✓ | ✓ | ✓ | ✓ |
| `content` | — | ✓ | **✗** | **✗** | **✗** | **✗** |
| `_unprocessed` | — | ✓ | ✓ | ✓ | ✓ | ✓ |
| `_recovery` | — | ✓ | ✓ | ✓ | ✓ | ✓ |
| `parent_target_id` | — | ✓ | ✓ | ✓ | ✓ | ✓ |
| `root_target_id` | — | ✓ | ✓ | ✓ | ✓ | ✓ |
| `chunk_info` | — | ✓ | ✓ | ✓ | ✓ | ✓ |
| `_file` | — | — | — | ✓ | ✓ | ✓ |
| `_trace` | — | — | — | — | ✓ | ✓ |
| `_state` | — | — | — | — | — | — |
| `_state_history` | — | — | — | — | — | — |
| `_state_schema_version` | — | — | — | — | — | — |

**Locations:**
- `RECORD_TRACKING_FIELDS`: `record/envelope.py:9`
- `RECORD_STAGE_FIELDS`: `record/envelope.py:19`
- `RECORD_FRAMEWORK_FIELDS`: `record/envelope.py:36` (union of tracking + stage)
- `_RECORD_METADATA_KEYS`: `prompt/context/scope_namespace.py:16`
- `METADATA_KEYS` (py): `tooling/rendering/data_card.py:16`
- `METADATA_KEYS` (ts): `tooling/docs/frontend/lib/data-card-utils.ts:13`
- `METADATA_KEYS` (vscode): `vscode-extension/src/views/queryResultsPanel.ts:187`

**Discrepancies:**
- `version_correlation_id` — in framework fields, missing from all exclusion sets
- `content` — in framework fields, missing from all exclusion sets
- `_file` — in UI rendering sets, missing from framework definition
- `_trace` — in TS/VSCode only, missing from Python and framework
- `_state` / `_state_history` / `_state_schema_version` — **not yet defined anywhere** (Milestone C adds to framework, Milestone J adds to exclusion sets)

---

## 3. Disposition Persistence

### Disposition enum (`storage/backend.py:20-30`)

| Value | Constant | Enum |
|-------|----------|------|
| `"passthrough"` | `DISPOSITION_PASSTHROUGH` | `Disposition.PASSTHROUGH` |
| `"skipped"` | `DISPOSITION_SKIPPED` | `Disposition.SKIPPED` |
| `"filtered"` | `DISPOSITION_FILTERED` | `Disposition.FILTERED` |
| `"exhausted"` | `DISPOSITION_EXHAUSTED` | `Disposition.EXHAUSTED` |
| `"failed"` | `DISPOSITION_FAILED` | `Disposition.FAILED` |
| `"deferred"` | `DISPOSITION_DEFERRED` | `Disposition.DEFERRED` |
| `"unprocessed"` | `DISPOSITION_UNPROCESSED` | `Disposition.UNPROCESSED` |
| `"success"` | `DISPOSITION_SUCCESS` | `Disposition.SUCCESS` |

`VALID_DISPOSITIONS = frozenset(d.value for d in Disposition)` at `backend.py:33`.

### set_disposition call sites (16 total)

| File | Line(s) | Type | Notes |
|------|---------|------|-------|
| `workflow/executor.py` | 442 | node-level | `_write_failed_disposition` — FAILED with 500-char reason |
| `workflow/executor.py` | 460 | node-level | `_write_skipped_disposition` — SKIPPED with reason |
| `processing/result_collector.py` | 99 | wrapper | `_safe_set_disposition` — swallows errors |
| `processing/result_collector.py` | 123 | node-level | `write_node_level_disposition` |
| `processing/result_collector.py` | 172 | record-level | EXHAUSTED for retry-exhausted |
| `processing/result_collector.py` | 180 | record-level | FAILED |
| `processing/result_collector.py` | 193 | record-level | FILTERED |
| `processing/result_collector.py` | 201 | record-level | PASSTHROUGH |
| `processing/result_collector.py` | 275 | record-level | DEFERRED |
| `processing/result_collector.py` | 299, 323, 350, 388, 408, 433, 456, 546 | record-level | various status branches |

### clear_disposition call sites (8 total)

| File | Line | Trigger |
|------|------|---------|
| `workflow/executor.py` | 167 | file_limit config changed |
| `workflow/executor.py` | 209 | re-running after prior skip/fail |
| `workflow/executor.py` | 489 | stale skip when output files exist |
| `workflow/executor.py` | 587 | stale failed when upstream has output |
| `workflow/executor.py` | 605 | stale skip on upstream dependency |
| `workflow/coordinator.py` | 277 | `_clear_for_fresh_run` (--fresh) |
| `workflow/coordinator.py` | 298 | `_reset_retryable_actions` |
| `processing/result_collector.py` | 155 | clear DEFERRED before writing final |

---

## 4. Telemetry Surfaces (skip_reason flow)

| File | Line(s) | Role |
|------|---------|------|
| `workflow/executor.py` | 34 | `UPSTREAM_SKIP_PREFIX` definition |
| `workflow/executor.py` | 37 | `WHERE_SKIP_REASON` definition |
| `workflow/executor.py` | 280, 291 | WHERE-clause skip events |
| `workflow/executor.py` | 372, 384, 394 | guard-filtered skip (3× bare string) |
| `workflow/executor.py` | 635, 638, 651, 662 | upstream cascade skip events |
| `workflow/managers/skip.py` | 77, 121, 204, 259 | skip_if / guard / error skip reasons |
| `workflow/managers/manifest.py` | 283 | stores skip_reason in manifest |
| `workflow/managers/output.py` | 121 | reads skip_reason from skip rows |
| `workflow/execution_events.py` | 87 | "already completed" skip_reason |
| `logging/events/workflow_events.py` | 181, 188, 193 | ActionSkipEvent dataclass + dict |
| `logging/events/handlers/run_results.py` | 29, 46, 226, 235 | Result dataclass + extraction |
| `logging/events/formatters.py` | 135 | extracts skip_reason from event |
| `cli/renderers/execution_renderer.py` | 39, 97, 256, 269–270 | display + UPSTREAM_SKIP_PREFIX check |
| `tooling/docs/run_tracker.py` | 88, 373–374 | ActionConfig field + JSON write |
| `processing/types.py` | 125, 184, 264 | ProcessingResult.skip_reason field + factories |
| `processing/result_collector.py` | 328, 413, 438 | disposition reason fallbacks |
| `logging/events/data_pipeline_events.py` | 463, 477, 489 | `total_unprocessed` field + message + dict |

---

## 5. `_unprocessed` writes (5 locations)

| File | Line | Context |
|------|------|---------|
| `processing/record_helpers.py` | 47 | `build_tombstone()` — guard-skip / error tombstones |
| `processing/record_helpers.py` | 79 | `build_exhausted_tombstone()` — retry-exhausted |
| `processing/strategies/online_llm.py` | 220 | `UPSTREAM_UNPROCESSED` passthrough |
| `utils/passthrough_builder.py` | 73 | unified passthrough builder |
| `processing/result_collector.py` | 257 | parse-error reclassification |

---

## 6. UI Surfaces

| File | Line(s) | What it reads | Phase 5 change |
|------|---------|---------------|----------------|
| `tooling/docs/frontend/components/ui/data-card.tsx` | tombstoneReason checks | `"guard_skip"`, `"upstream_unprocessed"` | Read `_state` (J) |
| `tooling/docs/frontend/lib/data-card-utils.ts` | 13 | `METADATA_KEYS` includes `_unprocessed` | Add `_state` keys (J) |
| `tooling/rendering/data_card.py` | 16 | `METADATA_KEYS` includes `_unprocessed` | Add `_state` keys (J) |
| `cli/preview.py` | branches | `_unprocessed`, `metadata.reason` | Read `_state` (J) |
| `vscode-extension/src/views/queryResultsPanel.ts` | 187 | `METADATA_KEYS` inline Set | Add `_state` keys (J) |

---

## 7. Tied Tests (38 files, ~392 occurrences)

| Test File | Relevant Strings | Count |
|-----------|-----------------|-------|
| `tests/unit/core/test_upstream_unprocessed_filter.py` | FILTER_PHASE, ProcessingStatus.UNPROCESSED, _unprocessed, guard_skip, upstream_unprocessed | 52 |
| `tests/unit/storage/test_sqlite_backend.py` | set/clear_disposition, tombstone | 43 |
| `tests/unit/core/test_result_collector.py` | ProcessingStatus.UNPROCESSED, _unprocessed, guard_skip, set/clear_disposition | 38 |
| `tests/unit/processing/test_record_helpers.py` | _unprocessed, guard_skip, tombstone | 36 |
| `tests/unit/workflow/test_pipeline_guard_skip_disposition.py` | _unprocessed, guard_skip, set/clear_disposition, tombstone | 25 |
| `tests/processing/test_guard_skip_disposition.py` | _unprocessed, guard_skip, set/clear_disposition, tombstone | 24 |
| `tests/unit/workflow/test_circuit_breaker.py` | guard_skip, set/clear_disposition | 16 |
| `tests/simulation/simulate_batch_resubmission.py` | FILTER_PHASE, _unprocessed, guard_skip, set/clear_disposition, tombstone | 14 |
| `tests/integration/test_storage_backend_integration.py` | set/clear_disposition, tombstone | 13 |
| `tests/unit/utils/test_passthrough_builder.py` | _unprocessed, metadata.reason, tombstone | 11 |
| `tests/unit/input/test_initial_pipeline_return.py` | _unprocessed, guard_skip, set/clear_disposition, tombstone | 11 |
| `tests/unit/storage/test_sqlite_dispositions.py` | set/clear_disposition | 10 |
| `tests/unit/cli/test_preview_namespace.py` | _unprocessed, guard_skip, tombstone | 10 |
| `tests/unit/processing/test_online_llm_strategy.py` | ProcessingStatus.UNPROCESSED, _unprocessed, guard_skip, upstream_unprocessed | 9 |
| `tests/unit/workflow/test_batch_pipeline_tombstone.py` | tombstone | 9 |
| `tests/unit/core/test_enrichment_unification.py` | guard_skip | 8 |
| `tests/unit/workflow/test_pipeline_hitl_file_mode.py` | _unprocessed, tombstone | 7 |
| `tests/unit/workflow/test_coordinator_sequential.py` | set/clear_disposition | 6 |
| `tests/unit/cli/test_execution_renderer.py` | UPSTREAM_SKIP_PREFIX, WHERE_SKIP_REASON, guard_skip | 6 |
| `tests/unit/workflow/test_file_mode_guard_prefilter.py` | ProcessingStatus.UNPROCESSED, _unprocessed | 6 |
| `tests/unit/test_async_evaluation_wiring.py` | set/clear_disposition | 6 |
| `tests/unit/workflow/test_pipeline_file_mode_tool.py` | _unprocessed, tombstone | 5 |
| `tests/unit/core/test_data_generator_unprocessed.py` | _unprocessed, upstream_unprocessed | 4 |
| `tests/unit/test_sqlite_concurrency.py` | set/clear_disposition | 4 |
| `tests/unit/workflow/test_limits.py` | set/clear_disposition | 3 |
| `tests/unit/processing/test_unified_processor.py` | _unprocessed, tombstone | 2 |
| `tests/unit/record/test_envelope.py` | _unprocessed | 2 |
| `tests/core/test_task_preparer.py` | guard_skip | 2 |
| `tests/integration/test_retry_reprompt_audit.py` | guard_skip | 2 |
| `tests/unit/core/test_guard_observability.py` | _unprocessed, tombstone, upstream_unprocessed | 2 |
| `tests/workflow/test_stale_completion_verification.py` | set/clear_disposition | 2 |
| `tests/unit/workflow/test_executor_lifecycle.py` | set/clear_disposition | 1 |
| `tests/unit/llm_invocation/test_batch_provider_edge_cases.py` | _unprocessed | 1 |
| `tests/tooling/rendering/test_data_card.py` | _unprocessed | 1 |
| `tests/unit/validation/test_guard_skipped_observe_refs.py` | guard_skip | 1 |
| `tests/preprocessing/test_guard_evaluator.py` | guard_skip | 1 |
| `tests/unit/core/test_reprompt_service.py` | guard_skip | 1 |
| `tests/unit/wave3/test_enrichment_complete_event.py` | set/clear_disposition | 1 |
