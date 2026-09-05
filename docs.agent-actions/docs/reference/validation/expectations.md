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
        params:
          min: 20
          max: 200
        severity: warn

      - id: no_hedging_language
        type: no_forbidden_phrases
        field: summary
        params:
          phrases: ["it seems", "possibly", "may or may not"]
        severity: warn

      - id: summary_grounded
        type: llm_judge
        field: summary
        severity: info
        params:
          votes: 3
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
| `suite` | string | — | Name of a schema-path file with an `expectations:` block (see [Rules in the schema file](#rules-in-the-schema-file)) instead of an inline list |
| `repair` | string | `auto` | `none` (observe), `retry` (re-send the original prompt), or `auto` (re-send with composed feedback) |
| `max_iterations` | integer 1–10 | `3` | Total generations per record, counting the first. Setting it explicitly alongside `repair: none` is a config error, not a no-op |
| `on_exhausted` | string | `return_last` | What to do when the iterations run out: `return_last`, `fail`, or `raise`. Same rule — do not set it under `repair: none` |
| `judge_budget` | integer ≥ 1 | uncapped | Max real `llm_judge` LLM calls this action's suite may make across the whole run |

Every entry in `expectations:` (or in a suite file) shares this shape:

| Key | Required | Purpose |
|-----|----------|---------|
| `id` | no | Stable identifier; derived from type + rule content when omitted |
| `type` | yes | A registered deterministic type, or `llm_judge` |
| `field` | yes* | [Field selector](#field-selectors) this rule reads. Omitted — and refused — when the rule is [declared on a field](#rules-in-the-schema-file), which already names what it tests; `expression` never takes one |
| `params` | no | The arguments for this `type` — `min`/`max`, `phrases`, `rule`, `votes`, and the universal [`row_condition`](#row-conditions) |
| `severity` | no | `error` (default), `warn`, or `info` — see [Severity](#severity) |
| `hint` | no | Remedy text handed to the model when `repair: auto` regenerates |

Those six keys are the whole vocabulary: anything else at the top level of a rule is refused by name, so a mistyped `sevrity:` is an error at load rather than an argument the type does not recognise. Type-specific arguments always go under `params:`.

## Deterministic expectation types

| Type | Params | Checks |
|------|--------|--------|
| `not_null` | — | Value isn't `None` and isn't an empty string/list/dict |
| `item_count` | `equals`, `min`, `max` | Length of a list field |
| `word_count_between` | `min`, `max` | Whitespace-split word count |
| `word_count_ratio` | `max_ratio` *(required)* | Longest/shortest word count across a list of items doesn't exceed a ratio — catches one option in a list being wildly longer than its siblings |
| `accepted_values` | `values` *(required)* | Value is one of an explicit allow-list |
| `matches_regex` | `pattern` *(required)*, `negate` | Value matches (or, with `negate: true`, must not match) a regex |
| `match_like_pattern` | `like_pattern` *(required)*, `negate` | Value matches a SQL `LIKE` pattern across its whole length — `%` is any run, `_` exactly one character, everything else literal |
| `no_forbidden_phrases` | `phrases` *(required)*, `case_sensitive` | Value doesn't contain any of a list of substrings |
| `contains_terms_from` | `terms` *(required)*, `min_matches` | Value contains at least `min_matches` (default 1) terms from a list |
| `expression` | `condition` *(required)* | A guard-syntax condition evaluated against the whole record — see [Expressions](#expressions) |

```yaml
- id: category_is_valid
  type: accepted_values
  field: category
  params:
    values: [billing, technical, account, other]

- id: no_placeholder_text
  type: matches_regex
  field: body
  params:
    pattern: '\bTODO\b|\bplaceholder\b'
    negate: true

- id: no_stray_markup
  type: match_like_pattern
  field: summary
  params:
    like_pattern: "%<%>%"
    negate: true
```

## Field selectors

A rule [declared on a field](#rules-in-the-schema-file) has no `field:` key — its position names what it tests. Everywhere else, the `field:` a rule reads follows three shapes:

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
  params:
    votes: 3
    rule: "The step is a concrete, executable instruction, not a vague restatement of the goal."
```

Nested paths inside a wildcard element (`options[*].text`) aren't supported — select the whole element and let the rule (or check) read the field it needs.

## Expressions

`type: expression` evaluates a condition against the **whole record**, using the same syntax as [guard](../execution/guards.md) conditions — a condition string is portable between a `guard:` block and an `expect:` entry unchanged. It takes no `field:` (the fields it reads are named inside the condition):

```yaml
- id: score_consistent_with_verdict
  type: expression
  params:
    condition: 'score >= 80 or verdict != "approved"'

- id: summary_present_when_flagged
  type: expression
  params:
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
  severity: warn
  params:
    rule: >
      The answer is fully supported by the grounding context and does not
      state anything the context contradicts or omits.
    votes: 3
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

Every ref in `context:` is automatically added to the action's own `context_scope.observe` at load time — you don't need to also list it there by hand (and if you do, it's deduplicated, not doubled). This covers an action's inline `expectations:` list and the rules of its own schema; a named `suite:` is the exception, because a suite is not loadable at the layer that does the injection, so list its refs in `observe:` yourself. This is what makes `retrieve_passage.passage_text` available to the judge in the example above even though `answer_is_grounded` lives on a different action than `retrieve_passage`.

### Caching and budget

- **Cache:** a judge call is keyed on `(expectation, resolved value)`. If two records (or two rules) produce byte-identical content for the same rule, the second call is served from cache instead of spending another real LLM call.
- **Budget:** `judge_budget` on the `expect:` block caps real judge calls across every record the action processes in one run — cache hits don't count against it. Once exhausted, further judge outcomes are marked `skipped` with a message naming the exhaustion. A skipped outcome did not pass, so an `error`-severity one appears in **both** the verdict's `failed` and `skipped` lists — it could not be checked, and a rule that could not be checked has not been satisfied.
- **Failure isolation:** if the judge LLM call itself errors (network, auth, rate limit), that single outcome fails with the error in its `detail` — it does not crash the record's processing.

## Severity

| Severity | Effect on `overall_pass` | Use for |
|----------|---------------------------|---------|
| `error` (default) | A failing `error`-severity outcome makes `overall_pass: false` | Hard requirements you intend to guard on downstream |
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
        params:
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

Once the budget is spent, later records carry a `skipped` judged outcome, which can never satisfy an `error`-severity rule. Those records still have their other rules repaired and ship with an honest failing verdict.

## Where results land

Results attach to the record under an `expect` key, alongside the action's own schema fields:

```json
{
  "summary": "...",
  "expect": {
    "overall_pass": true,
    "failed": [],
    "skipped": [],
    "outcomes": [
      {"id": "summary_present", "type": "not_null", "severity": "error", "passed": true, "detail": "", "skipped": false},
      {"id": "summary_length", "type": "word_count_between", "severity": "warn", "passed": false, "detail": "212 words, expected at most 200", "skipped": false},
      {"id": "summary_grounded", "type": "llm_judge", "severity": "info", "passed": true, "detail": "3/3 judge votes passed", "skipped": false}
    ]
  }
}
```

The `skipped` list holds `error`-severity rules that could **not** be checked — a budget-exhausted judge, for instance. A rule waived by its `row_condition` passed and is not listed there, and neither are `warn`/`info` skips, since neither can change `overall_pass`. Every skip is still in `outcomes[]` with `skipped: true` and its reason in the detail, so "did not apply" stays distinguishable from "could not tell".

`summary_length` failed and is still recorded in `outcomes`, but it appears in neither `failed` nor `overall_pass`: both count `error`-severity outcomes only, and that rule is `severity: warn`. That is the whole point of `warn` — the finding is on the record without gating anything.

To act on the verdict, read it from a downstream [guard](../execution/guards.md):

```yaml
- name: publish_summary
  dependencies: summarize_article
  guard:
    condition: 'summarize_article.expect.overall_pass == true'
    on_false: filter
```

## Rules in the schema file

An inline `expectations:` list is scoped to one action. To reuse the same rules — or simply to keep a field's shape and its quality rules together — declare them in the schema file, on the fields they test:

```yaml
# schema/my_workflow/grounded_summary.yml
name: grounded_summary
fields:
  - id: summary
    type: string
    description: "Concise summary of the source."
    expectations:
      - id: summary_present
        type: not_null

      - id: summary_length
        type: word_count_between
        params:
          min: 20
          max: 200
        severity: warn

  - id: exam_density
    type: string
    expectations:
      - id: density_is_a_known_level
        type: accepted_values
        params:
          values: [high, medium, low]
```

A rule under a field takes no `field:` — its position is the selector, and declaring one is an error rather than a redundancy. That also removes a whole class of mistake: a rule cannot name a field the schema does not declare.

Rules that are about no single field keep the file's own top-level `expectations:` block, where they carry `field:` as usual:

```yaml
expectations:
  - id: front_and_back_are_balanced
    type: word_count_ratio
    field: [term, definition]
    params:
      max_ratio: 4

  - id: score_matches_verdict
    type: expression
    params:
      condition: 'score >= 80 or verdict != "approved"'
```

A file may carry either form or both. A file with only rules and no `fields:` is still a valid suite — that is the portable form an external stack consumes.

### Binding a suite to an action

```yaml
- name: summarize_article
  schema: grounded_summary
  expect:
    repair: none
```

`suite:` names a different file, resolved through the schema path exactly as `schema:` does — by file name, across the project-level and workflow-level schema directories named by `schema_path` in `agent_actions.yml`:

```yaml
  expect:
    repair: none
    suite: shared_summary_rules
```

Rules in a schema file attach nothing by themselves — they run only where an action declares `expect:`. An `expect:` block with neither `suite:` nor `expectations:` reads the rules of the file the action's own `schema:` names, so the co-located drop-in is just `expect: {repair: none}`. The compiled schema sent to a provider never contains any of it.

A suite file has no `repair`, `judge_budget`, or `context_scope` of its own — those stay on the action's `expect:` block; the file only supplies the rules.

## Row conditions

Every type accepts a `row_condition` argument: a guard-syntax condition deciding whether the rule applies to a record at all.

```yaml
- id: reason_is_substantive
  type: word_count_between
  field: density_reason
  params:
    min: 6
    max: 120
    row_condition: "exam_density != 'low'"
```

A record the condition does not hold for records a passing outcome marked `skipped`, naming the condition — so an exemption is visible in the verdict rather than being indistinguishable from a rule that never fired. The gate runs before the check, applies to record-scoped rules too, and the argument is never handed to the check itself.

A condition that *cannot be evaluated* — it names a field the record does not carry, or compares against an unquoted literal — is a different answer from one that is false, and it **fails the rule**. Waiving a rule on a condition that never ran would silence it exactly when the model omitted the field, which is the case the rule exists to catch.

The condition is preflight-checked like any other: it must parse, and every field it names must be one the action produces. Preflight can only check that the schema *declares* the field, not that a given record carries it — which is why the runtime treats an unevaluatable condition as a failure rather than an exemption.

To gate on a field a record may legitimately lack, say so with `IS NULL` / `IS NOT NULL`, which read an absent field as absent rather than failing to evaluate:

```yaml
    row_condition: "question_type IS NOT NULL and question_type == 'multiple_choice'"
```

A record without `question_type` waives the rule; one that has it is checked. Writing `question_type == 'multiple_choice'` alone would fail the rule on records that lack the field, which is the safe default but not what you meant.

## Preflight validation

`agac inspect` validates an `expect:` block before any LLM call is made:

- `votes` must be a positive integer.
- `context` must be a list of `action.field` strings; each referenced action must exist upstream and each field must appear in that action's declared output.
- Unknown parameters for a given `type` (e.g. `phrases` on `not_null`) are rejected — including for [your own registered types](#extending-with-your-own-checks), whose declared parameters are enforced exactly like built-ins'.
- Every entry must carry a `field:` (empty strings and empty lists are rejected too) — except `expression`, which must not, and rules declared on a field, which already have one.
- `expression` conditions and `row_condition` arguments are parsed and checked in full (syntax, blocklist, field references, constant conditions) — see [Expressions](#expressions).
- Superseded spellings are named, not merely rejected: arguments written flat instead of under `params:`, and `severity: fail` for `severity: error`. A key that merely *resembles* a rule key (`sevrity:`) is reported as that key rather than sent to `params:`.
- Rules a selector could never reach — declared on a nested member of a field rather than on the field itself — are refused rather than ignored, as is a record-scoped `expression` rule declared under a field.
- Preflight builds each suite the way the runner does, so rules declared on a schema's fields are checked too.

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
  params:
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

- **Repair runs in both modes, but it counts iterations differently.** Online, each record loops on its own: one record can take three generations while its neighbour passes first time. Batch loops the whole set — every round re-submits the records still failing, so `max_iterations` bounds the number of *batches*, not the number of tries any single record gets. A record that fails in round one and passes in round two has had two generations either way; what differs is that a batch round waits for the slowest record in it.
- **A judged `context:` ref is online only.** Batch validates from the stored result and has no `llm_context`, so a judged rule with `context:` refs is refused at preflight rather than failing every record on a missing context source.
- **Record granularity only for repair.** One file-granularity call produces the whole file, so a single failing record would regenerate all of them; preflight refuses `repair` on a `granularity: file` action. Observe mode works there — a response holding many records has each one validated and annotated independently, the same as an action whose LLM returns a JSON array.
- **No custom repair prompt.** The `repair: {prompt: $wf.X}` mapping form is reserved in the schema but not implemented; it is refused with a message saying so. Use `retry` or `auto`.
- **Tool actions cannot repair.** Re-running a deterministic UDF yields the same output, so `repair` on a `kind: tool` action is refused at preflight; observe mode works normally.
- **The prompt trace shows the original prompt.** A record repaired on iteration 2 or later has a stored trace pairing the *first* prompt with the *final* response, and that response carries the attached verdict.
- **`context:` refs are single-level.** `action.field` only — no nested paths into a wildcard element (`action.items[*].text` is not valid inside a `context:` ref).
- **Budget is per run, not persisted.** `judge_budget` resets each time the workflow runs; it does not track spend across separate `agac run` invocations.
