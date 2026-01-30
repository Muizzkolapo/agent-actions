---
title: Workflow Dependencies
sidebar_position: 6
---

# Workflow Dependencies

Workflow dependencies enable orchestration across multiple workflows, creating multi-stage pipelines.

## Dependency Types

| Type | Syntax | Description |
|------|--------|-------------|
| Single | `dependencies: action_name` | Single action in current workflow |
| Multiple | `dependencies: [action_a, action_b]` | Merge multiple actions |
| Cross-workflow | `dependencies: [{workflow: name, action: act}]` | Specific action from another workflow |

## Same-Workflow Dependencies

```yaml
actions:
  - name: extract_data
    # No dependencies (first action)

  - name: validate_data
    dependencies: extract_data

  - name: generate_summary
    dependencies: [analyze_sentiment, extract_entities]  # Merge pattern
```

:::info Auto-Inferred Context
Actions referenced in `context_scope` but not in `dependencies` are automatically treated as context dependencies.
:::

## Cross-Workflow Dependencies

```yaml
actions:
  - name: process_upstream_output
    dependencies:
      - workflow: upstream_workflow
        action: final_action
```

### All Outputs from Workflow

```yaml
dependencies:
  - workflow: data_preparation
  # Receives outputs from all terminal actions
```

### Specific Action

```yaml
dependencies:
  - workflow: data_preparation
    action: validated_output
```

## CLI Execution

```bash
# Run upstream workflows first
agac run -a my_workflow --upstream

# Run downstream workflows after
agac run -a my_workflow --downstream

# Full chain execution
agac run -a my_workflow --upstream --downstream
```

| Command | What Executes |
|---------|---------------|
| `agac run -a B` | B only |
| `agac run -a B --upstream` | A → B |
| `agac run -a B --downstream` | B → C |
| `agac run -a B --upstream --downstream` | A → B → C |

## Field References

Reference upstream workflow outputs in prompts:

```yaml
- name: enhance_content
  dependencies:
    - workflow: qanalabs_quiz_gen
      action: format_quiz_text
  prompt: |
    Enhance: {{ format_quiz_text.question }}
```

## See Also

- [run Command](../cli/run) - `--upstream` and `--downstream` flags
- [Field References](../context/field-references) - Referencing upstream outputs
- [Guards](./guards) - Conditional execution
