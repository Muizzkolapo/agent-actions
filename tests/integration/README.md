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

---

## test_repair_loop_audit.py

Audit of the expectations repair loop (`expect:` with a `repair:` policy). 18 tests, all driven through the **real `agac run` CLI against a project scaffolded on disk**. Only the provider call is mocked, so the config loader, action expander, preflight, invocation strategy, loop, record envelope and SQLite store all execute for real.

### Why CLI-level rather than service-level

The two genuine bugs this subsystem shipped with were both invisible to tests that mocked the generation seam directly:

- a real online record arrives as a **length-1 list**, not a bare dict, so validation silently never ran;
- `agent_config["expect"]` was **never forwarded** through the action expander.

Both were caught only by driving the actual CLI. These tests keep that path covered.

### Coverage

| Class | Tests | What it covers |
|-------|-------|----------------|
| `TestRepairSucceeds` | 4 | Regenerated record ships; a passing first attempt costs one call; `auto` sends the failure detail, the hint and the previous output to the model; `retry` re-sends the original prompt |
| `TestStructuralGate` | 3 | A schema-violating record is repaired; the `_structural` failure reaches the repair prompt; observe mode never applies the gate |
| `TestExhaustion` | 5 | `return_last` ships the annotated record; `fail` refuses to ship it; `fail` matches reprompt exhaustion exactly; `raise` halts the run; `max_iterations` counts the first generation |
| `TestObserveMode` | 2 | One call, verdict attached, record unchanged — passing and failing |
| `TestVerdictAsAGate` | 2 | A repaired record satisfies a downstream `guard:` on `expect.overall_pass`; an unrepaired one is filtered |
| `TestExtensionPointsDriveRepair` | 2 | A project's own `@expectation_check` from `tools/` drives regeneration and its detail reaches the prompt; an `expression` rule does the same |

### Mutation-verified

The suite was checked against four deliberate regressions in `agent_actions/expectations/service.py`; each is caught:

| Mutation | Tests that fail |
|---|---|
| Loop never iterates (`iterations = 1`) | 14 |
| `auto` degrades to `retry` (composed feedback never sent) | 3 |
| Structural gate disabled | 1 |
| `on_exhausted: raise` ignored | 1 |

### Running

```bash
pytest tests/integration/test_repair_loop_audit.py -v
```

Deterministic, no network, ~1.4s.

### What is deliberately not here

The repair-mode **preflight guards** live in `tests/unit/validation/test_expectations_validator.py`, not here. Driving them through the CLI produced two tests that passed while proving nothing: a `granularity: File` action is rejected by an earlier validator, so the run failed for an unrelated reason and stayed green with the whole `expect:` block deleted; and a `run_mode: batch` action never reaches the mocked provider seam, so it hit the real batch submission path and made a live HTTPS request.

### Isolation

A real run touches three process-global singletons. The fixture restores all of them — the path manager, the guard filter's thread pool, and the expectation type registry (`tools/` discovery registers user checks into it) — and scopes `OPENAI_API_KEY` to the test. Leak-checked: running the suite in a fresh interpreter leaves the registry and environment unchanged.

Adding this suite is what surfaced a latent bug in `reset_global_guard_filter()`: it shut down the filter's pool without clearing the guard *evaluator* singleton that caches it, so nine unrelated tests failed depending on ordering. Fixed in the same branch.

## test_expectation_authors.py

Seventeen ways to write an `expect:` block, each a working project under
`fixtures/expectation_authors/` and each driven through the real preflight
(`WorkflowInspector.validate()`, the same read-only path `agac inspect` uses).

What is pinned is the verdict, and for a refusal the phrase that names the
correction. A refusal that does not say what to change is worth no more than
silence, and one of these fixtures exists because a refusal once told the author
to do the thing they had already done.

| Author | What they write | Verdict |
|---|---|---|
| `field_scoped_rules` | Rules on the fields they test, severity error and warn, a bare expect block | accepted |
| `inline_rules` | Rules in the action's own expect block, each naming its field | accepted |
| `repair_auto` | `repair: auto` with a bounded iteration count | accepted |
| `shared_suite` | One rules-only file, two actions bound to it by name | accepted |
| `row_condition_on_optional_field` | A rule gated on a field the record may not carry | accepted |
| `custom_check` | An `@expectation_check` of their own, discovered from `tools/` | accepted |
| `verdict_guard` | A downstream action guarded on the verdict | accepted |
| `judge_votes_and_budget` | A judged rule with votes, a run budget, and `severity: info` | accepted |
| `pair_and_pattern_rules` | A rule over two fields, and a pattern rule that negates | accepted |
| `record_expression` | A cross-field condition that belongs to no single field | accepted |
| `batch_field_rules` | Field-declared rules under `run_mode: batch`, nothing judged | accepted |
| `tool_action` | An expect block on a `kind: tool` action | accepted |
| `array_member_rule` | A whole-list rule on the field and a per-item rule under `items` | refused — a selector reaches top-level fields only |
| `many_mistakes` | Five different mistakes in one block | refused — all five, each naming its own correction |
| `judged_context_under_batch` | A judged rule reading another action, under `run_mode: batch` | refused — no context source exists in batch |
| `old_flat_shape` | A whole file still written with flat arguments and `severity: fail` | refused — arguments under `params:`, `fail` is now `error` |
| `repair_auto_at_file_granularity` | `repair: auto` where one call produces the whole file | refused — one failing record would regenerate all of them |

No provider is called: preflight is the deterministic half, and it is the half
that decides whether an author's config is ever allowed to run. The suite takes
about a second.

Adding an author means adding the project directory and its verdict; a fixture
with no verdict fails `test_every_author_has_a_verdict`.

## test_runtime_probes.py

Runtime failure behaviour driven through the real CLI. Ported from a real
project, where these existed as throwaway workflows for watching failure
handling live against a local model.

Fixture: `fixtures/runtime_probes/` — one project, three workflows, all offline
against `agac-provider`.

### Why CLI-level rather than unit-level

Every mechanism here already has unit coverage. What has none is the seam
between the layers: the staging guard rejects a file, the pipeline decides
whether that is fatal, the summary counts what ran, and the status file records
what happened. Those are four layers, and a unit test sees one at a time.

| Workflow | What it pins |
|---|---|
| `staging_namespace_collision` | Every record carries a field named `source`. The run must fail, name the field, and print the rename remedy. |
| `partial_file_rejection` | One clean file, one rejected. Only the clean record persists — and the action still reports a clean success (see below). |
| `repair_exhaustion` | A rule that can never be satisfied. `on_exhausted: return_last` must keep the record and attach its last verdict. |

### The known defect

`test_a_partially_rejected_action_is_not_reported_as_a_clean_success` is a
strict `xfail`. A staging file rejected at load leaves no durable trace: the
action records status `completed`, the run exits 0, and the only evidence is a
log line. The same workflow with *every* file rejected exits 1 — the silence is
specific to the partial case.

It is strict so that fixing the defect fails the suite until the marker is
removed.

### Not ported

The real project also carried a batch retry-exhaustion probe. It drives failures
through `OLLAMA_FAIL_FIRST_N`, which only the `ollama` client implements, so it
needs a live Ollama and cannot run here. `agac-provider`'s batch client has no
failure path at all. Porting it means giving that provider count-based injection
mirroring the ollama one — worth doing, but it is a change to a shipped provider
rather than a test addition.
