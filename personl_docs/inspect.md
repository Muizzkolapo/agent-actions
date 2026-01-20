# Inspect Command

The `agac inspect` command provides tools for analyzing workflow structure, data flow, and potential issues before runtime.

## Overview

```bash
agac inspect [SUBCOMMAND] [OPTIONS]
```

Available subcommands:
- `field-flow` - Trace and visualize data flow through a workflow
- `conflicts` - Detect field name conflicts and ambiguous references

---

## Field Flow Analysis

Analyze how data flows between actions in your workflow. This command validates all field references and shows clear errors with suggestions for typos.

### Basic Usage

```bash
# Analyze entire workflow
agac inspect field-flow -a my_workflow

# Analyze a specific action
agac inspect field-flow -a my_workflow.extract_facts

# Show detailed field lineages
agac inspect field-flow -a my_workflow --verbose

# Output as JSON
agac inspect field-flow -a my_workflow --json
```

### Options

| Option | Description |
|--------|-------------|
| `-a, --agent` | Workflow name, optionally with action (e.g., `my_workflow.action`) |
| `-u, --user-code` | Path to user code directory containing UDFs |
| `--json` | Output as JSON for programmatic use |
| `-v, --verbose` | Show detailed field lineage information |
| `--errors-only` | Show only validation errors |
| `--field` | Trace a specific field (e.g., `extractor.summary`) |

### Examples

#### Whole Workflow Analysis

```bash
$ agac inspect field-flow -a document_processor

Field Flow Analysis: document_processor

All field references are valid

╭─────────────────────────────────────────────────────────────╮
│ Workflow Data Flow                                          │
├─────────────────────────────────────────────────────────────┤
│ Flow Visualization                                          │
│ ├── extractor (llm)                                         │
│ │   ├── uses:                                               │
│ │   │   └── source.document_text                            │
│ │   └── produces:                                           │
│ │       ├── title                                           │
│ │       └── summary                                         │
│ └── formatter (llm)                                         │
│     ├── uses:                                               │
│     │   └── extractor.summary                               │
│     └── produces:                                           │
│         └── formatted_output                                │
╰─────────────────────────────────────────────────────────────╯
```

#### Single Action Detail

```bash
$ agac inspect field-flow -a document_processor.extractor

╭───────────────────────────────────────────────────────────────╮
│ Action: extractor                                             │
├───────────────────────────────────────────────────────────────┤
│ extractor (llm)                                               │
│ ├── depends_on:                                               │
│ │   └── source                                                │
│ ├── uses (from templates):                                    │
│ │   └── source                                                │
│ │       └── document_text (task_instructions)                 │
│ └── produces:                                                 │
│     ├── title                                                 │
│     └── summary                                               │
╰───────────────────────────────────────────────────────────────╯
```

#### Trace a Specific Field

```bash
$ agac inspect field-flow -a my_workflow --field extractor.summary

╭──────────────────────────────────────────────────────────────╮
│ Field Lineage: extractor.summary                             │
├──────────────────────────────────────────────────────────────┤
│ Field Lineage: extractor.summary                             │
│ ├── Producer: extractor                                      │
│ │   └── Type: schema                                         │
│ └── Consumers:                                               │
│     └── formatter                                            │
│         └── Location: task_instructions                      │
╰──────────────────────────────────────────────────────────────╯
```

#### Validation Errors

When field references are invalid, you'll see detailed error messages:

```bash
$ agac inspect field-flow -a broken_workflow

Field Flow Analysis: broken_workflow

2 error(s), 0 warning(s) found

Error 1:
  Action: formatter
  Reference: {{ extractor.sumary }}
  Location: task_instructions
  Problem: Field 'sumary' not found in agent 'extractor'
  Available: summary, title
  Hint: Did you mean 'summary'?
```

---

## Conflict Detection

Detect field name conflicts that can cause ambiguous references or unexpected behavior.

### Basic Usage

```bash
# Analyze entire workflow
agac inspect conflicts -a my_workflow

# Output as JSON
agac inspect conflicts -a my_workflow --json

# Filter to specific action
agac inspect conflicts -a my_workflow --filter-action extractor

# Include INFO-level conflicts
agac inspect conflicts -a my_workflow --include-info
```

### Options

| Option | Description |
|--------|-------------|
| `-a, --agent` | Agent/workflow configuration name |
| `-u, --user-code` | Path to user code directory containing UDFs |
| `--json` | Output as JSON for programmatic use |
| `--filter-action` | Filter conflicts to those affecting a specific action |
| `--include-info` | Include INFO-level conflicts (drop-recreate patterns) |

