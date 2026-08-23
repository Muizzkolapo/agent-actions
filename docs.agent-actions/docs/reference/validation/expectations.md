---
title: AI Expectations
sidebar_position: 3
---

# AI Expectations

Schema validation catches structural problems — missing fields, wrong types. It can't catch semantic ones. A summary can be a perfectly well-typed string and still misstate what the source said. A generated question can match its schema and still be unanswerable from the material it was supposed to be grounded in.

`expect:` adds a validation layer on top of schema and guards: deterministic checks (length, forbidden phrases, allowed values, regex) plus LLM-judged checks (`llm_judge`) that ask a model whether a value satisfies an arbitrary natural-language rule, optionally grounded against other actions' output.

How much authority those results carry is up to you. Under `repair: none` they are pure reporting — the verdict rides along on the record and blocks nothing, so pair it with a [guard](../execution/guards.md) if you want it to gate anything. Under a repair policy the same rules drive [regeneration](#repairing-instead-of-observing), and can tombstone a record or halt the run outright.

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

:::note Start with `repair: none`
The example above uses observe mode: run the checks, attach the verdict, keep going. It costs nothing beyond the checks themselves and changes no behaviour, which makes it the right way to learn what your rules actually catch before letting them regenerate anything. When you're ready to enforce, see [Repairing instead of observing](#repairing-instead-of-observing).
:::

## The `expect:` block

| Key | Type | Default | Purpose |
|-----|------|---------|---------|
| `expectations` | list | — | Inline list of expectation entries (mutually exclusive with `suite`; omit both to read the action's own schema file) |
| `suite` | string | — | Name of a schema-path file with an `expectations:` block (see [Named suites](#named-suites)) instead of an inline list |
| `repair` | string | `auto` | `none` (observe), `retry` (re-send the original prompt), or `auto` (re-send with composed feedback) |
| `max_iterations` | integer 1–10 | `3` | Total generations per record, counting the first. Setting it explicitly alongside `repair: none` is a config error, not a no-op |
| `on_exhausted` | string | `return_last` | What to do when the iterations run out: `return_last`, `fail`, or `raise`. Same rule — do not set it under `repair: none` |
| `judge_budget` | integer ≥ 1 | uncapped | Max real `llm_judge` LLM calls this action's suite may make across the whole run |

Every entry in `expectations:` (or in a suite file) shares this shape:

| Key | Required | Purpose |
|-----|----------|---------|
| `id` | no | Stable identifier; derived from type + rule content when omitted |
| `type` | yes | A registered deterministic type, or `llm_judge` |
| `field` | yes | [Field selector](#field-selectors) this rule reads |
| `severity` | no | `fail` (default), `warn`, or `info` — see [Severity](#severity) |
| `hint` | no | Remedy text handed to the model when `repair: auto` regenerates |
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
| `expression` | `condition` *(required)* | A guard-syntax condition evaluated against the whole record — see [Expressions](#expressions) |

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

## Expressions

`type: expression` evaluates a condition against the **whole record**, using the same syntax as [guard](../execution/guards.md) conditions — a condition string is portable between a `guard:` block and an `expect:` entry unchanged. It takes no `field:` (the fields it reads are named inside the condition):

```yaml
- id: score_consistent_with_verdict
  type: expression
  condition: 'score >= 80 or verdict != "approved"'

- id: summary_present_when_flagged
  type: expression
  condition: 'needs_summary == false or summary IS NOT NULL'
  severity: warn
```

Use it when a rule spans multiple fields or needs comparison logic no single-field type expresses — the declarative middle ground between the built-in types and writing Python.

Behavior worth knowing:

- **A false condition's detail carries the actual values** of every field the condition read: `condition 'score >= 80' is false (score=64)` — so a reader (or a future repair loop) sees why, not just that.
- **A missing field is a failed outcome, not a crash**, carrying the evaluator's own message listing the fields the record does have.
- **An unquoted string literal** (`verdict == approved` instead of `verdict == "approved"`) is a classic typo: `approved` parses as a field reference. On records without that field the rule fails with a remediation message telling you to quote it — and preflight flags the unknown field reference before any run.
- **`udf:`-prefixed conditions are not supported** here (unlike guards). The Python extension point for expectations is [`@expectation_check`](#extending-with-your-own-checks); preflight rejects a `udf:` condition with exactly that pointer.
- **Function calls (`LENGTH(...)` etc.) are not available** in condition syntax.

Preflight validates every condition before any LLM call: syntax, the dangerous-pattern blocklist, field references against the action's schema (dotted paths checked at their top segment), and rejects a constant condition that references no record fields (it would always evaluate the same way).

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

## Repairing instead of observing

Under a repair policy the action stops merely reporting quality and starts enforcing it: a record whose suite fails is regenerated and re-validated, up to `max_iterations` total generations.

```yaml
- name: write_question
  expect:
    repair: auto
    max_iterations: 3
    on_exhausted: fail
    expectations:
      - id: option_count
        type: item_count
        field: options
        equals: 4
        hint: write exactly four options, one correct and three plausible distractors
```

Each iteration runs the **whole** suite again, not just the rules that failed last time — a repair that fixes one rule by breaking another does not pass. The two policies differ only in what the regeneration is told:

- **`retry`** re-sends the original prompt unchanged. Use it when failures look like sampling noise.
- **`auto`** re-sends the original prompt plus composed feedback: the previous output, every failed expectation with its detail and `hint`, and the list of rules that already passed and must stay passing. Use it when the model needs to know what was wrong.

`max_iterations` counts *total* generations, so `3` means the first attempt plus at most two repairs. When they run out, `on_exhausted` decides:

| `on_exhausted` | What ships |
|---|---|
| `return_last` (default) | The last attempt, with its failing verdict attached, so a downstream guard can filter on it. If that last attempt is not a record at all (every iteration failed structurally), there is nothing to annotate and it becomes a tombstone instead |
| `fail` | An `expectations_exhausted` tombstone carrying the failed rule ids and the iteration count |
| `raise` | Nothing — the run halts with an error naming the action and the still-failing rules |

### Repair and `reprompt:`

Under a repair policy the loop also owns **structural** quality. A response that isn't a JSON object, or one that doesn't conform to the action's schema, becomes a failing iteration carrying the schema feedback — the same ground `reprompt:` covers with its default schema checking.

Keeping both on one action multiplies cost, because the reprompt loop runs *inside* every repair iteration: `max_iterations × reprompt.max_attempts` provider calls in the worst case, `3 × 2` at their defaults, and more again if the action also configures `retry:`.

So a `reprompt:` block that only does schema checking is redundant under `repair: auto`, and deleting it is the migration. Check what yours actually does first — `reprompt:` also runs a `validation:` UDF and supports `use_llm_critique` / `use_self_reflection`, none of which the structural gate replaces. If your block uses those, either keep it and accept the nesting cost, or port the UDF to an [`@expectation_check`](#extending-with-your-own-checks) so the suite owns it.

One more caveat: `repair: retry` records structural failures in the verdict but re-sends the original prompt unchanged, so it does not carry schema feedback back to the model the way `reprompt:` does. Use `repair: auto` if you are replacing a reprompt block.

### Budgeting the judge under repair

Two things change once the loop can regenerate.

The verdict cache is keyed on the **field value** a rule reads, not on the whole response. A repair that leaves a judged field untouched — which is what the `auto` prompt asks for, since it names the passing rules as things to preserve — is served from cache and costs nothing. A repair that rewrites the judged field is genuinely new content and costs a real call. So iterations multiply judge spend only for the rules whose fields actually change; `records × iterations` is the safe upper bound, not the expected cost.

`judge_budget` counts *budget units*, and one unit is acquired per rule per value — not per provider call. With `votes: 3`, one unit spends three real calls, so a budget of `200` permits up to 600 provider calls. Divide by `votes` when sizing it.

Once the budget is spent, later records carry a `skipped` judged outcome, which can never satisfy a `fail`-severity rule. Those records still have their other rules repaired and ship with an honest failing verdict.

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
- Unknown parameters for a given `type` (e.g. `phrases` on `not_null`) are rejected — including for [your own registered types](#extending-with-your-own-checks), whose declared parameters are enforced exactly like built-ins'.
- Every entry must carry a `field:` (empty strings and empty lists are rejected too) — except `expression`, which must not.
- `expression` conditions are parsed and checked in full (syntax, blocklist, field references, constant conditions) — see [Expressions](#expressions).

```bash
agac inspect -a my_workflow
```

Reaching the action list at all means these checks passed.

## Extending with your own checks

When the built-in types and `expression` conditions aren't enough, register a project-defined check with the `expectation_check` decorator — the same pattern as `udf_tool` for tool actions. The check is a pure function receiving one resolved value plus the entry's parameters, returning `(passed, detail)`:

```python
# tools/my_workflow/quality_checks.py
from agent_actions import expectation_check

@expectation_check("valid_isbn", params=("allow_isbn10",))
def valid_isbn(value, params):
    digits = str(value).replace("-", "")
    if _isbn_checksum_ok(digits, allow_isbn10=params.get("allow_isbn10", False)):
        return True, ""
    return False, f"'{value}' has an invalid ISBN check digit"
```

```yaml
- id: isbn_is_real
  type: valid_isbn
  field: isbn
  allow_isbn10: true
```

How it works:

- **Where the file lives:** anywhere under your project's tool path (`tools/` by default) — the same directory tool-action UDFs live in. Discovery imports any file there that declares the decorator, except `_`-prefixed and `test_`-prefixed files, which are always skipped — a check in `_helpers.py` silently never registers.
- **When it registers:** at config load, before preflight — so `agac inspect` validates your type's parameters (`params=`, `required=`) exactly like a built-in's, and an unknown parameter or missing required parameter on your type is a preflight defect.
- **Failure detail:** write the `detail` string to name the observed value (`"'X' has an invalid check digit"`), not to restate the rule — it's what a reader sees in the record's verdict.
- **A check that raises** doesn't crash the record: the outcome fails with `check raised {ExceptionType}: {message}` and the traceback is logged at warning level.
- **Name collisions fail loudly:** shadowing a built-in type name (or `llm_judge`/`expression`) raises at load with the offending file named; registering the same name from two different files or functions raises a duplicate-function error. Re-importing the same file is safe.

Prefer the tiers in this order: a built-in type (zero code), an `expression` condition (declarative, cross-field), `llm_judge` (semantic, natural-language), and only then a custom check — Python you now own and test.

## Current limitations

- **Repair is online only.** The checks themselves run in both modes and attach the same verdict, so `expect:` with `repair: none` behaves identically whichever `run_mode` you set. Regeneration does not: the batch path validates and reports but does not yet re-submit failing records, so `repair: retry`/`auto` on a batch action is refused at preflight rather than silently ignored. Expectation recovery metadata is also not carried across a batch reload.
- **Record granularity only.** A repair policy needs one record per response to validate; preflight refuses `repair` on a `granularity: file` action. Observe mode on such an action attaches a verdict only when the response happens to hold exactly one record; a multi-record response is passed through unvalidated.
- **No custom repair prompt.** The `repair: {prompt: $wf.X}` mapping form is reserved in the schema but not implemented; it is refused with a message saying so. Use `retry` or `auto`.
- **Tool actions cannot repair.** Re-running a deterministic UDF yields the same output, so `repair` on a `kind: tool` action is refused at preflight; observe mode works normally.
- **The prompt trace shows the original prompt.** A record repaired on iteration 2 or later has a stored trace pairing the *first* prompt with the *final* response, and that response carries the attached verdict.
- **`context:` refs are single-level.** `action.field` only — no nested paths into a wildcard element (`action.items[*].text` is not valid inside a `context:` ref).
- **Budget is per run, not persisted.** `judge_budget` resets each time the workflow runs; it does not track spend across separate `agac run` invocations.
