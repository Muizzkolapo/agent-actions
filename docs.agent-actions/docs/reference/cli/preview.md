---
title: preview Command
description: Show the data that the SQLite storage backend keeps
sidebar_position: 7
---

# preview Command

The `preview` command shows the data that the SQLite storage backend keeps while a workflow runs. Use it to debug, to verify outputs and to see the data that goes between actions.

```bash
agac preview -w <workflow-name> [options]
```

Use `preview` to check quickly which records an action wrote. You do not have to open SQLite files manually.

## Options

| Option | Description |
|--------|-------------|
| `-w, --workflow TEXT` | The name of the workflow configuration file (required) |
| `-a, --action TEXT` | The name of the action to preview. If you do not specify it, the command lists all actions |
| `-n, --limit INT` | The maximum number of records to show (default: 10) |
| `--offset INT` | The number of records to skip (default: 0) |
| `-f, --format` | The output format: `table`, `json` or `raw` (default: table) |
| `--stats` | Show only the storage statistics |

## Examples

### List All Actions

Show the actions that have stored data:

```bash
agac preview -w my_workflow
```

### Preview Action Output

Show the records of a specified action:

```bash
agac preview -w my_workflow -a extract_facts
```

### JSON Output

Get output that a machine can read, for scripts:

```bash
agac preview -w my_workflow -a extract_facts -f json
```

### Pagination

Move through large datasets one page at a time:

```bash
# First 10 records
agac preview -w my_workflow -a extract_facts -n 10

# Next 10 records
agac preview -w my_workflow -a extract_facts -n 10 --offset 10
```

### Storage Statistics

Show the quantity of data that each action stored:

```bash
agac preview -w my_workflow --stats
```

## Output Formats

### Table Format (default)

The table shows one row for each record. The row numbers start from the offset. With `-a`, the columns are the output fields of the action, sorted by name. The table shows a maximum of the first six fields. Without `-a`, the command lists the actions that have stored data.

```
┏━━━┳━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━┓
┃ # ┃ id     ┃ saw_keys                      ┃ saw_score ┃ saw_secret ┃ score ┃
┡━━━╇━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━┩
│ 1 │ keep-1 │ id,saw_source_keys,score,tier │ True      │ False      │ 90    │
└───┴────────┴───────────────────────────────┴───────────┴────────────┴───────┘
```

### JSON Format

The full data of each record, as a JSON array. The data includes the lineage and metadata fields:

```bash
agac preview -w my_workflow -a extract_facts -f json
```

### Raw Format

Output with no format, to send through a pipe to other tools:

```bash
agac preview -w my_workflow -a extract_facts -f raw | jq '.[] | .content'
```

## Use Cases

### Debug Missing Data {/* #debugging-missing-data */}

If a downstream action does not receive the expected data, examine the output of the upstream action:

```bash
# Check what the upstream action actually produced
agac preview -w my_workflow -a upstream_action -n 5 -f json
```

### Verify Field References {/* #verifying-field-references */}

Make sure that fields exist before you refer to them:

```bash
# See the actual content structure
agac preview -w my_workflow -a extract_facts -f json | jq '.[0].content | keys'
```

### Monitor the Progress of a Workflow {/* #monitoring-workflow-progress */}

During a workflow that runs for a long time, check which records the workflow processed:

```bash
agac preview -w my_workflow --stats
```

## See Also

- **[inspect Command](./inspect)**: Analyze the structure and the dependencies of a workflow
- **[run Command](./run)**: Run workflows
- **[batch Commands](./batch)**: Manage batch processing operations
