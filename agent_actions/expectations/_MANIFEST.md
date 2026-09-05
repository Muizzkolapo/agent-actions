# Expectations

Declarative output expectations: typed rules an action's output must satisfy,
their results, and the service that runs them around generation.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `types.py` | Module | Defines `Expectation`, `Suite`, `Outcome`, `SuiteResult`. `Expectation` reads type-specific arguments from its `params:` block and forbids unknown rule keys; `definition_hash()` digests what a rule tests, ignoring its id. | `validation`, `typing` |
| `fields.py` | Module | Turns a `field:` selector into check inputs via `resolve()` — bare name yields the whole value, `name[*]` one per element, a list of names one combined input. `referenced_names()` backs the preflight check. | `validation` |
| `registry.py` | Module | Deterministic expectation types and `register`/`get`/`known_types`. A check returns `(passed, detail)`; `detail` names the observed value, since the repair composer reads it. | `validation` |
| `loader.py` | Module | Builds a `Suite` from a schema-path file's rules — those declared under a `fields:` entry, which carry that field as their selector, and those in the file's own `expectations:` block (`load_named_suite` via `SchemaLoader`, `build_suite_from_schema_data`) — or from an action's inline list (`build_inline_suite`). | `output` |
| `judge.py` | Module | `llm_judge` invocation, `votes:` majority voting, the per-action verdict cache (`CachedJudge`), and the per-run judge budget (`JudgeBudget`). `invoke_judge()` parses the model's verdict as strict JSON text, never a vendor-native structured-output schema — a malformed response is always a failure. | `processing` |
| `runner.py` | Module | Evaluates every expectation against one record via `run_suite()`. Deterministic types call `registry.get(...).check()` directly; `llm_judge` dispatches through an injected `judge` callable and an optional `context_source`, keeping this module free of any pipeline or network import. Every rule runs even after an earlier failure. A missing field, an unresolvable `context:` ref, or a judge dispatched with no caller wired are each handled explicitly — the first two as failed outcomes, the third as a raised error. | `validation` |
| `service.py` | Module | Runs one generation through `ExpectationService.execute()`, taking the same `llm_operation` callable contract as `RepromptService`. Unwraps a real online record's length-1 list response before validating — `create_dynamic_agent` always returns `list[Any]`, so a bare dict is never what a real single-record call produces. `create_expectation_service_from_config()` is the composition point: it builds a `CachedJudge`/`JudgeBudget` pair from `agent_config`/`judge_budget` only when a suite actually contains `llm_judge`, and injects the composed dispatcher into `run_suite()`. `attach_verdict()` writes the verdict under the record's `expect` key. | `processing` |

## Project Surface

| Symbol | File | Interaction | Config Key |
|--------|------|-------------|------------|
| `load_named_suite` | `schema/{workflow}/{name}.yml` | Reads | `schema_path` |
| `create_expectation_service_from_config` | `agent_config/{workflow}.yml` | Reads | `actions[].expect` |
| `attach_verdict` | `agent_io/target/{action}/` | Writes | — |
| `CachedJudge` | agent's own `model_vendor`/`model_name` | Reads | `actions[].expect.expectations[].model` |
| `JudgeBudget` | — | Bounds | `actions[].expect.judge_budget` |

**Internal only**: `Outcome`, `SuiteResult`, `ExpectationType`, `ExpectationRunResult`, `resolve`, `referenced_names`, `resolve_context` -- no direct project surface.

## Dependencies

| Package | Direction | Why |
|---------|-----------|-----|
| `processing` | inbound | `OnlineStrategy` composes `ExpectationService` as the outermost recovery layer |
| `validation` | inbound | `expectations_validator` reads the registry and field selectors at preflight |
| `config` | outbound | `ExpectConfig` lives in `config/schema.py` |
| `output` | outbound | `loader.py` resolves suite names through `SchemaLoader`, exactly as `schema:` resolves |

## Notes

The engine core (`types`, `fields`, `registry`, `loader`, `runner`) imports nothing
from `workflow/`, `processing/` or `storage/`. `service.py` is the only module here
that knows about the pipeline. Keeping that boundary is what lets the runner be
tested without a network and the CLI start without loading the workflow stack.

A named `suite:` reference (or the bare-block default, which reads the action's
own schema file) is only resolvable when a project root is available.
`InvocationStrategyFactory` (the only production caller of
`create_expectation_service_from_config` as of Plan 1) does not thread one
through, so those modes raise `ConfigurationError` unconditionally today even
for an existing file — only the inline `expectations:` form works end to end.
Threading the project root through `OnlineLLMStrategy` and its three callers
(`workflow/pipeline.py`, `prompt/data_generator.py`,
`input/preprocessing/staging/initial_pipeline.py`) is required before the
file-backed forms are usable, and is out of scope for this plan.

