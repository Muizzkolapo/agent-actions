# Phase 3 Recovery Surface Inventory

**Generated:** 2026-05-02
**Baseline commit:** integration/error-recovery-unification (from main at a151c95)

---

## Recovery function call graph

```
BatchProcessingService._process_original_batch()  [processing.py:436]
  ├── retry_ops.submit_retry_batch()              → async retry submission
  ├── check_and_submit_reprompt()                 → initial evaluation + reprompt submission
  │     ├── reprompt_ops.build_evaluation_loop()
  │     ├── EvaluationLoop.split()
  │     ├── EvaluationLoop.tag_graduated()
  │     ├── reprompt_ops.submit_reprompt_batch()
  │     └── reprompt_ops.apply_exhausted_reprompt_metadata()
  └── finalize_batch_output()

BatchProcessingService._process_recovery_batch()  [processing.py:370]
  └── process_recovery_batch()
        ├── handle_retry_recovery()
        │     ├── retry_ops.process_retry_results()
        │     ├── retry_ops.submit_retry_batch()
        │     ├── retry_ops.build_exhausted_recovery()
        │     ├── check_and_submit_reprompt()
        │     └── finalize_batch_output()
        └── handle_reprompt_recovery()
              ├── reprompt_ops.build_evaluation_loop()
              ├── EvaluationLoop.split()
              ├── EvaluationLoop.tag_graduated()
              ├── reprompt_ops.submit_reprompt_batch()
              ├── reprompt_ops.apply_exhausted_reprompt_metadata()
              ├── retry_ops.build_exhausted_recovery()
              └── finalize_batch_output()

BatchRetryService (facade) [retry.py]
  ├── retrieve_results_with_retry()  [blocking path]
  │     ├── retry_ops.resubmit_missing_records()
  │     ├── retry_ops.build_exhausted_recovery()
  │     └── reprompt_ops.validate_and_reprompt()
  │           ├── reprompt_ops.build_evaluation_loop()
  │           ├── EvaluationLoop.split() / tag_graduated() / build_resubmission()
  │           └── reprompt_ops.apply_exhausted_reprompt_metadata()
  └── delegators: submit_retry_batch, process_retry_results,
      build_exhausted_recovery, validate_and_reprompt, validate_results,
      submit_reprompt_batch, process_reprompt_results,
      apply_exhausted_reprompt_metadata, serialize_results, deserialize_results
```

---

## LOC baselines

| File | Lines | Phase 3 Target |
|------|-------|----------------|
| `llm/batch/services/processing_recovery.py` | 533 | ~250 |
| `llm/batch/services/reprompt_ops.py` | 628 | ~400 |
| `llm/batch/services/retry_ops.py` | 250 | ~200 |
| `llm/batch/services/retry.py` | 338 | ~120 (typed) |
| **Total** | **1,749** | **~1,030** |
| **New:** `processing/evaluation/exhaustion.py` | — | ~60 |

Note: Contract estimated 1,527 baseline. Actual is 1,749 (retry.py is 338 not 113 — includes `retrieve_results_with_retry` blocking path).

---

## Recovery metadata types

| Type | Fields | Serialized to |
|------|--------|---------------|
| `RetryMetadata` | `attempts: int`, `failures: int`, `succeeded: bool`, `reason: str`, `timestamp: str\|None` | `_recovery.retry` in output JSON |
| `RepromptMetadata` | `attempts: int`, `passed: bool`, `validation: str` | `_recovery.reprompt` in output JSON |
| `EvaluationMetadata` | `passed: bool`, `strategy_name: str` | `_recovery.evaluation` in output JSON |
| `RecoveryMetadata` | `retry: RetryMetadata\|None`, `reprompt: RepromptMetadata\|None`, `evaluation: EvaluationMetadata\|None` | `_recovery` container in output JSON |

All defined in `agent_actions/processing/types.py` (lines 36–106).

---

## RecoveryState fields

Dataclass in `agent_actions/llm/batch/infrastructure/recovery_state.py`:

