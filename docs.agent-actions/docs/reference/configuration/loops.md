---
title: Loops
sidebar_position: 7
---

# Loops {/* #loops */}

A loop runs a [branch](./branches.md) again for each record whose check failed, up to a fixed number of times. Each new iteration reads the verdict of the one before, so a writer can fix what a checker found. After the loop, one name holds the output of the last iteration that ran for each record. Write a loop with a `- loop:` entry in the `actions:` list of a workflow. The load expands it into ordinary actions.

```yaml
# branches/question_round.yml
branch: question_round
description: Write a question, then check it
inputs:
  spec: the topic of the record
  prior: the check of the previous iteration
outputs: [check]
actions:
  - name: write
    intent: Write the question
    prompt: $quiz.Write              # {% if prior %}Fix this: {{ prior.reasons }}{% endif %}
    schema: draft
    dependencies: [spec]
    context_scope: { observe: [spec.topic, prior.*] }
  - name: check
    kind: tool
    impl: check_question
    intent: Check the question
    schema: verdict                  # passed: boolean, reasons: string
    dependencies: [write]
    context_scope: { observe: [write.question, spec.*, prior.*] }
```

```yaml
# agent_config/quiz.yml
actions:
  - name: spec
    # ...
  - loop: round
    include: question_round
    max_iterations: 3
    inputs: { spec: spec }
    feedback: { prior: check }       # in iteration k, prior is the check of iteration k-1
    until: check.passed == true      # a record leaves the loop once this holds
    result: check                    # `round` holds the check of the last iteration that ran
  - name: publish
    dependencies: [round]
    # ...
    context_scope: { observe: [round.*] }
```

## The Loop Entry {/* #loop-entry */}

| Key | What it does |
|-----|--------------|
| `loop` | Names the loop. Actions below the loop read this name. The rule for action names applies; the name cannot end with `_` and digits, which reads as a version. |
| `include` | The branch file that one iteration runs. |
| `max_iterations` | Required. How many times the branch may run for a record, from 1 to 10. |
| `inputs` | Binds the inputs of the branch to actions of the workflow, as on an include. Every iteration reads the same actions. |
| `feedback` | Maps an input of the branch to an action of the branch. In iteration 2 and later, the input is that action of the previous iteration. In iteration 1 it is none. The action must be listed under `outputs:` of the branch. |
| `until` | A guard condition on the fields of the branch actions, written with their short names (`check.passed == true`). It may read only actions that run up to `result`, and only fields their schemas declare. |
| `result` | The action of the branch whose output the loop name holds. It must be listed under `outputs:` of the branch. |

## How a Record Goes Through {/* #loop-iterations */}

- Iteration 1 runs the branch on every record.
- After each iteration, `until` is checked for each record on the output of that iteration. A record for which it holds leaves the loop. A record for which it does not hold runs the next iteration, if one is left.
- The loop name, `round` above, holds one output for each record: the `result` of the last iteration that ran for it. For a record that passed, that is the iteration that passed. For a record that never passed, it is the last iteration (as `on_exhausted: return_last` keeps the last answer of an [`expect` repair](../validation/expectations.md#repairing-instead-of-observing)). Read `until`'s fields from the loop name to tell the two apart.
- A record that fails inside an iteration (an error, not a check that does not pass) stops there, as a failed record stops anywhere: the loop name holds nothing for it until [`agac retry`](../cli/retry.md) answers it. The retry continues the loop from that iteration.

### Feedback {/* #loop-feedback */}

A feedback input is the action of the previous iteration that it names. A prompt reads it by its short name, and a tool reads `data["prior"]`. In iteration 1 there is no previous iteration: a prompt reads `prior` as none, so write `{% if prior %}...{% endif %}` around what it reads of it, and a tool gets no `prior` key. A `context_scope` entry that reads a feedback input is left out of iteration 1.

A guard cannot read a feedback input, since iteration 1 could not evaluate it; read it in the prompt or the tool instead.

Prompts get no iteration number.

## What the Load Makes of It {/* #loop-expansion */}

The loop is unrolled when the workflow loads, into `max_iterations` instances of the branch and one action named after the loop:

- Iteration `k` is the include instance `<loop>_iter<k>`, so its actions are named `round_iter1__write`, `round_iter1__check`, `round_iter2__write`, and so on. The separator `_iter` keeps an instance name from ending with `_` and digits, which would read as a version.
- From iteration 2, each action that starts the branch (one that depends on no other action of it) depends on the `result` of the previous iteration only, and gets the guard `NOT (<until of the previous iteration>)` with `on_false: filter`. A record that passed is recorded `filtered` with the reason `sent_elsewhere`, as a record a [router](./routes.md) does not send to a branch. It is not reported as filtered, and it is not dead below: the loop name gathers it back. A record with no output in the previous iteration does not satisfy `NOT (...)`, so it never runs again.
- The loop name is a built-in tool action that depends on the `result` of every iteration and writes the output of the last one the record holds. Its schema is the schema of `result`.

Each iteration is an ordinary action in the status file, the storage and the run output. A stop after any iteration, then `agac run`, starts the next iteration; finished iterations do not run again.

## What the Load Refuses {/* #loop-refusals */}

The load, and so `agac inspect` and `agac run`, refuse:

- `max_iterations` that is not a whole number from 1 to 10;
- a `feedback` input the branch does not declare, or one also bound under `inputs:`, or one whose action the branch does not list under `outputs:`;
- a `result` the branch does not list under `outputs:`, or one with versions;
- an `until` that does not parse, is a UDF, reads no field, reads anything but a field of an action that runs up to `result`, or reads a field its schema does not declare;
- an action that starts the branch and has a guard of its own (put the condition on the next action), and a guard or version source that reads a feedback input;
- an action of the branch that runs at File granularity: a loop runs each record on its own;
- an action outside the loop that reads an iteration's action (`round_iter2__check`) instead of the loop name;
- an unknown key, and a name that is taken or breaks the name rule.

## In agac inspect {/* #loop-inspect */}

`agac inspect` shows the loop as one line, with its limit and its condition, and none of its iteration actions:

```
  ✓  spec
  ✓  round    loop ×3 max, until check.passed == true (branch question_round, result check)
  ✓  publish
```

`agac inspect action round_iter2__write` still shows one iteration's action, with its generated guard.

[`agac docs`](../documentation-site.md) lists each iteration's actions and the action named after the loop. In the editor, the loop's name resolves to its `- loop:` entry; an action of its branch is not an action of the workflow. The example [`examples/question_rounds`](https://github.com/Muizzkolapo/agent-actions/tree/main/examples/question_rounds) runs a loop, a router and a join offline.

## A Loop or an `expect` Repair {/* #loop-or-repair */}

An [`expect` repair](../validation/expectations.md#repairing-instead-of-observing) generates one LLM action's output again until its own rules pass. Use it when the rules that judge the output belong to that action. Use a loop when the verdict comes from later actions (a tool, a validator LLM, an examiner), when more than one action must run again, or when the next attempt must read what those actions found.
