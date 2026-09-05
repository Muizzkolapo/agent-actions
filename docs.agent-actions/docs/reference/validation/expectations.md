---
title: AI Expectations
sidebar_position: 3
---

# AI Expectations

Schema validation catches structural problems — missing fields, wrong types. It can't catch semantic ones. A summary can be a perfectly well-typed string and still misstate what the source said. A generated question can match its schema and still be unanswerable from the material it was supposed to be grounded in.

`expect:` adds a validation layer on top of schema and guards: deterministic checks (length, forbidden phrases, allowed values, regex) plus LLM-judged checks (`llm_judge`) that ask a model whether a value satisfies an arbitrary natural-language rule, optionally grounded against other actions' output. Results are attached to the record and reported — they never block the pipeline or trigger a retry on their own. If you need pipeline-blocking behavior, pair `expect:` with a [guard](../execution/guards.md) that reads the verdict.

## Quick example

```yaml
- name: summarize_article
  dependencies: [extract_article]
  schema: summary_schema
  prompt: $prompts.Summarize
  context_scope: { observe: [extract_article.body] }
  expect:
    repair: none
    judge_budget: 200
    expectations:
      - id: summary_present
        type: not_null
        field: summary

      - id: summary_length
        type: word_count_between
        field: summary
        min: 20
        max: 200
        severity: warn

      - id: no_hedging_language
        type: no_forbidden_phrases
        field: summary
        phrases: ["it seems", "possibly", "may or may not"]
        severity: warn

      - id: summary_grounded
        type: llm_judge
        field: summary
        votes: 3
        severity: info
        context:
          - extract_article.body
        rule: >
          The summary only states facts present in the grounding text and
          does not introduce claims the source does not support.
```

Every `expect:` entry runs after schema validation succeeds, against the same record schema validation just accepted. Nothing here changes what the LLM was asked to produce — it only judges what came back.

:::note Observe mode only
The current build only implements `repair: none` (observe: run the checks, attach the verdict, keep going). `repair: retry` and `repair: auto` are accepted by the schema for forward compatibility but raise a `ConfigurationError` at startup — they're reserved for a future repair/regeneration loop, not silently ignored.
:::

## The `expect:` block

