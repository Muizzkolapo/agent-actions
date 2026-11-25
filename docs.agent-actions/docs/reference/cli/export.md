---
title: export Command
description: Write the outputs that a workflow declares to their database tables, with no model call
sidebar_position: 3
---

# export Command

The `export` command writes the `outputs:` of a workflow to their database tables. It reads the records that the last run stored. It calls no model, so you can run it again and again.

```bash
agac export -w <workflow-name> [options]
```

`agac run` and `agac retry` write the same tables when they finish with each action complete. Use `export` when that write failed, or when you changed a table and want it written again. See [Databases](../data-io/databases.md) for the `connections:` and `outputs:` keys.

## Options

| Option | Description |
|--------|-------------|
| `-w, --workflow NAME` | The workflow name (required). `-a` names the same option. |
| `-A, --action NAME` | Write only the output of this action. The action must have an output. If no output names it, the command stops and lists the actions that have outputs |

## Examples

### Write each table again after a failed write

When the write at the end of a run fails, the run prints this message:

```
Every action finished, but writing the outputs failed. The results are stored: write them again with agac export -w ticket_triage
```

Correct the cause, for example a table with a column that does not accept null. Then write the tables:

```bash
agac export -w ticket_triage
```

The command prints one line for each table:

```
Wrote 120 rows to ticket_classification
Wrote 14 rows to ticket_escalations
```

If two connections each have a table with the same name, the line names the connection too: `Wrote 120 rows to results on warehouse`.

### Write the table of one action

```bash
agac export -w ticket_triage -A classify_ticket
```

## When the command stops

The command checks each output before it writes a table. These conditions stop the command, and the error names the cause:

| Cause | What to do |
|-------|------------|
| The workflow declares no `outputs:` | Add an `outputs:` block to the workflow, or do not use `export` |
| An output names an action that the workflow does not run | Correct the action name |
| An output names a connection that `agent_actions.yml` does not declare | Add the connection to `connections:`, or correct the name |
| The driver of a connection is not installed | Install the extra that the error names, for example `pip install 'agent-actions[postgres]'` |
| A `table`, `key` or `carry` name is not a plain name | Use letters, digits and underscores, with a dot between a schema and a table |
| Two outputs write the same table on the same connection | Give each output its own table |
| Two different records share the key of a `merge` or `append` output | Set `key` to columns that tell the records apart, or use `mode: replace`. See [Modes](../data-io/databases.md#modes) |
| `agac run` or `agac retry` of the same workflow is in progress | Wait for the run to finish. A table written during a run would hold only a part of the records |

If one table fails, the tables that the command wrote before it stay written. Correct the cause and run the command again. A `merge` or a `replace` that you write two times gives the same table as one write.
