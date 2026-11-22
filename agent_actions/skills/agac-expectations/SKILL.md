---
name: agac-expectations
description: Declare output-quality rules with expect blocks in agent-actions, and calibrate them before they may block records. Triggers on expect, expectations, llm_judge, votes, judge_budget, judge_mode, repair, on_exhausted, accepted_values, matches_regex, word_count_between, no_forbidden_phrases, overall_pass, verdicts, or "how do I check that the model produced something good".
---

# Agent Actions Expectations

Declare output-quality rules with expect blocks in agent-actions, and calibrate them before they may block records.

An action's schema says what shape its output takes. An expectation says what makes the output good enough. You write the rule once. agent-actions runs it on each record, writes a verdict on the record, and can ask the model to repair a failed output.

## Terms

| Term | Meaning in this skill |
|---|---|
| output | What the action wrote for one record |
| rule | One expectation: an `id`, a `type`, usually a `field`, and `params` |
| verdict | The `expect` object that agent-actions writes on the record |
| judge | A model call that an `llm_judge` rule makes to decide a rule that code cannot decide |
| repair round | One more model call for a record whose output failed a rule, with the rule's `hint` |

## Rules

1. **Put type arguments under `params:`.** `id`, `type`, `field`, `severity` and `hint` stay at the top of the rule. A rule with `values:` at the top level is refused at preflight.
2. **Use a code rule when code can decide.** An `llm_judge` costs one model call for each vote, each record and each repair round. A regex, a value list or a length check costs nothing.
3. **Never let a judge vote on a missing or empty field.** Put `not_null` on the field before the `llm_judge` rule. A field that is missing fails the rule with its reason. A field that is present but empty goes to the judge, the judge votes FAIL, and each repair round repeats the same failure.
4. **Calibrate before a rule may block.** Run a new rule with `severity: warn` on known-good outputs first. Make it `error` only when the known-good outputs pass it. If they fail it, the rule is wrong, not the outputs.
5. **Count the cost of repair.** `max_iterations: 3` with `votes: 5` can make 15 judge calls for one record. Set `judge_budget` to cap the judge calls of the action.

## The shape

```yaml
expect:
  repair: auto            # none | retry | auto
  max_iterations: 2       # the first generation counts (1-10)
  on_exhausted: return_last
  expectations:
    - id: priority_is_known
      type: accepted_values
      field: priority
      params:
        values: [urgent, high, normal, low]
      hint: "priority must be one of urgent, high, normal, low."
```

Rules can be in three places:

| Where | Use it for |
|---|---|
| `expectations:` under `expect:` | Rules for one action |
| The action's schema file, under the field | Rules that go with the shape wherever it is produced |
| A named suite (`suite: <name>`), a schema-path file with an `expectations:` block | One set of rules for several actions |

`expect: {repair: none}` with no `suite:` and no `expectations:` reads the rules from the action's own schema file.

## Types

| Type | Required params | Checks |
|---|---|---|
| `not_null` | — | The field is not null, and not an empty string, list or object. A string of only spaces passes: use `matches_regex` with `pattern: '\S'` to refuse it |
| `no_null_fields` | (+ `exclude`) | No field of the output is null (an empty string is not null) |
| `accepted_values` | `values` | The value is one of a fixed set |
| `word_count_between` | `min`, `max` | Length in words |
| `word_count_ratio` | `max_ratio` | Length compared with another field |
| `matches_regex` | `pattern` (+ `negate`) | A pattern that must match, or with `negate: true` must not match |
| `match_like_pattern` | `like_pattern` (+ `negate`) | An SQL LIKE pattern |
| `no_forbidden_phrases` | `phrases` (+ `case_sensitive`) | Words that must not appear |
| `contains_terms_from` | `terms`, `min_matches` | Coverage of a word list |
| `item_count` | `min` / `max` / `equals` | Length of an array |
| `expression` | `condition` | A condition across several fields of the record |
| `llm_judge` | `rule` (+ `votes`, `context`, `model`) | A rule that only a reader can decide |

Each type also takes `row_condition` inside `params:`. It decides if the rule applies to this record. True runs the rule. False waives it. A condition that cannot be evaluated fails the rule.