| Key | Type | Default | Purpose |
|-----|------|---------|---------|
| `expectations` | list | — | Inline list of expectation entries (mutually exclusive with `suite`; omit both to read the action's own schema file) |
| `suite` | string | — | Name of a schema-path file with an `expectations:` block (see [Named suites](#named-suites)) instead of an inline list |
| `repair` | string | `auto` | Must be set to `none` in this build |
| `judge_budget` | integer ≥ 1 | uncapped | Max real `llm_judge` LLM calls this action's suite may make across the whole run |

Every entry in `expectations:` (or in a suite file) shares this shape:

| Key | Required | Purpose |
|-----|----------|---------|
| `id` | no | Stable identifier; derived from type + rule content when omitted |
| `type` | yes | A registered deterministic type, or `llm_judge` |
| `field` | yes | [Field selector](#field-selectors) this rule reads |
| `severity` | no | `fail` (default), `warn`, or `info` — see [Severity](#severity) |
| `hint` | no | Remedy text, reserved for the future repair loop |
| *(type-specific)* | varies | e.g. `min`/`max`, `phrases`, `rule`, `votes` — see below |

## Deterministic expectation types

| Type | Params | Checks |
|------|--------|--------|
| `not_null` | — | Value isn't `None` and isn't an empty string/list/dict |
| `item_count` | `equals`, `min`, `max` | Length of a list field |
| `word_count_between` | `min`, `max` | Whitespace-split word count |
| `word_count_ratio` | `max_ratio` *(required)* | Longest/shortest word count across a list of items doesn't exceed a ratio — catches one option in a list being wildly longer than its siblings |
| `accepted_values` | `values` *(required)* | Value is one of an explicit allow-list |
| `matches_regex` | `pattern` *(required)*, `negate` | Value matches (or, with `negate: true`, must not match) a regex |
| `no_forbidden_phrases` | `phrases` *(required)*, `case_sensitive` | Value doesn't contain any of a list of substrings |
| `contains_terms_from` | `terms` *(required)*, `min_matches` | Value contains at least `min_matches` (default 1) terms from a list |

```yaml
- id: category_is_valid
  type: accepted_values
  field: category
  values: [billing, technical, account, other]

- id: no_placeholder_text
  type: matches_regex
  field: body
  pattern: '\bTODO\b|\bplaceholder\b'
  negate: true
```

## Field selectors

The `field:` a rule reads follows three shapes:

| Selector | Resolves to |
|----------|-------------|
| `summary` | The whole value at that field — the input a whole-value check like `item_count` or `word_count_ratio` needs |
| `options[*]` | One input per element of the `options` array — the rule runs once per element |
| `[option_a, option_b]` | A single input holding the list `[value_of_option_a, value_of_option_b]` — for checks that compare sibling fields |

A wildcard selector works on arrays of objects too — each element is passed through as-is (non-string values are JSON-serialized before reaching an `llm_judge` prompt):

```yaml
- id: each_step_is_actionable
  type: llm_judge
  field: steps[*]
  votes: 3
  rule: "The step is a concrete, executable instruction, not a vague restatement of the goal."
```

Nested paths inside a wildcard element (`options[*].text`) aren't supported — select the whole element and let the rule (or check) read the field it needs.

## `llm_judge`

`llm_judge` asks an LLM whether a value satisfies a natural-language `rule`. It's the only expectation type that makes its own model call — everything else is a pure function over the resolved value.

```yaml
- id: answer_is_grounded
  type: llm_judge
  field: answer
  rule: >
    The answer is fully supported by the grounding context and does not
    state anything the context contradicts or omits.
  votes: 3
  severity: warn
  model: gpt-4o-mini
  context:
    - retrieve_passage.passage_text
```

| Param | Default | Purpose |
|-------|---------|---------|
| `rule` | *(required)* | The natural-language criterion the judge evaluates |
| `votes` | `1` | Run the judge this many times independently and take the majority; a tie **fails closed** (an even split never counts as a pass) |
| `model` | the action's own `model_name` | Override which model does the judging |
| `context` | none | List of `action.field` refs, resolved from the *same* `context_scope` machinery as prompts, and passed to the judge as grounding text |

### `context:` auto-injection

Every ref in `context:` is automatically added to the action's own `context_scope.observe` at load time — you don't need to also list it there by hand (and if you do, it's deduplicated, not doubled). This is what makes `retrieve_passage.passage_text` available to the judge in the example above even though `answer_is_grounded` lives on a different action than `retrieve_passage`.

### Caching and budget

- **Cache:** a judge call is keyed on `(expectation, resolved value)`. If two records (or two rules) produce byte-identical content for the same rule, the second call is served from cache instead of spending another real LLM call.
- **Budget:** `judge_budget` on the `expect:` block caps real judge calls across every record the action processes in one run — cache hits don't count against it. Once exhausted, further judge outcomes are marked `skipped` (not `failed`) with a message naming the exhaustion.
- **Failure isolation:** if the judge LLM call itself errors (network, auth, rate limit), that single outcome fails with the error in its `detail` — it does not crash the record's processing.

## Severity

| Severity | Effect on `overall_pass` | Use for |
|----------|---------------------------|---------|
| `fail` (default) | A failing `fail`-severity outcome makes `overall_pass: false` | Hard requirements you intend to guard on downstream |
| `warn` | Never blocks `overall_pass` | Notable but non-blocking quality signals |
| `info` | Never blocks `overall_pass` | Diagnostics you want recorded, not enforced — the natural default for `llm_judge`, since a single model's opinion is evidence, not ground truth |

## Where results land

Results attach to the record under an `expect` key, alongside the action's own schema fields:

```json
{
  "summary": "...",
  "expect": {
    "overall_pass": false,
    "failed": ["summary_length"],
    "skipped": [],
    "outcomes": [
      {"id": "summary_present", "type": "not_null", "severity": "fail", "passed": true, "detail": "", "skipped": false},
      {"id": "summary_length", "type": "word_count_between", "severity": "warn", "passed": false, "detail": "212 words, expected at most 200", "skipped": false},
      {"id": "summary_grounded", "type": "llm_judge", "severity": "info", "passed": true, "detail": "3/3 judge votes passed", "skipped": false}
    ]
  }
}
```

`overall_pass` reflects only `fail`-severity outcomes — `summary_length` failing above doesn't flip it because that rule is `severity: warn`.

To act on the verdict, read it from a downstream [guard](../execution/guards.md):

```yaml
- name: publish_summary
  dependencies: summarize_article
  guard:
    condition: 'summarize_article.expect.overall_pass == true'
    on_false: filter
```

## Named suites

An inline `expectations:` list is scoped to one action. To reuse the same rules across actions, put them in an `expectations:` block of a schema-path file and reference it by name:

```yaml
- name: summarize_article
  expect:
    repair: none
    suite: grounded_summary
```

`suite:` resolves through the schema path exactly as `schema:` does — by file name, across the project-level and workflow-level schema directories named by `schema_path` in `agent_actions.yml`. The file may carry `fields:`, `expectations:`, or both, so an action's shape contract and its quality rules can live in one file:

```yaml
# schema/my_workflow/grounded_summary.yml
expectations:
  - id: summary_present
    type: not_null
    field: summary
  - id: summary_grounded
    type: llm_judge
    field: summary
    votes: 3
    rule: "The summary is fully supported by the grounding context."
```

An `expectations:` block on a schema attaches nothing by itself — rules run only where an action declares `expect:`. An `expect:` block with neither `suite:` nor `expectations:` reads the `expectations:` block of the file the action's own `schema:` names, so the co-located drop-in is just `expect: {repair: none}`. The compiled schema sent to a provider never contains the `expectations:` block.

A suite file has no `repair`, `judge_budget`, or `context_scope` of its own — those stay on the action's `expect:` block; the suite only supplies the `expectations:` list.

## Preflight validation

`agac inspect` validates an `expect:` block before any LLM call is made:

- `votes` must be a positive integer.
- `context` must be a list of `action.field` strings; each referenced action must exist upstream and each field must appear in that action's declared output.
- Unknown parameters for a given `type` (e.g. `phrases` on `not_null`) are rejected.

```bash
agac inspect -a my_workflow
```

Reaching the action list at all means these checks passed.

## Current limitations

- **Observe-only.** `repair: none` is the only supported mode; there is no automatic regenerate-and-recheck loop yet.
- **`context:` refs are single-level.** `action.field` only — no nested paths into a wildcard element (`action.items[*].text` is not valid inside a `context:` ref).
- **Budget is per run, not persisted.** `judge_budget` resets each time the workflow runs; it does not track spend across separate `agac run` invocations.
