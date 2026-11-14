---
title: AI Expectations
sidebar_position: 3
---

# AI Expectations

Schema validation finds structural problems, for example missing fields and wrong types. It cannot find semantic problems. A summary can be a string with a perfectly correct type and still give an incorrect statement of the source. A generated question can match its schema and still have no answer in the material that it was supposed to be grounded in.

`expect:` adds a validation layer on top of the schema and the guards. The layer has two kinds of checks:

- **Deterministic checks:** length, forbidden phrases, allowed values and regex.
- **LLM-judged checks (`llm_judge`):** These checks ask a model if a value satisfies an arbitrary natural-language rule. Optionally, the check grounds the value against the output of other actions.

You decide how much authority these results have:

- **Under `repair: none`**, the results are only a report. The verdict goes with the record and blocks nothing. If you want the verdict to gate a record, use it with a [guard](../execution/guards.md). The run still shows how many records failed. The line of the action changes to `⚠` and ends with `— N failed their checks`. [`agac dispositions`](../cli/dispositions.md) counts these records under **Failed checks**.
- **Under a repair policy**, the same rules start [regeneration](#repairing-instead-of-observing). They can also make a record a tombstone or halt the run immediately.

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

Each `expect:` entry runs after schema validation succeeds. It runs against the same record that schema validation accepted. The `expect:` block does not change the request to the LLM. It only judges the response.

:::note[Start with `repair: none`]
The example above uses observe mode. Observe mode runs the checks, attaches the verdict and continues. It costs nothing more than the checks, and it changes no behavior. Thus observe mode is the correct way to learn what your rules find before the rules can regenerate output. To enforce the rules, see [Repairing instead of observing](#repairing-instead-of-observing).
:::

:::note[Every form of `expect:`, run through the real preflight]
`tests/integration/fixtures/expectation_authors` contains seventeen small projects. Each project shows one way to write this block:

- Twelve projects are accepted. They include inline rules, a named `suite:`, rules on a schema field, `llm_judge` with `votes:`, a `row_condition`, a custom check and more.
- Five projects are refused. They cover an unreachable nested selector, a judged `context:` under batch, a flat-shape argument, `severity: fail` and `repair` at file granularity.

`tests/integration/test_expectation_authors.py` sends each project through `WorkflowInspector`. This is the same preflight that `agac inspect` runs. The test pins the exact refusal phrase for each refused form. These tests are the fastest way to see if Agent Actions accepts a shape, and what the framework says when it refuses the shape.
:::

## The `expect:` block

| Key | Type | Default | Purpose |
|-----|------|---------|---------|
| `expectations` | list | — | Inline list of expectation entries. You cannot use it with `suite`. If you omit both keys, Agent Actions reads the schema file of the action |
| `suite` | string | — | The name of a file in the schema path that holds rules. You use it in place of an inline list. The rules are on its fields, in its own `expectations:` block, or in the two places (see [Rules in the schema file](#rules-in-the-schema-file)) |
| `repair` | string or mapping | `auto` | How the model generates the output again after a **rule** failure: `none` (observe), `retry` (send the original prompt again), `auto` (send it again with composed feedback), or `{prompt: $wf.X}` (an authored template that holds the same failure list) |
| `structural` | string or mapping | `retry` | How the model generates the output again after a **schema** failure. The values are the same four values, but not `none`. See [Re-roll or steer](#re-roll-or-steer) |
| `max_iterations` | integer 1–10 | `3` | The total number of generations for each record, including the first. If you set it explicitly with `repair: none`, it is a configuration error, not a setting that does nothing |
| `on_exhausted` | string | `return_last` | The result when no iterations remain: `return_last`, `fail`, or `raise`. The same rule applies: do not set it under `repair: none` |
| `judge_budget` | integer ≥ 1 | no limit | The maximum number of real `llm_judge` LLM calls that the suite of this action may make in the full run |

Each entry in `expectations:` (or in a suite file) has this shape:

| Key | Required | Purpose |
|-----|----------|---------|
| `id` | no | A stable identifier. If you omit it, Agent Actions derives it from the type and the content of the rule |
| `type` | yes | A registered deterministic type, or `llm_judge` |
| `field` | yes* | The [field selector](#field-selectors) that this rule reads. When the rule is [declared on a field](#rules-in-the-schema-file), omit it. Agent Actions refuses it there, because the field already names what the rule tests. `expression` never takes a `field` |
| `params` | no | The arguments for this `type`, for example `min`/`max`, `phrases`, `rule`, `votes`, and the universal [`row_condition`](#row-conditions) |
| `severity` | no | `error` (default), `warn`, or `info`. See [Severity](#severity) |
| `hint` | no | The text that tells the model how to fix the output when `repair: auto` generates the output again |

These six keys are the full vocabulary. Agent Actions refuses, by name, any other key at the top level of a rule. Thus a mistyped `sevrity:` is an error at load. It is not an argument that the type does not recognize. Arguments that are specific to a type always go under `params:`.

Rules come from three sources. Thus the block of an action does not always show which rules the action gets. [`agac expect list`](../cli/expect.md) resolves the rules in the same way as the runner. It prints the rules that would run:

```bash
agac expect list -a my_workflow --action summarize
```

## Deterministic expectation types

| Type | Params | Checks |
|------|--------|--------|
| `not_null` | — | The value is not `None` and is not an empty string, list or dict |
| `no_null_fields` | `exclude` (list) | **Record-scoped**. No field in the full record is `None`. It takes no `field:`. `exclude` waives the fields that can correctly be null. Null is not the same as empty. An empty string is a value that the model chose. To reject an empty value on a named field, use `not_null` |
| `item_count` | `equals`, `min`, `max` (numbers) | The length of a list field |
| `word_count_between` | `min`, `max` (numbers) | The word count, with words split at whitespace |
| `word_count_ratio` | `max_ratio` (number) *(required)* | The ratio of the longest word count to the shortest word count in a list of items is not more than `max_ratio`. It finds one option in a list that is much longer than the other options |
| `accepted_values` | `values` (list) *(required)* | The value is one of the values in an explicit allow-list |
| `matches_regex` | `pattern` (string) *(required)*, `negate` (boolean) | The value matches a regex. With `negate: true`, the value must not match the regex |
| `match_like_pattern` | `like_pattern` (string) *(required)*, `negate` (boolean) | The full length of the value matches a SQL `LIKE` pattern. `%` is any sequence of characters. `_` is exactly one character. All other characters are literal |
| `no_forbidden_phrases` | `phrases` (list) *(required)*, `case_sensitive` (boolean) | The value does not contain any of the substrings in a list |
| `contains_terms_from` | `terms` (list) *(required)*, `min_matches` (number) | The value contains at least `min_matches` (default 1) terms from a list |
| `expression` | `condition` (string) *(required)* | A condition in guard syntax. Agent Actions evaluates it against the full record. See [Expressions](#expressions) |

Each parameter takes the value type that the table shows. Agent Actions refuses a value of another type when it loads the rule.
This occurs at preflight and at run time, with the same message. Agent Actions also refuses a list parameter that is given as a string.
The reason is that `params` hold literal values. Thus `terms: source.essay` would be the text
`source.essay`, not the field. A number is never a boolean, and a list is never a number.
The same rules apply to the parameters of [`llm_judge`](#llm_judge) and to the universal
[`row_condition`](#row-conditions). `row_condition` is a string under each type, your own types included.

```
quote_in_source: type 'contains_terms_from' takes parameter 'terms' as a list, got str 'source.essay'; params hold literal values, so a field name here is not read
```

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

A rule [declared on a field](#rules-in-the-schema-file) has no `field:` key. Its position names what it tests. In all other places, the `field:` that a rule reads has one of three shapes:

| Selector | Resolves to |
|----------|-------------|
| `summary` | The full value at that field. A check of the full value, for example `item_count` or `word_count_ratio`, needs this input |
| `options[*]` | One input for each element of the `options` array. The rule runs one time for each element |
| `[option_a, option_b]` | One input that holds the list `[value_of_option_a, value_of_option_b]`. Use it for checks that compare sibling fields |

A wildcard selector also works on arrays of objects. Agent Actions sends each element with no change. A value that is not a string is serialized to JSON before it goes into an `llm_judge` prompt:

```yaml
- id: each_step_is_actionable
  type: llm_judge
  field: steps[*]
  params:
    votes: 3
    rule: "The step is a concrete, executable instruction, not a vague restatement of the goal."
```

Nested paths inside a wildcard element (`options[*].text`) are not supported. Select the full element. Then the rule (or the check) can read the field that it needs.

## Expressions

`type: expression` evaluates a condition against the **full record**. It uses the same syntax as [guard](../execution/guards.md) conditions. The grammar is the same, but the field resolution is different. Thus you **cannot** use one condition string in the two places with no change. An `expect:` entry reads the output of its own action by bare name, as the example shows. A guard reads the namespaced stored record. Thus the same bare name usually resolves to a different value in a guard, or to nothing. For this reason, you cannot use one in place of the other. An `expression` takes no `field:`, because the condition names the fields that it reads:

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

Use `expression` when a rule reads multiple fields, or when it needs comparison logic that no single-field type can express. It is the declarative option between the built-in types and Python code.

Important behavior:

- **The detail of a false condition has the actual values** of each field that the condition read: `condition 'score >= 80' is false (score=64)`. Thus a reader (or a future repair loop) sees why the condition failed, not only that it failed.
- **A missing field is a failed outcome, not a crash**. The outcome has the message of the evaluator, which lists the fields that the record has.
- **A string literal with no quotes** (`verdict == approved` instead of `verdict == "approved"`) is a common typo. Agent Actions parses `approved` as a field reference. On records that do not have that field, the rule fails with a message that tells you to put quotes around the literal. Also, preflight flags the unknown field reference before any run.
- **Conditions with the `udf:` prefix are not supported** here. Guards support them. The Python extension point for expectations is [`@expectation_check`](#extending-with-your-own-checks). Preflight rejects a `udf:` condition with a message that gives exactly that reference.
- **Function calls (`LENGTH(...)` and other functions) are not available** in condition syntax.

Preflight validates each condition before any LLM call. It checks these items:

- The syntax.
- The blocklist of dangerous patterns.
- The field references against the schema of the action. Preflight checks a dotted path at its top segment.

Preflight also rejects a constant condition that refers to no record fields, because that condition always gives the same result.

## `llm_judge`

`llm_judge` asks an LLM if a value satisfies a natural-language `rule`. It is the only expectation type that makes its own model call. All the other types are pure functions of the resolved value.

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
| `rule` (string) | *(required)* | The natural-language criterion that the judge evaluates |
| `votes` (number) | `1` | The number of independent judge runs. The majority result is the verdict. A tie **fails closed**: an even split never counts as a pass |
| `model` (string) | the `model_name` of the action | The model that judges the value, in place of the default |
| `context` (list) | none | A list of `action.field` references. Agent Actions resolves them with the *same* `context_scope` mechanism as prompts. It sends them to the judge as grounding text |

### Testing a judge offline

On `model_vendor: agac-provider`, the judge receives a verdict object. Thus you can test a judged rule with no network and no key. The mock selects `passed: true` or `passed: false` with its seeded generator. It writes a generated sentence as the `reason`. The same rule and value give the same verdict on each run. Different values get the two verdicts, so the pass path and the fail path both run. The verdict does not judge the value. It tests the connections, not the rule.

### `context:` auto-injection

At load time, Agent Actions automatically adds each reference in `context:` to the `context_scope.observe` of the action. You do not need to also list the reference there. If you do list it, Agent Actions removes the duplicate. This applies to the inline `expectations:` list of an action and to the rules of its own schema. A named `suite:` is the exception. The layer that adds the references cannot load a suite. Thus you must list the references of a suite in `observe:` yourself. For this reason, `retrieve_passage.passage_text` is available to the judge in the example above. This is true although `answer_is_grounded` is on a different action than `retrieve_passage`.

### Caching and budget

- **Cache:** The key of a judge call is `(expectation, resolved value)`. Two records (or two rules) can produce byte-identical content for the same rule. Then Agent Actions gets the second result from the cache, and does not make another real LLM call.
- **Budget:** `judge_budget` on the `expect:` block sets the maximum number of real judge calls for all the records that the action processes in one run. Cache hits do not count. When the budget is exhausted, Agent Actions marks each subsequent judge outcome `skipped`. The message says that the budget is exhausted. A skipped outcome did not pass. Thus a skipped outcome with `error` severity is in **both** the `failed` list and the `skipped` list of the verdict. Agent Actions could not check the rule, and a rule that it could not check is not satisfied.
- **Failure isolation:** If the LLM call of the judge has an error (network, authentication, rate limit), only that outcome fails. The outcome has the error in its `detail`. The error does not stop the processing of the record.

## Severity

| Severity | Effect on `overall_pass` | Use for |
|----------|---------------------------|---------|
| `error` (default) | A failed outcome with `error` severity makes `overall_pass: false` | Hard requirements that you intend to check with a downstream guard |
| `warn` | Never blocks `overall_pass` | Important quality signals that do not block |
| `info` | Never blocks `overall_pass` | Diagnostics that you want to record but not enforce. It is the natural default for `llm_judge`, because the opinion of one model is evidence, not ground truth |

## Repairing instead of observing

Under a repair policy, the action does not only report the quality. It enforces the quality. If the suite of a record fails, the model generates the record again and Agent Actions validates it again. The total number of generations is `max_iterations` or fewer.

**What "regenerated" does is different in each run mode. No run mode starts the action again.** Regeneration does not enter the DAG again. Dependencies, guards and `context_scope` all ran one time, upstream. Agent Actions does not evaluate them again.

- **Online**, a failed record loops **in place**, inside the one call that produced it. The same call for that record runs again, with any `retry:` around it. For `retry`, the call uses `original_prompt`. For `auto`, it uses the composed-feedback prompt. The other records that the action processes do not change. A slow record does not delay the other records, and a fast record does not skip the check.
- **Batch** has no call to loop around. A round *is* a full batch submission, so there is nothing to enter again synchronously. In place of a loop, each round submits a **new, smaller batch**. The batch contains only the records that still fail. Agent Actions composes the feedback for each record exactly as it does online. The records that already passed go forward and are never submitted again. Here, `max_iterations` sets the maximum number of these rounds, not the number of tries that one record gets. For the effect on a record that fails in round one, see [Current limitations](#current-limitations).

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

Each iteration runs the **full** suite again, not only the rules that failed the last time. If a repair fixes one rule but breaks another rule, the repair does not pass. The only difference between the policies is what the regeneration prompt says:

- **`retry`** sends the original prompt again with no change. Use it when failures look like sampling noise.
- **`auto`** sends the original prompt again with composed feedback. The feedback has three parts: the previous output, each failed expectation with its detail and `hint`, and a list. The list gives the rules that already passed and must continue to pass. Use it when the model needs to know what was wrong.
- **`{prompt: $wf.Section}`** sends an authored template that holds the same failure list. Use it when you want different words from the built-in words. See [An authored repair prompt](#an-authored-repair-prompt).

### Re-roll or steer

The modes answer one question. When the output fails, you can send the same prompt again (re-roll). Or you can say something about the failure (steer).

A generation can fail in two ways, and each way has its own setting. `repair:` controls a **rule** failure. `structural:` controls a **schema** failure. A schema failure is output that was not a JSON object, or that did not conform to the schema of the action.

The two settings have different defaults because the two failures give different information:

- A rule failure names a specific defect in output that is usable in other respects. Thus the failure list is exactly what the regeneration needs. `repair` has the default `auto`.
- A schema failure means that there was no usable output to keep. Thus there is nothing to say other than the original instruction. `structural` has the default `retry`.

| You want | The block |
|---|---|
| Re-roll all failures, never steer | `expect: {repair: retry}` |
| Steer rule failures, re-roll malformed output (the default) | `expect: {repair: auto}` |
| Steer all failures | `expect: {repair: auto, structural: auto}` |
| Steer in your own words | `expect: {repair: {prompt: $wf.Fix}}` |
| Validate, never regenerate | `expect: {repair: none}` |

Use `structural: auto` when a model formats the output incorrectly in a *systematic* way, not occasionally. For such a model, blind re-rolls can use all the iterations. One line that names the expected fields would fix the output on the second attempt. The two keys use the same `max_iterations`. The count does not reset when the type of failure changes.

`structural:` has no `none` value. If you set it under `repair: none`, it is a configuration error. Nothing generates the output again, so there is nothing for `structural:` to describe.

### An authored repair prompt

`repair: {prompt: $wf.Section}` resolves through the same prompt-reference path that the `prompt:` of an action uses. The resolved text is the full regeneration prompt. Agent Actions fills it with the payload that `auto` composes:

| Placeholder | Holds |
|---|---|
| `{original_prompt}` | The action's rendered prompt |
| `{response_json}` | The output that failed |
| `{failed_lines}` | One bullet for each failed rule: the id, the detail and the `hint` of the author |
| `{passing_lines}` | The rules that already pass and must stay passing |

If a template names a placeholder that does not exist, preflight refuses the template. This occurs at preflight, not at the failure. Thus a typo is a configuration error. It is not a regeneration that loses its feedback with no message and looks like a re-roll.

The payload is the difference between this option and `retry`. An authored prompt that cannot see which rules failed can only repeat the instruction.

`max_iterations` counts the *total* number of generations. Thus `3` means the first attempt and a maximum of two repairs. When no iterations remain, `on_exhausted` sets the result:

| `on_exhausted` | What ships |
|---|---|
| `return_last` (default) | The last attempt, with its failed verdict attached. Thus a downstream guard can filter on the verdict. The record is stored `success` with reason `expectations_failed`. It is not cascade-blocked, `agac retry` does not run it again, and the action still ends `completed`. The run line shows the failures (`⚠ summarize  4 records in 0.1s — 3 failed their checks`). `agac dispositions` also shows them (**Failed checks**). If the last attempt is not a record (each iteration failed structurally), there is nothing to annotate. Then the attempt becomes a tombstone |
| `fail` | An `expectations_exhausted` tombstone that has the ids of the failed rules and the iteration count. The record is stored `exhausted`, online and under batch. The action ends `completed_with_failures` (`failed` when no record succeeds). `agac retry` runs the record again |
| `raise` | Nothing. The run halts with an error that names the action and the rules that still fail. Agent Actions records the halt, online and under batch. The next `agac run` refuses the action and does not call the model. [`agac retry`](../cli/retry.md#a-retry-resumes-a-halted-action-in-full) resumes the action. Under batch, the records where the run stopped are stored `exhausted`, not as answers |

:::note[See exhaustion happen]
`tests/integration/fixtures/runtime_probes/repair_exhaustion` is a rule that the mock provider can never satisfy, with `on_exhausted: return_last`. `tests/integration/test_runtime_probes.py` runs it through the real CLI. The test asserts that the record continues to exist with its last failed verdict attached. This is the concrete shape of the `return_last` row above. The `partial_file_rejection` workflow of the same fixture project shows the other side. If the first stage refuses a staging file, the run stops before it processes any file. Thus a run that exits 0 did stage each file.
:::

### Migrating from `reprompt:`

`reprompt:` was removed. Agent Actions refuses a configuration that has it at load. The error names the `expect:` block that
replaces it. The full migration is below. All four blocks that can contain `reprompt:`
refuse it: an action, `defaults:`, a top-level `agents:` entry, and the `default_agent_config:` block
of `agent_actions.yml`. Thus if you move it up a level, the workflow still gets the error.

**A block that only checked the schema** (the common case) becomes an `expect:` with no rules. Set it
one time for the workflow:

```yaml
# before                                  # after
defaults:                                 defaults:
  reprompt:                                 expect:
    on_schema_mismatch: reprompt              repair: auto
    max_attempts: 3                           max_iterations: 3
    use_self_reflection: true                 structural: auto
    on_exhausted: return_last                 on_exhausted: return_last
```

`structural: auto` keeps the schema feedback that the `reprompt:` block sent. If you do not set it, a schema failure
sends the original prompt again. This is usually what you want, because a response that the schema
rejected has no partial result to keep.

`use_self_reflection` has no replacement and does not need one. It added one fixed question.
`repair: auto` sends the actual failure with the `detail` and `hint` of each rule.

**A block that names a `validation:` tool** becomes a rule. Most of these tools are the same as a built-in type:

| The tool checked | The rule |
|---|---|
| no field came back null | `no_null_fields` |
| a field matches a pattern | `matches_regex` |
| the length of a field | `word_count_between`, `item_count` |
| a field is one of a set | `accepted_values` |
| the response parsed | nothing. The structural gate does this check |

A check that is really specific to the project becomes an [`@expectation_check`](#extending-with-your-own-checks).
It returns `(passed, detail)`, not only a boolean. Thus the failure goes into the repair
prompt, not only into the log.

**`on_schema_mismatch:` was also removed.** `expect: {repair: auto}` does what `reprompt` mode did.
`reject` (halt, and do not generate again) becomes `max_iterations: 1` with `on_exhausted: raise`.

**A run deferred during a reprompt** cannot resume. Its stored state names a recovery phase that this
version does not run. Agent Actions refuses the run and does not read it in a different way. Run the action again with `--fresh`. The
records that the run completed before are in the store.

## Setting it once for a workflow

An `expect:` block can be in `defaults:`. There, each action inherits it:

```yaml
defaults:
  expect: {repair: auto, max_iterations: 3}

actions:
  - name: classify_genre
    expect:
      expectations:
        - {type: matches_regex, field: code, params: {pattern: '^[A-Z]{3}\d{6}$'}}
```

The two blocks merge **key by key**, and the block of the action wins. Thus you can set the policy where you decide it. The repair policy is usually a choice for the full workflow, but rules belong to one action. An action can add rules and not set `repair`. That action keeps the policy of the workflow. It does not use the default.

An inherited block adapts to the action that receives it. Tool actions and file-granularity actions cannot repair. A deterministic tool gives the same output when it runs again, and one file call produces each record. Thus Agent Actions does not apply an inherited repair policy to these actions:

- If the block has rules, the action continues to validate but does not repair.
- If the block has no rules, Agent Actions drops the block.

A policy that you write **on** the action is your decision. If the action cannot obey it, preflight reports it.

## A block with no rules

Under a repair policy, an `expect:` block does not need rules:

```yaml
defaults:
  expect: {repair: auto}
```

This block is the structural contract alone. The output of each action must conform to its schema. If the output does not conform, the model generates it again. This block is the smallest way to enable schema enforcement for all of a workflow.

Under `repair: none`, Agent Actions refuses this block. With no rules and no repair, nothing would be checked and nothing would be generated again. Agent Actions also refuses an empty inline `expectations: []`. The reason is that it looks like a list that you intended to fill, not a list that you left empty on purpose.

## Where results land

Agent Actions attaches the results to the record under an `expect` key, next to the schema fields of the action:

```json
{
  "summary": "...",
  "expect": {
    "overall_pass": true,
    "failed": [],
    "skipped": [],
    "outcomes": [
      {"id": "summary_present", "type": "not_null", "severity": "error", "passed": true, "detail": "", "definition_hash": "3f9a1c2d7b40", "skipped": false},
      {"id": "summary_length", "type": "word_count_between", "severity": "warn", "passed": false, "detail": "212 words, expected at most 200", "definition_hash": "a81e5b60c3d2", "skipped": false},
      {"id": "summary_grounded", "type": "llm_judge", "severity": "info", "passed": true, "detail": "3/3 judge votes passed", "definition_hash": "c07d44e9b1a6", "skipped": false}
    ]
  }
}
```

The `skipped` list holds the rules with `error` severity that Agent Actions could **not** check. A judge whose budget is exhausted is an example. A rule that its `row_condition` waived passed, and it is not in the list. Skips with `warn` or `info` severity are also not in the list, because they cannot change `overall_pass`. Each skip is still in `outcomes[]` with `skipped: true` and its reason in the detail. Thus you can tell "did not apply" from "could not tell".

`summary_length` failed and is still recorded in `outcomes`. But it is not in `failed` and it does not change `overall_pass`. The two count only outcomes with `error` severity, and that rule is `severity: warn`. This is the purpose of `warn`. The finding is on the record, but it does not gate anything.

To read the verdicts of a full run, use [`agac expect report`](../cli/expect.md#expect-report). The report shows which rule fails most often, and on which action:

```bash
agac expect report -a my_workflow
```

To make CI fail when the quality decreases, give it a threshold. [`--fail-under`](../cli/expect.md#gating-ci-with-a-threshold) exits with a non-zero code when an action is below the threshold. It also exits non-zero when the expectations of an action were never checked.

To use the verdict inside the workflow, read it from a downstream [guard](../execution/guards.md):

```yaml
- name: publish_summary
  dependencies: [summarize_article]
  guard:
    condition: 'summarize_article.expect.overall_pass == true'
    on_false: filter
```

## Rules in the schema file

An inline `expectations:` list applies to one action only. You can declare the rules in the schema file, on the fields that they test. This lets you use the same rules again. It also keeps the shape of a field and its quality rules together:

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

A rule under a field takes no `field:`. Its position is the selector. If you declare a `field:` there, it is an error, not only a repetition. This also prevents a full class of mistakes: a rule cannot name a field that the schema does not declare.

Rules that are about no single field go in the top-level `expectations:` block of the file. There, they have `field:` as usual:

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

A file may have one of the two forms, or both forms. A file with only rules and no `fields:` is still a valid suite. This is the portable form that an external stack uses.

### Binding a suite to an action

```yaml
- name: summarize_article
  schema: grounded_summary
  expect:
    repair: none
```

`suite:` names a different file. Agent Actions resolves it through the schema path exactly as it resolves `schema:`. It finds the file by name in the project-level and workflow-level schema directories that `schema_path` in `agent_actions.yml` names:

```yaml
  expect:
    repair: none
    suite: shared_summary_rules
```

Rules in a schema file do nothing alone. They run only where an action declares `expect:`. An `expect:` block with no `suite:` and no `expectations:` reads the rules of the file that the `schema:` of the action names. Thus, to use the rules in the same file, you only add `expect: {repair: none}`. The compiled schema that Agent Actions sends to a provider never contains these rules.

A suite file has no `repair`, `judge_budget`, or `context_scope` of its own. These keys stay on the `expect:` block of the action. The file only supplies the rules.

## Row conditions

Each type accepts a `row_condition` argument. It is a condition in guard syntax that decides if the rule applies to a record.

```yaml
- id: reason_is_substantive
  type: word_count_between
  field: density_reason
  params:
    min: 6
    max: 120
    row_condition: "exam_density != 'low'"
```

If the condition is false for a record, the record gets a passed outcome marked `skipped`. The outcome names the condition. Thus you can see an exemption in the verdict, and you can tell it from a rule that never ran. The gate runs before the check. It also applies to record-scoped rules. Agent Actions never gives the argument to the check.

A condition that *cannot be evaluated* is different from a false condition, and it **fails the rule**. For example, the condition names a field that the record does not have, or compares against a literal with no quotes. Agent Actions does not waive a rule on a condition that never ran. Such a waiver would silence the rule exactly when the model omitted the field. That is the case that the rule must find.

Preflight checks the condition as it checks all other conditions. The condition must parse, and each field that it names must be a field that the action produces. Preflight can only check that the schema *declares* the field. It cannot check that a given record has the field. For this reason, the runtime treats a condition that it cannot evaluate as a failure, not as an exemption.

A record may correctly not have a field. To gate on such a field, use `IS NULL` / `IS NOT NULL`. These operators read an absent field as absent, and the evaluation does not fail:

```yaml
    row_condition: "question_type IS NOT NULL and question_type == 'multiple_choice'"
```

A record that does not have `question_type` waives the rule. A record that has `question_type` is checked. If you write only `question_type == 'multiple_choice'`, the rule fails on records that do not have the field. That is the safe default, but it is not what you meant.

## Preflight validation

`agac inspect` validates an `expect:` block before the workflow makes any LLM call:

- `votes` must be a positive integer.
- Each parameter must have the value type that its type declares. See [Deterministic expectation types](#deterministic-expectation-types) and [`llm_judge`](#llm_judge).
- `context` must be a list of `action.field` strings. Each referenced action must exist upstream. Each field must be in the declared output of that action.
- Unknown parameters for a given `type` (for example, `phrases` on `not_null`) are rejected. This includes [your own registered types](#extending-with-your-own-checks). Their declared parameters are enforced exactly as the parameters of built-in types are.
- Each entry must have a `field:`. Empty strings and empty lists are also rejected. There are two exceptions. `expression` must not have a `field:`. A rule declared on a field already has one.
- `expression` conditions and `row_condition` arguments are parsed and checked in full (syntax, blocklist, field references, constant conditions). See [Expressions](#expressions).
- A refusal names what is valid, not what was replaced. For arguments written flat, the message says to move them under `params:`. For a `severity:` that is not a level, the message names the levels. A key that only *resembles* a rule key (`sevrity:`) is reported as that key. It is not sent to `params:`.
- Some rules are declared on a nested member of a field, not on the field itself. A selector can never reach these rules. Preflight refuses them and does not ignore them. Preflight also refuses a record-scoped `expression` rule declared under a field.
- Preflight builds each suite in the same way as the runner. Thus preflight also checks the rules declared on the fields of a schema.

```bash
agac inspect -a my_workflow
```

If the command shows the action list, these checks passed.

## Extending with your own checks

If the built-in types and `expression` conditions are not sufficient, register a check for your project with the `expectation_check` decorator. This is the same pattern as `udf_tool` for tool actions. The check is a pure function. It receives one resolved value and the parameters of the entry. It returns `(passed, detail)`:

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

- **The location of the file:** Any location under the tool path of your project (`tools/` by default). This is the same directory as the tools of tool actions. Discovery imports any file there that declares the decorator. Discovery always skips files with the `_` prefix and the `test_` prefix. Thus a check in `_helpers.py` never registers, and no message tells you.
- **When it registers:** At configuration load, before preflight. Thus `agac inspect` validates the parameters of your type (`params=`, `required=`) exactly as it validates a built-in type. An unknown parameter or a missing required parameter on your type is a preflight defect.
- **Failure detail:** Write the `detail` string to name the observed value (`"'X' has an invalid check digit"`). Do not repeat the rule. A reader sees this string in the verdict of the record.
- **A check that raises an exception** does not stop the record with a crash. The outcome fails with `check raised {ExceptionType}: {message}`. Agent Actions logs the traceback at warning level.
- **Name collisions fail with an error:** A check can use the name of a built-in type (or `llm_judge`/`expression`). Then Agent Actions raises an error at load. The error names the file. If two different files or functions register the same name, Agent Actions raises a duplicate-function error. It is safe to import the same file again.

Use the tiers in this order of preference:

1. A built-in type (zero code).
2. An `expression` condition (declarative, across fields).
3. `llm_judge` (semantic, natural language).
4. A custom check. This is Python code that you then own and test.

## Current limitations

- **Repair runs in the two modes, but each mode counts iterations differently.** Online, each record loops independently. One record can take three generations while another record passes the first time. Batch loops the full set. Each round submits again the records that still fail. Thus `max_iterations` sets the maximum number of *batches*, not the number of tries that one record gets. A record that fails in round one and passes in round two had two generations in the two modes. The difference is that a batch round waits for its slowest record.
- **A judged `context:` reference works online only.** Batch validates from the stored result and has no `llm_context`. Thus preflight refuses a judged rule with `context:` references. Without this refusal, each record would fail because the context source is missing.
- **Repair works at record granularity only.** One file-granularity call produces the full file. Thus one failed record would make the model generate all the records again. Preflight refuses `repair` on a `granularity: file` action. Observe mode works there. Agent Actions validates and annotates each record of a response independently. This is the same as for an action whose LLM returns a JSON array.
- **Tool actions cannot repair.** A deterministic tool gives the same output when it runs again. Thus preflight refuses `repair` on a `kind: tool` action. Observe mode works at record granularity.
- **A tool or HITL action at file granularity never runs its rules.** A strategy that does not evaluate expectations processes these actions. Preflight does not refuse the combination. Thus an `expect:` block on such an action does nothing, and no message tells you. `kind: hitl` is always file granularity, so this is true of each HITL action. [`agac expect list`](../cli/expect.md#rules-that-will-not-run) marks such an action. It does not show that the rules run.
- **`context:` references have one level only.** Use only `action.field`. Nested paths into a wildcard element are not valid (`action.items[*].text` is not valid inside a `context:` reference).
- **The budget applies to one run and is not persisted.** `judge_budget` resets each time the workflow runs. It does not track the cost across separate `agac run` invocations.