| Field | Type | Phase | Default |
|-------|------|-------|---------|
| `phase` | `str` | cross | required ("retry"\|"reprompt"\|"done") |
| `retry_attempt` | `int` | retry | 0 |
| `retry_max_attempts` | `int` | retry | 3 |
| `missing_ids` | `list[str]` | retry | [] |
| `record_failure_counts` | `dict[str, int]` | retry | {} |
| `reprompt_attempt` | `int` | reprompt | 0 |
| `reprompt_max_attempts` | `int` | reprompt | 2 |
| `validation_name` | `str\|None` | reprompt | None |
| `reprompt_attempts_per_record` | `dict[str, int]` | reprompt | {} |
| `validation_status` | `dict[str, bool]` | reprompt | {} |
| `on_exhausted` | `str` | reprompt | "return_last" |
| `accumulated_results` | `list[dict]` | cross | [] |
| `graduated_results` | `list[dict]` | cross | [] |
| `evaluation_strategy_name` | `str\|None` | cross | None |

Serialized via `to_dict()` → `atomic_json_write()` to `batch/.recovery_state_{file_name}.json`.
Deserialized via `RecoveryState(**json.load(f))` — additive-only changes safe.
Validation: `__post_init__` checks `phase` is in `{"retry", "reprompt", "done"}`.

---

## Exhaustion sites (consolidation targets)

| Function | Location | Recovery type | Raises? | Callers |
|----------|----------|---------------|---------|---------|
| `apply_exhausted_reprompt_metadata` | `reprompt_ops.py:582` | reprompt | Yes, if `on_exhausted="raise"` | `validate_and_reprompt` (line 191), `processing_recovery.py` via facade (lines 319, 408) |
| `build_exhausted_recovery` | `retry_ops.py:212` | retry | Never | `handle_retry_recovery` (line 189), `handle_reprompt_recovery` (line 338), `retrieve_results_with_retry` (line 151) |
| Inline exhaustion | `processing_recovery.py` (handle_reprompt_recovery) | reprompt | Via `apply_exhausted_reprompt_metadata` | — |

Additional `on_exhausted` handling outside target files:
- `batch_result_strategy.py:427-442` — retry exhaustion in online batch path (raises if `on_exhausted="raise"`)
- `result_collector.py:564-601` — `_check_retry_exhaustion()` raises if `on_exhausted="raise"`
- `processing/recovery/reprompt.py:131-143` — online RepromptService exhaustion

---

## Finalization call sites

| Location | File | Line | Context |
|----------|------|------|---------|
| `handle_retry_recovery` | `processing_recovery.py` | 210 | After retry exhausted + no reprompt |
| `handle_reprompt_recovery` | `processing_recovery.py` | 259 | After all graduated |
| `handle_reprompt_recovery` | `processing_recovery.py` | 343 | After exhaustion (return_last path) |
| `_process_original_batch` | `processing.py` | 502 | No recovery needed (direct finalize) |
| `_finalize_batch_output` (delegator) | `processing.py` | 575–592 | Wrapper that delegates to processing_recovery impl |

The `processing.py` delegator (line 575) is a method that `import`s and delegates to `processing_recovery.finalize_batch_output`. It's called at line 502.

---

## `build_evaluation_loop` import sites

| Location | File | Line | Context |
|----------|------|------|---------|
| Definition | `reprompt_ops.py` | 81 | Factory function |
| Internal use | `reprompt_ops.py` | 155 | Inside `validate_and_reprompt` |
| Inline import 1 | `processing_recovery.py` | 251 | Inside `handle_reprompt_recovery` |
| Inline import 2 | `processing_recovery.py` | 386 | Inside `check_and_submit_reprompt` |

Two inline imports in `processing_recovery.py` (deferred to avoid circular imports). Both use `from agent_actions.llm.batch.services.reprompt_ops import build_evaluation_loop`.

---

## `check_and_submit_reprompt` call sites

