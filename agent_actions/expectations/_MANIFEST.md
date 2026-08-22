# Expectations

Declarative output expectations: typed rules an action's output must satisfy,
their results, and the service that runs them around generation.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `types.py` | Module | Defines `Expectation`, `Suite`, `Outcome`, `SuiteResult`. `Expectation` accepts type-specific params as extra keys; `definition_hash()` digests what a rule tests, ignoring its id. | `validation`, `typing` |
| `fields.py` | Module | Turns a `field:` selector into check inputs via `resolve()` — bare name yields the whole value, `name[*]` one per element, a list of names one combined input. `referenced_names()` backs the preflight check. | `validation` |
| `registry.py` | Module | Deterministic expectation types and `register`/`get`/`known_types`. A check returns `(passed, detail)`; `detail` names the observed value, since the repair composer reads it. | `validation` |
| `loader.py` | Module | Loads a suite via `load_suite_file`, `load_named_suite`, `build_inline_suite`. Named suites resolve through `get_expectations_path()`, which defaults rather than raising. | `configuration` |
| `runner.py` | Module | Evaluates every expectation against one record via `run_suite()`. Every rule runs even after an earlier failure — the repair composer needs both what broke and what to preserve. A missing field is a failed outcome; an unregistered type raises. | `validation` |
| `service.py` | Module | Runs one generation through `ExpectationService.execute()`, taking the same `llm_operation` callable contract as `RepromptService` and composing as the outermost recovery layer. `attach_verdict()` writes the verdict under the record's `expect` key. | `processing` |

## Project Surface

| Symbol | File | Interaction | Config Key |
|--------|------|-------------|------------|
| `load_named_suite` | `expectations/{workflow}/{suite}.yml` | Reads | `expectations_path` |
| `create_expectation_service_from_config` | `agent_config/{workflow}.yml` | Reads | `actions[].expect` |
| `attach_verdict` | `agent_io/target/{action}/` | Writes | — |

**Internal only**: `Outcome`, `SuiteResult`, `ExpectationType`, `ExpectationRunResult`, `resolve`, `referenced_names` -- no direct project surface.

## Dependencies

| Package | Direction | Why |
|---------|-----------|-----|
| `processing` | inbound | `OnlineStrategy` composes `ExpectationService` as the outermost recovery layer |
| `validation` | inbound | `expectations_validator` reads the registry and field selectors at preflight |
| `config` | outbound | `service.py` resolves suite paths via `path_config`; `ExpectConfig` lives in `config/schema.py` |

## Notes

The engine core (`types`, `fields`, `registry`, `loader`, `runner`) imports nothing
from `workflow/`, `processing/` or `storage/`. `service.py` is the only module here
that knows about the pipeline. Keeping that boundary is what lets the runner be
tested without a network and the CLI start without loading the workflow stack.

A named `suite:` reference is only resolvable when both a project root and a
workflow name are available. `InvocationStrategyFactory` (the only production
caller of `create_expectation_service_from_config` as of Plan 1) does not thread
either through, so `suite:` mode raises `ConfigurationError` unconditionally today
even for an existing suite file — only the inline `expectations:` form works end
to end. Threading project root/workflow through `OnlineLLMStrategy` and its three
callers (`workflow/pipeline.py`, `prompt/data_generator.py`,
`input/preprocessing/staging/initial_pipeline.py`) is required before `suite:`
is usable, and is out of scope for this plan.
