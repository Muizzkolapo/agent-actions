# Question rounds — a loop, a router and a join

An LLM writes one exam question per topic and a tool checks it. A question that fails is
written again, with the reasons, and checked again, up to three rounds. The questions that
passed are published; the ones that never passed are flagged for a human. Both are gathered
under one name at the end.

It runs offline: the workflow uses the `agac-provider` mock vendor, and `check_question`
stands in for a real validator by passing a question once its topic has been tried `bar`
times (1, 2 and 9 in the staged data). Set `model_vendor` and `model_name` in the
workflow's `defaults:` to use a real LLM.

## What it shows

| Entry | Becomes | What it does |
|---|---|---|
| `- loop: round` | `round_iter1__write` … `round_iter3__check`, and `round` | Runs the branch `question_round` (write → check) again for each record whose check failed. Round 2 and 3 read the previous check as `prior`; `round` holds the check of the last round that ran. |
| `- route: verdict` | `verdict` | Sends each record to `publish` or `flag_for_review` by `round.outcome`. |
| `- join: bank` | `bank` | Gathers the two branches again: one record per topic. |

See [Loops](https://docs.runagac.com/docs/reference/configuration/loops) and
[Routes and Joins](https://docs.runagac.com/docs/reference/configuration/routes).

## Run it

```bash
agac inspect -a question_rounds
agac run -a question_rounds
```

`agac inspect` shows the loop as one line:

```
  ✓  round            loop ×3 max, until check.passed == true (branch question_round, result check)
```

The run shows each round take fewer records: `photosynthesis` passes in round 1,
`plate tectonics` in round 2, and `the water cycle` never, so `round` holds its round-3
check and `verdict` sends it to `flag_for_review`.
