# Expectations

Declarative output expectations: typed rules an action's output must satisfy,
their results, and the service that runs them around generation.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `types.py` | Module | Defines `Expectation`, `Suite`, `Outcome`, `SuiteResult`. `Expectation` reads type-specific arguments from its `params:` block and forbids unknown rule keys; `definition_hash()` digests what a rule tests, ignoring its id. `field:` is required for every type except the record-scoped ones (`expression`), which must omit it — enforced by a model validator so every construction path gets the same rule. | `validation`, `typing` |
| `fields.py` | Module | Turns a `field:` selector into check inputs via `resolve()` — bare name yields the whole value, `name[*]` one per element, a list of names one combined input. `referenced_names()` backs the preflight check. | `validation` |
| `registry.py` | Module | Deterministic expectation types and `register`/`get`/`known_types`, plus the public `expectation_check` decorator for project-defined types (exported from `agent_actions`). Every registered type also accepts the universal `row_condition` argument, unioned in `ExpectationType` itself so no registration path can omit it. A check returns `(passed, detail)`; `detail` names the observed value, since the repair composer reads it. User registration happens as a `tools/` import side effect during UDF discovery; collision policy is three-way — shadowing a built-in raises, the same name from a different file or function raises `DuplicateFunctionError`, and true re-import of the same function is idempotent. | `validation` |
| `expression.py` | Module | Parses and evaluates an `expression` rule's condition against the whole record. `condition_holds()` is the same evaluation with the opposite error contract — it raises rather than reporting false — for callers deciding whether a rule applies, which must not read "we could not tell" as "it does not apply". Reuses the guard machinery verbatim — `GuardParser`'s blocklist plus the `WhereClauseParser` grammar — so a condition string is portable between `guard:` and `expect:` unchanged; `udf:` conditions are rejected with a pointer to `expectation_check`. A false condition's detail carries the values of every field the condition read; a missing field or an unquoted-literal semantic error becomes a failed outcome carrying the evaluator's own message. Imports from `guards/` and `input/preprocessing/parsing/` are deliberate and stay within the pipeline-free rule, which bans only `workflow`/`processing`/`storage`. | `validation` |
| `loader.py` | Module | Builds a `Suite` from a schema-path file's rules — those declared under a `fields:` entry, which carry that field as their selector, and those in the file's own `expectations:` block (`load_named_suite` via `SchemaLoader`, `build_suite_from_schema_data`) — or from an action's inline list (`build_inline_suite`). | `output` |
| `judge.py` | Module | `llm_judge` invocation, `votes:` majority voting, the per-action verdict cache (`CachedJudge`), and the per-run judge budget (`JudgeBudget`). `invoke_judge()` takes the payload a provider already parsed where there is one and reads the output-field text otherwise, never asking for a vendor-native structured-output schema. Its reader accepts the four faithful shapes a judge produces — JSON or a Python literal, bare or fenced — and refuses anything it cannot consume whole, since `passed` is a validation gate's terminal boolean with nothing downstream to re-check it. | `processing` |
| `runner.py` | Module | Evaluates every expectation against one record via `run_suite()`. A rule's `row_condition` argument is the first gate: false waives the rule (a passing outcome marked skipped, naming the condition), a condition that cannot be evaluated fails it, and the argument is withheld from the check. Deterministic types call `registry.get(...).check()` directly; `expression` dispatches to `expression.evaluate_condition` against the whole record before field resolution; `llm_judge` dispatches through an injected `judge` callable and an optional `context_source`, keeping this module free of any pipeline or network import. Every rule runs even after an earlier failure, and a check call that raises is isolated into a failed outcome (`check raised {Type}: ...`) with a warning-level traceback. Still raised, deliberately: an unregistered type, a judge dispatched with no caller wired, and a `None`-field expectation reaching field resolution without a record-scoped dispatch branch — each is a wiring bug, not a data outcome. | `validation` |
| `service.py` | Module | Runs generation through `ExpectationService.execute()`, taking the same `llm_operation` callable contract as `RepromptService`. Under a repair policy it loops generate → unwrap → structural gate → suite up to `max_iterations`, returning as soon as the suite passes; observe mode (`repair: none`) is a single unlooped pass and never consults the schema. Unwraps a real online record's length-1 list response before validating — `create_dynamic_agent` always returns `list[Any]`, so a bare dict is never what a real single-record call produces. The structural gate turns a non-record response or a schema-non-conforming record into a synthetic `_structural` outcome (underscore-prefixed by convention; nothing validates authored ids against it, but collision is impossible by control flow — a structural failure returns its own `SuiteResult` *instead of* running the suite) carrying the validator's own feedback and a digest of the schema, computed lazily so a schema that will not JSON-canonicalize cannot crash construction. `_exhausted_result()` owns `on_exhausted`: `return_last` ships the annotated last attempt, `fail` returns the tombstone shape (`executed=False`, response `None`, verdict kept), `raise` raises `ExpectationsExhaustedError`. All loop state lives in `execute()` locals — one service serves every record of an action, possibly concurrently. `create_expectation_service_from_config()` is the composition point: it builds a `CachedJudge`/`JudgeBudget` pair from `agent_config`/`judge_budget` only when a suite actually contains `llm_judge`, threads `max_iterations`/`on_exhausted`/`schema`, and refuses the reserved `repair: {prompt:}` form. A response holding many records is validated one record at a time, each outcome tagged with its record index, so a 1→N expansion gets a verdict per record rather than one for the batch; the observe-mode batch entry point returns nothing for a non-record response, but the batch repair driver goes through the same per-record fan-out as online. `attach_verdict()` writes the verdict under the record's `expect` key. | `processing` |
| `service.py` (batch entry) | Method | `ExpectationService.validate()` runs the suite over an already-produced record and returns its `SuiteResult`. The batch path has its response before it reaches this package, so it validates through here rather than through `execute()`; sharing the service keeps the judge cache, the per-run budget and the outcome shape identical on both paths. | `processing` |
| `repair.py` | Module | Composes the `repair: auto` regeneration prompt from a failed iteration: the original prompt, the previous output as JSON, every failed expectation with severity, detail and the author's `hint`, and the list of passing expectations the regeneration must preserve. Skipped outcomes are omitted from both lists — one that failed was never evaluated (judge budget), one that passed was waived by its `row_condition`, and neither is something the regeneration can be asked to preserve — but a partly-skipped outcome that also holds a real failure is kept. Pipeline-free. | `processing` |