```yaml
      params:
        min: 20
        max: 200
        row_condition: "ticket_kind IS NOT NULL and ticket_kind == 'bug_report'"
```

## The judge

```yaml
expect:
  repair: auto
  max_iterations: 2
  on_exhausted: return_last
  judge_budget: 400
  expectations:
    - id: summary_has_text
      type: not_null
      field: summary
    - id: summary_states_only_ticket_facts
      type: llm_judge
      field: summary
      params:
        votes: 3
        rule: >
          Every fact in the summary is stated in the ticket. A fact that the ticket
          does not state fails the rule, even if it is true.
        context: [source.ticket_text]
      hint: "Remove or correct the facts that the ticket does not state."
```

1. `votes: 3` runs 3 independent judge calls and takes a strict majority. A tie fails. The detail keeps the tally and the dissent, for example `2/3 judge votes passed: ...`.
2. `context:` gives the judge other fields of the record. Name only what the rule needs.
3. Judge calls follow the run mode of the action. Set `judge_mode: batch` or `judge_mode: online` under `expect:` to choose. `judge_mode: batch` needs `run_mode: batch`.
4. Write the rule as a pass condition that a careful reader can check from the field and the context alone. Give one example that passes and one that fails, if the rule has a known trap.

For calibration, read [references/calibration.md](references/calibration.md).

## Severity and the verdict

`error` (the default) fails the record: the rule goes into `failed`, and `overall_pass` becomes false. `warn` records the failure and does not change `overall_pass`. `info` is a note.

```json
{"overall_pass": false,
 "failed": ["priority_is_known"],
 "skipped": [],
 "outcomes": [{"id": "priority_is_known", "severity": "error", "passed": false, "detail": "value 'High' is not one of ['urgent', 'high', 'normal', 'low']"}]}
```

Guard on `overall_pass` or `failed`, not on "no outcome failed", because a failed `warn` rule also has `passed: false`:

```yaml
guard: { condition: 'triage_ticket.expect.overall_pass == true', on_false: "filter" }
```

A rule that `row_condition` waived reports `passed: true, skipped: true`. It is in neither list.

## When repair rounds are used up

| `on_exhausted` | The record |
|---|---|
| `return_last` (default) | Keeps the last output, with its failed verdict. The next actions see it |
| `fail` | Fails. The record stops at this action |
| `raise` | Stops the action |

With `return_last`, a rule that fails on every record does not stop the run. Every record keeps a failed verdict, and a guard downstream filters them. The run can end with exit code 0 and few usable records. Check the counts after each run (see the `agac-operations` skill, Health check).

## When NOT to use an expectation

An expectation judges one record's output against a stated rule. Keep a tool action or a group of actions for the cases below:

1. **A comparison of two groups.** A rule cannot measure the difference between a control group and a test group. No single field holds that signal.
2. **A rule across records.** Duplicates, uniqueness across a file and set coverage are concerns of a set. Use a tool at `granularity: file`.
3. **A judge that must not see part of the record.** An expectation reads the record as it stands. If the judge must not see a reference value, or ids that reveal it, build the hidden view in a tool first (see the `agac-blind-verification` skill).
4. **A check that a tool already does well.** Keep it.

The test: can a careful reader decide the rule from this one record and the rule text? Yes: an expectation. No: keep the tool or the actions.

## Gotchas

1. **Rule ids must be unique in a suite.** The id names the outcome and links a hint to its rule.
2. **A rule on a field that the action does not produce is refused at preflight**, with the field name.
3. **`repair: auto` is refused on a `kind: tool` action.** A tool gives the same output again. Use `repair: none`.
4. **`repair` cannot run at `granularity: file`.** Use `repair: none`, or put the rule on the record action before it.
5. **`structural:` handles schema failures, `repair:` handles rule failures.** `structural: retry` (the default) sends the same prompt again. `structural: auto` sends the schema feedback.

See [Expectations](https://docs.runagac.com/docs/reference/validation/expectations), [Output validation](https://docs.runagac.com/docs/reference/validation/output-validation) and [agac expect](https://docs.runagac.com/docs/reference/cli/expect).