### Conflict Types

#### Shadowing (WARNING)

Multiple actions produce the same field name. This can cause confusion about which value is used.

```bash
$ agac inspect conflicts -a multi_extractor_workflow

1 warning(s)

Shadowing Conflicts
┏━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Field    ┃ Severity ┃ Details                                   ┃ Resolution                        ┃
┡━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ summary  │ WARN     │ Field 'summary' is produced by multiple   │ Use qualified reference:          │
│          │          │ actions: extractor1, extractor2           │ {{ action.extractor1.summary }}   │
│          │          │ Producers: extractor1, extractor2         │ or {{ action.extractor2.summary }}│
└──────────┴──────────┴───────────────────────────────────────────┴───────────────────────────────────┘

Summary:
  Actions analyzed: 3
  Unique fields: 5
  Shadowed fields: 1
```

#### Ambiguous Reference (ERROR)

An unqualified reference points to a field that exists in multiple sources. This is an error because the system cannot determine which value to use.

```bash
$ agac inspect conflicts -a ambiguous_workflow

1 error(s)

Ambiguous References
┏━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Field    ┃ Severity ┃ Details                                   ┃ Resolution                        ┃
┡━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ title    │ ERROR    │ Ambiguous reference '{{ source.title }}'  │ Use qualified reference:          │
│          │          │ in action 'consumer' could match multiple │ {{ action.extractor1.title }}     │
│          │          │ sources                                   │ or {{ action.extractor2.title }}  │
│          │          │ Affected: consumer:task_instructions      │                                   │
└──────────┴──────────┴───────────────────────────────────────────┴───────────────────────────────────┘
```

#### Reserved Name (WARNING)

A field uses a reserved namespace name (like `source`, `seed`, `loop`, `workflow`, `action`), which may cause confusion with system namespaces.

```bash
$ agac inspect conflicts -a reserved_name_workflow

1 warning(s)

Reserved Name Usage
┏━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Field    ┃ Severity ┃ Details                                   ┃ Resolution                        ┃
┡━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ source   │ WARN     │ Field 'source' uses a reserved name that  │ Consider renaming the field to    │
│          │          │ may conflict with system namespaces       │ avoid confusion                   │
└──────────┴──────────┴───────────────────────────────────────────┴───────────────────────────────────┘
```

#### Drop-Recreate (INFO)

A field was dropped by one action and recreated by another. This pattern is often intentional but worth noting.

```bash
$ agac inspect conflicts -a transform_workflow --include-info

1 info

Drop-Recreate Patterns
┏━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Field        ┃ Severity ┃ Details                                ┃ Resolution                        ┃
┡━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ raw_content  │ INFO     │ Field 'raw_content' was dropped by     │ This may be intentional. Verify   │
│              │          │ 'cleaner' and recreated by 'enricher'  │ the workflow logic.               │
└──────────────┴──────────┴────────────────────────────────────────┴───────────────────────────────────┘
```

### JSON Output

Both commands support JSON output for programmatic use:

```bash
$ agac inspect conflicts -a my_workflow --json
```

```json
{
  "workflow_name": "my_workflow",
  "has_conflicts": true,
  "error_count": 0,
  "warning_count": 1,
  "conflicts": [
    {
      "type": "shadowing",
      "severity": "warning",
      "field_name": "summary",
      "message": "Field 'summary' is produced by multiple actions: extractor1, extractor2",
      "resolution": "Use qualified reference: {{ action.extractor1.summary }} or {{ action.extractor2.summary }}",
      "producers": [
        {"action": "extractor1", "field_source": "schema"},
        {"action": "extractor2", "field_source": "schema"}
      ],
      "affected_references": []
    }
  ],
  "summary": {
    "actions_analyzed": 3,
    "unique_fields": 5,
    "shadowed_fields": 1
  }
}
```

---

## Best Practices

1. **Run before deployment**: Use `agac inspect field-flow` to validate all field references before deploying a workflow.

2. **Check for conflicts early**: Run `agac inspect conflicts` when designing workflows with multiple actions that produce similar data.

3. **Use qualified references**: When multiple actions produce the same field name, use qualified references like `{{ action.extractor1.field }}` instead of `{{ field }}`.

4. **Avoid reserved names**: Don't name output fields `source`, `seed`, `loop`, `workflow`, or `action` to prevent confusion with system namespaces.

5. **Review drop-recreate patterns**: Use `--include-info` periodically to review intentional drop-recreate patterns and ensure they're still correct.