## Project Surface

| Symbol | File | Interaction | Config Key |
|--------|------|-------------|------------|
| `load_named_suite` | `schema/{workflow}/{name}.yml` | Reads | `schema_path` |
| `schema_rule_entries` | `schema/{workflow}/{action}.yml` | Reads `fields[].expectations` and the file's own `expectations:` | `schema_path` |
| `create_expectation_service_from_config` | `agent_config/{workflow}.yml` | Reads | `actions[].expect` |
| `attach_verdict` | `agent_io/target/{action}/` | Writes | — |
| `CachedJudge` | agent's own `model_vendor`/`model_name` | Reads | `actions[].expect.expectations[].params.model` |
| `JudgeBudget` | — | Bounds | `actions[].expect.judge_budget` |
| `ExpectationService` | `agent_config/{workflow}.yml` | Reads | `actions[].expect.repair`, `actions[].expect.max_iterations`, `actions[].expect.on_exhausted` |
| `ExpectationService` | `schema/{workflow}/{action}.yml` | Validates | `actions[].schema` |
| `expectation_check` | `tools/{workflow}/*.py` | Reads (import side effect) | `actions[].expect.expectations[].type` |

**Internal only**: `Outcome`, `SuiteResult`, `ExpectationType`, `ExpectationRunResult`, `ExpectationsExhaustedError`, `compose_repair_prompt`, `resolve`, `referenced_names`, `resolve_context`, `parse_condition`, `referenced_field_paths`, `evaluate_condition` -- no direct project surface.

## Dependencies

| Package | Direction | Why |
|---------|-----------|-----|
| `processing` | inbound | `OnlineStrategy` composes `ExpectationService` as the outermost recovery layer, and converts an exhausted run into `RecoveryMetadata.expectations` for the `expectations_exhausted` tombstone arm |
| `processing` | outbound | `service.py` consumes `SchemaValidator` and `_extract_field_names` for the structural gate — constructed per call, since the validator carries per-call feedback state |
| `validation` | inbound | `expectations_validator` reads the registry, field selectors, and expression parsing at preflight |
| `input` | inbound | `input/loaders/udf.py` imports `tools/` files declaring `expectation_check`, registering user types before preflight |
| `config` | outbound | `ExpectConfig` lives in `config/schema.py` |
| `output` | outbound | `loader.py` resolves suite names through `SchemaLoader`, exactly as `schema:` resolves |
| `guards`, `input` | outbound | `expression.py` reuses `GuardParser`'s blocklist and the `input/preprocessing/parsing` grammar/AST |
| `utils` | outbound | `judge.py` reuses `json_parsing.strip_code_fences` to unwrap a fenced verdict; it deliberately does not reuse `parse_llm_json`, whose best-effort repair would scavenge a verdict out of prose |
| `output` | outbound | `judge.py` takes the provider payload from `response.ResponseBuilder.unwrap`, the counterpart to the `wrap_non_json` that produced the envelope |

## Notes

The engine core (`types`, `fields`, `registry`, `expression`, `loader`, `runner`, `repair`)
imports nothing from `workflow/`, `processing/` or `storage/`. `service.py` is the only module
here that knows about the pipeline. Keeping that boundary is what lets the runner be tested
without a network and the CLI start without loading the workflow stack.

**A response carries one record or many.** A bare dict, or the length-1 list a real online call
produces, is one record; an action whose LLM returns a JSON array fans out 1→N. Every record is
validated and annotated on its own. The combined verdict passes only when all of them do, and
tags each outcome with its record index so a rule that fails on one record and passes on another
is not reported as both.

**Cost.** `judge_budget` units are acquired per rule per value, not per provider call — `votes: N`
spends N calls inside one unit, so divide by `votes` when sizing it. The verdict cache keys on the
resolved field value, so a repair that leaves a judged field untouched is still cache-served, and
an expansion multiplies judge spend by its record count. `reprompt:` nests inside each repair
iteration, costing `max_iterations x reprompt.max_attempts` in the worst case.

**Limits worth knowing before changing this package.** A named `suite:` (or the bare-block
default, which reads the action's own schema file) needs a project root to resolve;
`InvocationStrategyFactory` does not thread one, so only the inline `expectations:` form works
end to end. A judged expectation's `context:` refs are auto-injected
into the producing action's `context_scope.observe` for the inline form only, so a named suite's
refs are inert. The prompt trace stores the original prompt against the final response, so a
record repaired on a later iteration has a trace whose prompt did not produce it. `_structural`
is reserved as an outcome id by convention; collision is prevented by control flow, since a
structural failure returns its own result instead of running the suite.
