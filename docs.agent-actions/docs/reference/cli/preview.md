---
title: preview Command
description: Preview data stored in the SQLite storage backend
sidebar_position: 7
---

# preview Command

The `preview` command lets you inspect data stored in the SQLite storage backend during workflow execution. This is useful for debugging, verifying outputs, and understanding what data flows between actions.

```bash
agac preview -w <workflow-name> [options]
```

:::tip Quick Inspection
Use `preview` to quickly check what records were written by an action without manually opening SQLite files.
:::

## Options

| Option | Description |
|--------|-------------|
| `-w, --workflow TEXT` | Workflow configuration file name (required) |
| `-a, --action TEXT` | Action name to preview (lists all actions if not specified) |
| `-n, --limit INT` | Maximum number of records to show (default: 10) |
| `--offset INT` | Number of records to skip (default: 0) |
| `-f, --format` | Output format: `table`, `json`, or `raw` (default: table) |
| `--stats` | Show storage statistics only |

## Examples

### List All Actions

See which actions have stored data:

```bash
agac preview -w my_workflow
```

### Preview Action Output

View records from a specific action:

```bash
agac preview -w my_workflow -a extract_facts
```

### JSON Output

Get machine-readable output for scripting:

```bash
agac preview -w my_workflow -a extract_facts -f json
```

### Pagination

Browse through large datasets:

```bash
# First 10 records
agac preview -w my_workflow -a extract_facts -n 10

# Next 10 records
agac preview -w my_workflow -a extract_facts -n 10 --offset 10
```

### Storage Statistics

Check how much data each action has stored:

```bash
agac preview -w my_workflow --stats
```

## Output Formats

### Table Format (default)

Displays records in a formatted table with key fields:

```
┏━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ source_guid ┃ node_id            ┃ content                                  ┃
┡━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ abc123      │ extract_facts_def4 │ {"facts": ["fact1", "fact2"]}           │
└─────────────┴────────────────────┴──────────────────────────────────────────┘
```

### JSON Format

Full record data as JSON array:

```bash
agac preview -w my_workflow -a extract_facts -f json
```

### Raw Format

Unformatted output for piping to other tools:

```bash
agac preview -w my_workflow -a extract_facts -f raw | jq '.[] | .content'
```

## Use Cases

### Debugging Missing Data

If a downstream action isn't receiving expected data:

```bash
# Check what the upstream action actually produced
agac preview -w my_workflow -a upstream_action -n 5 -f json
```

### Verifying Field References

Confirm that fields exist before referencing them:

```bash
# See the actual content structure
agac preview -w my_workflow -a extract_facts -f json | jq '.[0].content | keys'
```

### Monitoring Workflow Progress

During long-running workflows, check what's been processed:

```bash
agac preview -w my_workflow --stats
```

## See Also

- **[inspect Command](./inspect)** - Analyze workflow structure and dependencies
- **[run Command](./run)** - Execute agentic workflows
- **[batch Commands](./batch)** - Manage batch processing operations
