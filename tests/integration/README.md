# Integration Tests

## test_retry_reprompt_audit.py

Comprehensive audit of the retry and reprompt recovery system. 85 tests covering every failure mode, edge case, and cross-layer interaction.

### What the system does

| Layer | Purpose | Triggers on |
|-------|---------|-------------|
| **Retry** | Re-execute LLM call on transport failure | `NetworkError`, `RateLimitError` |
| **Reprompt** | Re-execute LLM call with validation feedback | UDF or schema validation failure |
| **Composed** | Retry wraps reprompt — transport resilience inside validation loop | Both |

### Test coverage by path type

```
Failure / exhaustion .... 23 tests   (27%)
Happy / recovery ........ 17 tests   (20%)
Edge cases .............. 15 tests   (18%)
Classification .......... 9  tests   (11%)
Serialization ........... 8  tests   (9%)
Invalid input ........... 6  tests   (7%)
Negative assertion ...... 4  tests   (5%)
Event verification ...... 3  tests   (4%)
                          --
                          85 tests   (~70% non-happy-path)
```

### Test classes

| Class | Tests | What it covers |
|-------|-------|----------------|
| `TestRetryService` | 20 | Network/rate-limit retry, non-retriable immediate raise, backoff formula + cap, exhaustion, metadata accuracy, error classification |
| `TestRetryServiceFactory` | 4 | Config → service creation: None, disabled, defaults, custom params |
| `TestRepromptService` | 16 | Feedback appending, first/multi-attempt pass, return_last/raise exhaustion, guard-skip bypass, validator exceptions (4 types), exception propagation, per-call override |
| `TestRepromptServiceFactory` | 5 | Config → service creation: None, missing validation, validator override |
| `TestComposedValidation` | 7 | Short-circuit chaining, retry-wraps-reprompt, retry exhaustion inside reprompt, guard-skip through combined path |
| `TestEventLogging` | 5 | RetryExhaustedEvent, RepromptValidationFailedEvent, DataValidation events per UDF call, events NOT fired on success |
| `TestBatchRetry` | 8 | Metadata serialization round-trip (full, retry-only, reprompt-only, none, failed), exhaustion markers, mixed batch |
| `TestBuildValidationFeedback` | 3 | Format, non-serializable fallback, delimiter |
| `TestUDFRegistry` | 6 | Register/retrieve, missing raises, overwrite warns, decorator preserves behavior, exception propagates + fires event |
| `TestRetryResultProperties` | 3 | `needed_retry` property semantics |
| `TestRecoveryMetadataTypes` | 5 | `to_dict()` serialization, optional timestamp, `is_empty()` |

### Spec failure modes — all covered

These are the failure modes from [025-retry-reprompt-audit](../../specs/new/025-retry-reprompt-audit.md):

| Failure Mode | Test(s) |
|---|---|
| Retry swallowing non-retriable errors | `test_no_retry_on_non_retriable_error[ValueError/VendorAPIError]` |
| Reprompt not appending feedback | `test_feedback_appended_to_prompt`, `test_feedback_rebuilds_from_original_each_time` |
| Metadata missing or wrong | `test_metadata_attempts_match_actual`, `test_metadata_passed_reflects_outcome_*` |
| Batch retry losing records | `test_exhausted_records_marked_failed`, `test_failed_result_error_field_roundtrip` |
| Exhaustion with `raise` not raising | `test_exhaustion_raise`, `test_exhaustion_raise_via_execute_override` |
| Guard-skipped actions running reprompt | `test_guard_skip_bypasses_validation`, `test_guard_skip_during_retry_plus_reprompt` |
| Event logging gaps | `test_retry_exhausted_event_fired`, `test_reprompt_failed_event_fired`, `test_data_validation_events_per_attempt` |

### Cross-layer failure tests

These verify behavior when multiple recovery layers interact:

- **`test_retry_wraps_reprompt`** — retry fails once inside reprompt, recovers, validation passes
- **`test_retry_exhaustion_inside_reprompt`** — retry exhausts completely, reprompt sees `(None, False)`, treats as guard-skip
- **`test_guard_skip_during_retry_plus_reprompt`** — guard skip propagates through both layers without crashing

### Running

```bash
pytest tests/integration/test_retry_reprompt_audit.py -v
```

All tests are deterministic, mock all I/O, and complete in < 1 second.
