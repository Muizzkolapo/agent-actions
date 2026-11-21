---
title: Routes and Joins
description: Send each record to one branch by the value of one field, and gather the branches again.
sidebar_position: 6
---

# Routes and Joins {/* #routes */}

A router sends each record to one branch, chosen by the value of one field. A join gathers the branches again under one name. Write a router with a `- route:` entry and a join with a `- join:` entry in the `actions:` list of a workflow. The load expands both into ordinary actions.

```yaml
actions:
  - name: route_focus
    kind: tool
    impl: assign_format
    intent: Decide the format of each record
    schema: route_focus_out          # format: enum [multi_choice, matching, fill_blank, true_false]
    context_scope: { observe: [source.text] }

  - route: format_router
    on: route_focus.format
    cases:
      multi_choice: [mc_write]       # the actions that start the branch
      matching: m                    # an include instance: its first actions
      fill_blank: [fb_write]
    default: [other_write]           # or: default: filter

  - name: mc_write
    intent: Write a multiple-choice item
    prompt: $quiz.Mc_Write
    schema: mc_item
    context_scope: { observe: [source.text] }
  # ... fb_write, other_write ...
  - include: format_branch
    as: m

  - join: bank
    of: [mc_write, m, fb_write, other_write]

  - name: publish
    dependencies: [bank]
    # ...
    context_scope: { observe: [bank.*] }
```

## The Route Entry {/* #route-entry */}

| Key | What it does |
|-----|--------------|
| `route` | Names the router. The name follows the rule for action names. It cannot end with `_` and digits, which reads as a version. |
| `on` | The field that chooses the branch, as `<action>.<field>`. The action is an action of the workflow, or `source`. |
| `cases` | Maps each value of the field to its branch: an include instance, or a list of the actions that start the branch. A case value is a string. Quote a value that YAML reads as another type (`"yes"`). The field must hold strings. |
| `default` | Required. The branch of a record whose value has no case, written like a case. `default: filter` filters such a record at the router instead. |

A record enters one branch only. The other branches do not see it.

The router compares the value of the field with each case exactly. The comparison is case-sensitive, and the router does not remove spaces: `"A"` and `"a "` do not match the case `a`. A value that is not a string never matches a case. Thus the load refuses a router on a field whose schema type is not `string`. It also refuses a field whose `enum` holds a value that is not a string. A type list or an `enum` can also hold `null`. A field with no schema, for example a `source` field, can hold a value of another type. Then the router fails that record with an error that names the type, for example `source.tier holds 1 (int); a router matches strings only`. This also occurs with `default: filter`.

### What the load makes of it {/* #route-expansion */}

- The router is a tool action named as the entry. It reads the field once and writes `case`: the value when it is a case, else `default`. A null value goes to `default`. A record that has no value at the field fails at the router when the router has a default branch. With `default: filter`, the router filters it. Its line in the run output counts the records of each case, for example `format_router 30 records in 0.2s — multi_choice 10, matching 10, fill_blank 10, default 0`.
- Each action that starts a branch gets the guard `<router>.case == "<case>"` with `on_false: filter`, the router as a dependency, and `<router>.case` in its `context_scope` observe list. The default branch is entered on the case `default`. For an include instance, the actions that start the branch are the actions of the instance that read no other action of it.
- A record that a branch does not take is recorded `filtered` with the reason `sent_elsewhere`. It is not reported as filtered. The guard pre-filter line counts it as sent elsewhere. [`agac dispositions`](../cli/dispositions.md) shows it in the **Sent elsewhere** column, outside **Filtered** and **Total**. A branch that takes no record completes on no records. Its readers run on nothing, and the join still runs.
- With `default: filter`, the router has the guard `<field> IN [<cases>] OR NOT (<field> IS NULL OR <field> >= "")` with `on_false: filter`. The second part lets through a value that is not a string, so that the router fails it. A record with another string value, a null value or no value is filtered at the router, and is counted as filtered there.

## The Join Entry {/* #join-entry */}

| Key | What it does |
|-----|--------------|
| `join` | Names the join. The same name rule as a router applies. |
| `of` | Lists the last action of each branch. An include instance stands for its one output. |

The join is a tool action that depends on every action of `of`. Each record holds the output of the one branch it went through, and the join writes that output under its own name. Thus an action downstream of the join reads `bank.<field>`. The schema of the join holds every field of the schemas of the joined actions, none of them required. A record that a branch sent elsewhere returns at the join through the branch that took it. It is live in every action downstream of the join. A record that a guard filtered in the usual way is not in the join.

A join can name another join, and a router can read the output of a join (`on: <join>.<field>`). A join cannot name an action that runs as versions: name the action that merges the versions. If the `of:` list of a join covers some branches of a router but not all of them, the load logs a warning. The records of the other branches stop at the join.

## What the Load Refuses {/* #route-refusals */}

The load, and so `agac inspect` and `agac run`, refuse:

- A router with no `default:`. Also a case or a default that names no branch, or that names something that is not an action or an include instance.
- A case value that is not a string, is empty, holds a quote, a backslash or a control character, or is `default`.
- An action that starts the branches of two cases. Also an action that starts a branch and has a guard of its own. Put the condition on the next action of the branch.
- An action that reads the branches of two cases short of a join, through a dependency or its `context_scope`.
- A field whose schema type is not `string`, or whose `enum` holds a value that is not a string. The message is: `<field> is not a string field (...). A router matches string values only, so no record could enter a case.`
- When the schema of the field has an `enum`: a case value outside the enum. Under `default: filter`, also an enum value with no case.
- A join that names an action that runs as versions.
- A `- route:` or `- join:` entry in a branch file. The message is: `the branch contains a '- route:' or '- join:' entry. Write routes and joins in the workflow, not in a branch file.`
- An unknown key, and a name that is taken or breaks the name rule.

## In agac inspect {/* #route-inspect */}

`agac inspect` shows the router with its field, its cases and the default, and the join with what it joins:

```
  ✓  format_router  route on route_focus.format: multi_choice → mc_write · matching → m__write · fill_blank → fb_write · default → other_write
  ✓  bank           join of mc_write, m__finalize, fb_write, other_write
```

`agac docs` lists the router and the join, also in a workflow with no include, and in the editor a read of the router's or the join's name resolves to its entry.

## Guards or a Router {/* #guards-or-router */}

Guards with `on_false: filter` on parallel actions also send records down different paths, and a record may pass more than one of them. But a record that one guard filters is not in any action where the branches meet again ([Guards](../execution/guards.md#filtered-records-leave-only-what-is-below-the-filter)), so such branches cannot be joined. Use a router when each record enters exactly one branch and the branches meet again. To run one branch again for the records that failed its check, use a [loop](./loops.md).

## See Also

- [Guards](../execution/guards.md)
- [Branches](./branches.md)
- [agac dispositions](../cli/dispositions.md)