| Location | File | Line | Context |
|----------|------|------|---------|
| Definition | `processing_recovery.py` | 363 | The function itself |
| Call (retry exhaustion) | `processing_recovery.py` | 193 | From `handle_retry_recovery` after retry exhausted |
| Import + delegation | `processing.py` | 34, 561 | `_check_and_submit_reprompt_impl` delegator |
| Call (original batch) | `processing.py` | 489 | From `_process_original_batch` when no missing IDs |

---

## BatchRetryService facade delegations

| Method | Delegates to | Module |
|--------|-------------|--------|
| `retrieve_results_with_retry` | (own implementation, calls below) | retry.py |
| `_resubmit_missing_records` | `retry_ops.resubmit_missing_records` | retry_ops.py |
| `submit_retry_batch` | `retry_ops.submit_retry_batch` | retry_ops.py |
| `process_retry_results` | `retry_ops.process_retry_results` | retry_ops.py |
| `build_exhausted_recovery` | `retry_ops.build_exhausted_recovery` | retry_ops.py |
| `validate_and_reprompt` | `reprompt_ops.validate_and_reprompt` | reprompt_ops.py |
| `validate_results` | `reprompt_ops.validate_results` | reprompt_ops.py |
| `submit_reprompt_batch` | `reprompt_ops.submit_reprompt_batch` | reprompt_ops.py |
| `process_reprompt_results` | `reprompt_ops.process_reprompt_results` | reprompt_ops.py |
| `apply_exhausted_reprompt_metadata` | `reprompt_ops.apply_exhausted_reprompt_metadata` | reprompt_ops.py |
| `serialize_results` (static) | inline | retry.py |
| `deserialize_results` (static) | inline | retry.py |

Total: 12 methods (10 delegations + 2 static utilities).

---

## Test coverage by recovery path

| Path | Test file(s) | Coverage | Critical gaps |
|------|-------------|----------|---------------|
| EvaluationLoop | `test_evaluation_loop.py` (46 tests) | Full | None |
| EvaluationLoop batch integration | `test_evaluation_loop_batch.py` (30+ tests) | Good | None |
| Recovery state graduated | `test_recovery_state_graduated.py` | Graduated pool | None |
| Reprompt selective resubmit | `test_reprompt_selective_resubmit.py` | Split + resubmit logic | None |
| Async evaluation wiring | `test_async_evaluation_wiring.py` | `handle_reprompt_recovery` + `check_and_submit_reprompt` | Indirect only |
| Retry/reprompt audit | `test_retry_reprompt_audit.py` (integration) | End-to-end composed | None |
| Batch resubmission (simulation) | `simulate_batch_resubmission.py` | Multi-cycle | Manual only |
| **`process_recovery_batch` dispatch** | — | **ZERO** | **FM15: no direct tests** |
| **`handle_retry_recovery` full** | — | **ZERO** | **FM15: only indirect via wiring tests** |
| **`finalize_batch_output`** | — | **ZERO** | **FM15: event payload untested** |
| **Composed exhaustion (retry→reprompt→exhausted)** | — | **ZERO** | **FM3/FM5: no dedicated tests** |
| **Phase transitions (retry exhausted → reprompt)** | — | **ZERO** | **FM5: critical path untested** |
| **RecoveryState serialization roundtrip (all fields)** | Partial (graduated only) | Partial | Full-field roundtrip missing |

---

## Additional observations

### Atomic write usage
- `RecoveryStateManager.save()` uses `atomic_json_write` (line 92) — correct.
- `finalize_batch_output` writes output via framework path (should be verified in E).

### Dynamic imports
- `processing_recovery.py` uses 2 deferred `from ... import build_evaluation_loop` (lines 251, 386).
- These are inside function bodies to avoid circular imports.
- Moving `build_evaluation_loop` without updating BOTH sites causes ImportError at async recovery time.

### `on_exhausted` handling outside target files
- `batch_result_strategy.py` has its own exhaustion logic (lines 427–442) — NOT in scope for Phase 3 consolidation (online batch path, separate concern).
- `result_collector.py` has `_check_retry_exhaustion()` (lines 564–601) — separate post-processing check, not a consolidation target.
- `processing/recovery/reprompt.py` has online RepromptService — explicitly OUT OF SCOPE per contract.
