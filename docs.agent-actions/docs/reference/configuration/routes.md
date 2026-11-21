---
title: Routes and Joins
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
| `cases` | Maps each value of the field to its branch: an include instance, or a list of the actions that start the branch. A case value is a string; quote a value that YAML reads as another type (`"yes"`, `"1"`). |
| `default` | Required. The branch of a record whose value has no case, written like a case. `default: filter` filters such a record at the router instead. |

A record enters one branch only. The other branches do not see it.

### What the load makes of it {/* #route-expansion */}

- The router is a tool action named as the entry. It reads the field once and writes `case`: the value when it is a case, else `default`. Its line in the run output counts the records of each case, for example `format_router 30 records in 0.2s — multi_choice 10, matching 10, fill_blank 10, default 0`.
- Each action that starts a branch gets the guard `<router>.case == "<case>"` with `on_false: filter`, the router as a dependency, and `<router>.case` in its `context_scope` observe list. The default branch is entered on the case `default`. For an include instance, the actions that start the branch are the actions of the instance that read no other action of it.
- A record that a branch does not take is recorded `filtered` with the reason `sent_elsewhere`. It is not reported as filtered: the guard pre-filter line counts it as sent elsewhere, and [`agac dispositions`](../cli/dispositions.md) shows it in the **Sent elsewhere** column, outside **Filtered** and **Total**. A branch that takes no record completes on no records; its readers run on nothing, and the join still runs.
- With `default: filter`, the router has the guard `<field> IN [<cases>]` with `on_false: filter`. A record with any other value, or none, is filtered at the router, and is counted as filtered there.

## The Join Entry {/* #join-entry */}

| Key | What it does |
|-----|--------------|
| `join` | Names the join. The same name rule as a router applies. |
| `of` | Lists the last action of each branch. An include instance stands for its one output. |

The join is a tool action that depends on every action of `of`. Each record holds the output of the one branch it went through, and the join writes that output under its own name, so an action below reads `bank.<field>`. The schema of the join holds every field of the schemas of the joined actions, none of them required. A record sent elsewhere by a branch comes back at the join through the branch that took it, and is live in every action below the join. A record that a guard filtered in the usual way stays out, also at the join.

## What the Load Refuses {/* #route-refusals */}

The load, and so `agac inspect` and `agac run`, refuse:

- a router with no `default:`, or a case or default that names no branch, or names something that is no action or include instance;
- a case value that is not a string, is empty, holds a quote, a backslash or a control character, or is `default`;
- an action that starts the branches of two cases, or that starts a branch and has a guard of its own (put the condition on the next action of the branch);
- an action that reads the branches of two cases, through a dependency or its `context_scope`, short of a join;
- when the schema of the field has an `enum`: a case value outside the enum, and, under `default: filter`, an enum value with no case;
- an unknown key, and a name that is taken or breaks the name rule.

## In agac inspect {/* #route-inspect */}

`agac inspect` shows the router with its field, its cases and the default, and the join with what it joins:

```
  ✓  format_router  route on route_focus.format: multi_choice → mc_write · matching → m__write · fill_blank → fb_write · default → other_write
  ✓  bank           join of mc_write, m__finalize, fb_write, other_write
```

`agac docs` lists the router and the join, also in a workflow with no include, and in the editor a read of the router's or the join's name resolves to its entry.

## Guards or a Router {/* #guards-or-router */}

Guards with `on_false: filter` on parallel actions also send records down different paths, and a record may pass more than one of them. But a record that one guard filters stays out wherever the branches meet again ([Guards](../execution/guards.md#filtered-records-leave-only-what-is-below-the-filter)), so such branches cannot be joined. Use a router when each record enters exactly one branch and the branches meet again. To run one branch again for the records that failed its check, use a [loop](./loops.md).
