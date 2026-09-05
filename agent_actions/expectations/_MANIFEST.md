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
| `runner.py` | Module | Evaluates every expectation against one record via `run_suite()`. Every rule runs even after an earlier failure — the repair composer needs both what broke and what to preserve. A missing field is a failed outcome; an unregistered type raises. | `validation` |
| `service.py` | Module | Runs one generation through `ExpectationService.execute()`, taking the same `llm_operation` callable contract as `RepromptService` and composing as the outermost recovery layer. `attach_verdict()` writes the verdict under the record's `expect` key. | `processing` |

## Project Surface

| Symbol | File | Interaction | Config Key |
|--------|------|-------------|------------|
| `load_named_suite` | `schema/{workflow}/{name}.yml` | Reads | `schema_path` |
| `create_expectation_service_from_config` | `agent_config/{workflow}.yml` | Reads | `actions[].expect` |
| `attach_verdict` | `agent_io/target/{action}/` | Writes | — |

**Internal only**: `Outcome`, `SuiteResult`, `ExpectationType`, `ExpectationRunResult`, `resolve`, `referenced_names` -- no direct project surface.

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
