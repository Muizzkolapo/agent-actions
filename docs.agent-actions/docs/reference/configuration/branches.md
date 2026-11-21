---
title: Branches
description: Write a group of actions one time in a branch file, and include it in a workflow one or more times.
sidebar_position: 5
---

# Branches {/* #branches */}

A branch file holds a group of actions that you write one time and include in a workflow. The entry `- include: <name>` in the `actions:` list of a workflow puts the actions of `branches/<name>.yml` in the place of the entry. After the load, an included action is an ordinary action of the workflow.

Use a branch when more than one workflow runs the same actions. Also use a branch when one workflow runs the same actions more than one time. To include one branch more than one time, give each include an instance name with `as:` (see [One Branch, Several Instances](#as)).

To send each record to one of several instances by the value of a field, and to gather the instances again, see [Routes and Joins](./routes.md). A case of a router can name an instance, and a join can name an instance with one output.

## The Branch File {/* #branch-file */}

The load reads a branch file only from the `branches/` folder at the project root.

```yaml
# branches/question_round.yml
branch: question_round
description: Write one question, then review it
inputs:
  spec: The specification of the question
outputs: [review]
actions:
  - name: write
    intent: Write the question
    prompt: $question_round.Write
    schema: question
    dependencies: [spec]
    context_scope:
      observe: [spec.text]
  - name: review
    intent: Review the question
    prompt: $question_round.Review
    schema: review
    dependencies: [write]
    context_scope:
      observe: [write.question]
```

| Key | Required | What it holds |
|-----|----------|---------------|
| `branch` | Yes | The name of the branch. It must be equal to the file name without `.yml`. |
| `description` | Yes | Text that tells what the branch does. |
| `inputs` | No | A map from each input name to a description. An input is an action outside the branch that the branch reads. |
| `outputs` | No | The branch actions that the workflow can read. |
| `actions` | Yes | The actions of the branch, in the same form as in a workflow. |

The load refuses a branch file that breaks one of these rules:

- An action name uses only letters, digits and single underscores, and starts with a letter. It does not contain `__` and does not end with `_`.
- A prompt names a prompt store block (`prompt: $file.Block`). A branch file holds no inline prompt.
- A branch file is plain YAML. It holds no Jinja tag, because the load does not render it.
- A branch file does not include another branch.
- An input name is not also the name of a branch action.
- An action name is not a reserved name: `source`, `seed`, `version`, `workflow`, `prompt`, `schema`, `context_scope` or `action`. The message is the message for a workflow without an include: `Reserved action name 'source' cannot be used`.

## The Include Entry {/* #include-entry */}

```yaml
actions:
  - name: draft_spec
    intent: Write the specification
    prompt: $quiz.Draft_Spec
    schema: spec
  - include: question_round
    inputs: {spec: draft_spec}
```

| Key | What it does |
|-----|--------------|
| `include` | Names the branch file. |
| `as` | Gives the include its own instance name. The load then puts `<as>__` before the name of each branch action. |
| `inputs` | Binds each input of the branch to an action of the workflow. Each input must be bound. |
| `defaults` | Sets defaults for the actions of this include only, over the `defaults:` of the workflow. `data_source` is not permitted. |
| `override` | Maps a branch action to action keys. Each key replaces the value of the branch. `null` removes the key. |
| `remove` | Lists branch actions that this include leaves out. |

Without `as:`, an input must be bound to an action of the same name, because the branch reads the input by its own name.

## What an Action Can Read {/* #reads */}

The load checks each read after it expands the includes:

- An action of the workflow reads only the `outputs` of a branch.
- A branch action reads only the actions of its include and the actions that its inputs bind. It can also read the framework namespaces `source`, `seed`, `version` and `workflow`. The include check does not refuse a read of `prompt`, `schema` or `action`, but pre-flight refuses it.
- Inside an include with `as:`, a branch action reads a bound action only through its input. The load refuses a read of the bound action by its workflow name.

A dependency, a `context_scope` entry, a guard clause, a prompt, the source of `version_consumption` and the `context` of an `llm_judge` rule are reads. A read that the action inherits from `defaults:` is also a read.

## One Branch, Several Instances {/* #as */}

With `as:`, you can include one branch more than one time. Each include is an instance of the branch. The load gives each action of the instance the name `<as>__<name>`. Inside the branch, the actions keep their short names.

```yaml
actions:
  - name: draft_spec
    intent: Write the specification
    prompt: $quiz.Draft_Spec
    schema: spec
  - include: question_round
    as: c
    inputs: {spec: draft_spec}
  - include: question_round
    as: c2
    inputs: {spec: draft_spec}
  - name: publish
    intent: Publish the two reviews
    prompt: $quiz.Publish
    schema: published
    dependencies: [c__review, c2__review]
    context_scope:
      observe: [c__review.verdict, c2__review.verdict]
```

The load expands this workflow to the actions `draft_spec`, `c__write`, `c__review`, `c2__write`, `c2__review` and `publish`.

### Short names inside the branch {/* #short-names */}

Inside an instance, each short name means the action of the same instance, or the action that an input binds:

| Short name | In instance `c` | In instance `c2` |
|------------|-----------------|------------------|
| `write` | `c__write` | `c2__write` |
| `review` | `c__review` | `c2__review` |
| `spec` | `draft_spec` | `draft_spec` |

The load renames the short names in these keys of each action of the instance:

- `dependencies`
- the `observe`, `passthrough` and `drop` lists of `context_scope`
- the guard clause (`guard:`, or `condition:` under `guard:`). Only the action at the start of a field path changes. Text in quotes, numbers, keywords and spaces stay as written. A UDF guard is not changed, and at run time its function gets its data with the final names, for example `data["c2__write"]`.
- `version_consumption.source`
- the `context` list of each `llm_judge` rule in the `expect:` block of the action
- the same keys in the `defaults:` and the `override:` of the include entry

A version of a branch action keeps its suffix: `vote_1` becomes `c2__vote_1`. An entry with a `?` at the end keeps the `?`.

The prompts, the tools and the schema files of the branch also use the short names (see [Short names at run time](#short-names-at-run-time)).

The workflow reads the outputs of an instance by their final names, for example `c2__review`. The store, the logs and `agac inspect` also use the final names.

### Short names at run time {/* #short-names-at-run-time */}

One prompt, one tool function and one schema file serve all instances.

**Prompts.** The load puts an alias header before the prompt of each action of an instance. The header has one `{% set %}` tag for each short name that the prompt reads, and the prompt text stays as written. For this prompt store block:

```markdown
{prompt Review}
Review {{ write.question }} against {{ spec.text }}.
{end_prompt}
```

the prompt of `c2__review` in the rendered workflow is:

```jinja
{% set write = c2__write %}{% set spec = draft_spec %}Review {{ write.question }} against {{ spec.text }}.
```

The header outputs nothing and is on the first line of the prompt. The rendered text and the line numbers in an error do not change. A short name is also visible inside a macro that the prompt defines. Text in single braces, for example `{item.name}`, renders as written. The checks report it as a reference, as in a workflow without an include: `Referenced action 'item' does not exist in workflow`. The checks of `agac inspect` and `agac run` read a short name as the action that it means. They follow only the header that the load writes. A `{% set %}` tag that you write in a prompt is a local variable, as in a workflow without an include. The context JSON that the model gets with the prompt keeps the final names, for example `c1__write`, and the prompt text uses the short names. For example, if the prompt of `c2__review` reads `write.question` and the action does not observe `write`, the error says: `template references namespace 'c2__write' which is not declared in context_scope.observe or passthrough`.

**Tools.** A tool action of an instance gets its record under the short names. In instance `c2`, `data["write"]` holds the output of `c2__write`, and `data["spec"]` holds the output of `draft_spec`. The final names of these actions are not keys of `data`. Other keys, for example `source`, do not change. A tool at `granularity: file` gets its records with the final names.

```python
@udf_tool
def check_question(data, *args):
    question = data["write"]["question"]
    ...
```

**Schema files.** The `context` list of each `llm_judge` rule uses the short names. This applies to a rule on a field and to a rule in the `expectations:` block of the schema file. Each instance gets its own copy of the compiled schema, with the final names. A rule in a named `suite:` is not renamed.

```yaml
# schema/review.yml
name: review
fields:
  - id: verdict
    type: string
    expectations:
      - type: llm_judge
        params: {rubric: "The verdict fits the question", context: [write.question]}
```

`agac inspect` marks each action of an instance `from branch question_round as c2`. `agac inspect action` shows a `Names` row with the map of the instance, for example `write → c2__write, review → c2__review, spec → draft_spec`, and `--json` adds `instance` and `names` under `branch`.

### Inputs bind any action {/* #as-inputs */}

Under `as:`, an input can be bound to an action of any name. Two instances can read different actions, and one instance can read an output of another instance. In this example, round 2 reads the review of round 1:

```yaml
# branches/question_round.yml (inputs)
inputs:
  spec: The specification of the question
  previous: The review of the round before
```

```yaml
  - include: question_round
    as: c
    inputs: {spec: draft_spec, previous: draft_spec}
  - include: question_round
    as: c2
    inputs: {spec: draft_spec, previous: c__review}
```

An input bound to an action of another instance must name an output of that branch.

### What the load refuses {/* #as-refusals */}

| Problem | Example message |
|---------|-----------------|
| The instance name breaks the rule for action names. | `Include 'question_round' in agent_config/quiz.yml: 'as: c_': the name ends with '_'. Use letters, digits and single underscores, starting with a letter.` |
| Two includes have the same instance name. An include without `as:` has the branch name as its instance name. | `Workflow 'quiz' (agent_config/quiz.yml) includes branch 'question_round' (branches/question_round.yml) twice with the instance name 'c'. Give each include its own instance name with 'as:'.` |
| A branch action reads a short name that the branch does not define and that no input binds. | `Branch 'question_round' (branches/question_round.yml), included in agent_config/quiz.yml as 'c2', action 'review': reads 'draft', which the branch does not define and no input of include 'c2' binds. Branch actions: write, review. Inputs: spec.` |
| A short name of the branch is also the name of an action of the workflow. An input bound to the action of its own name is permitted. | `Include 'question_round' as 'c2' in agent_config/quiz.yml: the short name 'write' of branch 'question_round' (branches/question_round.yml) is also an action of workflow 'quiz'. Inside the include it means 'c2__write', so the branch could not tell the two apart. Rename one of them.` |

One branch cannot have an include without `as:` and an include with `as:` in the same workflow. The load refuses this with the message for a short name that is also a workflow action.

`agac inspect` loads the workflow in the same way, so it reports the same refusals.

### The name map {/* #name-map */}

The load writes the map of each instance into the `_include` key of each of its actions, under `names`. The rendered workflow in `artefact/rendered_workflows/` shows it:

```yaml
# The _include key of the action c2__review
_include:
  branch: question_round
  instance: c2
  local_name: review
  branch_file: branches/question_round.yml
  names: {write: c2__write, review: c2__review, spec: draft_spec, previous: c__review}
```

`_include` does not change the config hash of the action.

## See Also

- [Templates](./templates.md)
- [Configuration Reference](./index.md)