A judged expectation's `context:` refs are only auto-injected into the
producing action's own `context_scope.observe` for the inline `expectations:`
form. `ActionExpander._create_agent_from_action` — the only place this
injection can happen — has no suite-loading capability, so a named `suite:`'s
`context:` refs are inert even on the day project-root threading
closes the gap above; that fix only makes `suite:` mode load, it does not
make its `context:` refs reach `observe:`. Both share a root cause but are two
different pieces of missing plumbing.

Two bugs found and fixed by this plan's mandated real-project verification
(driving a mocked end-to-end `agac run` through the actual CLI, not a
synthetic dict or direct service construction — see Plan 2 Task 8):

1. `ExpectationService.execute()`'s `isinstance(response, dict)` check never
   matched what a real online single-record call produces. `create_dynamic_agent`
   always returns `list[Any]`; a real record arrives as a length-1 list, not a
   bare dict. Expectation validation — Plan 1's deterministic checks and this
   plan's `llm_judge` alike — silently never ran for a real `agac run`, only
   in unit tests that mocked `_call_llm`/`generate` with a bare dict directly.
   Fixed: a length-1 list is unwrapped before validation; a longer list (file
   granularity) is left alone, since `expect:` has no per-item semantics
   defined for that shape.
2. `agent_config["expect"]` was never forwarded — the exact class of bug Plan 1
   Task 9 already found and fixed once for the `expect:` block itself (see the
   git history on `output/response/expander.py`); this plan re-verified that
   fix still holds and found no regression.

A narrow, real, and deliberately **not** worked around side effect of fix 1,
found by review: `agent_actions/processing/strategies/online_llm.py` passes
the SAME (now-unwrapped) `response` on to `MetadataExtractor.extract_from_response`
as `raw_response`, which branches on `isinstance(response, dict)` — a dict routes
to `_extract_from_dict`, which reads `model`/`finish_reason`/`stop_reason`/
`status_code`/`http_status`/`request_id`/`id`/`usage` keys as provider metadata;
a list routes to `_extract_from_object` (attribute/`hasattr`-based), which
returns near-empty for a plain `list`. Before this fix, EVERY online action's
`raw_response` was always a list (since `create_dynamic_agent` always returns
one) — so `_extract_from_object`'s near-empty result was universal, and metadata
extraction from response content was already a no-op for every online action,
`expect:`-configured or not. This fix makes an `expect:`-configured action's
`raw_response` a dict for the first time, so `_extract_from_dict` fires for
that action category specifically — if its business schema happens to emit a
field literally named one of the keys above (`id` is the most plausible),
that value is misread as provider metadata. `hitl.py`'s own list-unwrap
(`processing/strategies/hitl.py:112-120`, "Unwrap single-item list from
invocation service") avoids this exact trap by keeping the *original*
`raw_response` for its `ProcessingResult` and using a separate unwrapped
variable only for its own internal decision logic — deliberately not mirrored
here, because doing so would mean `ExpectationRunResult.response` (returned to
`OnlineStrategy.invoke()` and merged with the verdict via `attach_verdict`)
would need to become list-shaped again after annotation, which would in turn
require a third file's (`online_llm.py`) contract to change to keep `_transform_response`
happy — a bigger, riskier change than this plan's real bug fix, for a narrow
key-name-collision that a project can trivially avoid by not naming an output
field `id`/`model`/`usage`/`finish_reason`/`stop_reason`/`status_code`/
`http_status`/`request_id`. Flagged for whoever owns `online_llm.py`/`enrichment.py`
next, not fixed here.

One confirmed, pre-existing bug found and **not** fixed (out of scope — it is
in shared parallel-execution infrastructure, not this package):
`action_executor.py:compute_execution_levels` buckets `execution_order` into
parallel batches using only the raw `dependencies:` field, not the fuller
`infer_dependencies()` graph that `determine_execution_order()` (the ordering
pass) already uses. A `context:`-only consumer sharing its raw `dependencies:`
with its context source (e.g. both declare only `dependencies: ["raw_input"]`)
gets bucketed into the *same parallel level* as that source, so the source's
output does not exist yet when the consumer's prompt is built — `resolve_context`
does not raise (the key is present in `llm_context`, just holding a stale/`None`
value), so this fails silently rather than loudly. Reproduced concretely: a
probe workflow with `extract_context` and `brainstorm` both declaring only
`dependencies: ["raw_input"]`, `brainstorm`'s judge declaring
`context: [extract_context.source_context]`, ran the judge with grounding
text `None` until `extract_context` was added to `brainstorm`'s own
`dependencies:` explicitly. This is not new — the same class of bug can
already affect any other `context_scope.observe`-only cross-reference
(`dep_observe_validator.py` deliberately does not require the reverse
direction, since an unlisted-dependency observe ref is the sanctioned
context-source pattern). Workaround today: list every `context:`-referenced
action in the consumer's own `dependencies:` too, even though nothing else
requires it. Proper fix is in `action_executor.py`, not this package.
