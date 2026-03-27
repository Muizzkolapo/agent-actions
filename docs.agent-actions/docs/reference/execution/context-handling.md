---
title: Context Handling
sidebar_position: 3
---

# Context Handling

Agent Actions builds prompt context differently depending on execution mode.

## Mode Differences

| Mode | Context Structure |
|------|-------------------|
| **Online** | Input data under `source` namespace |
| **Batch** | Input data at root level |

### Online Mode

```json
{
  "source": {
    "page_content": "Document text...",
    "url": "https://example.com"
  },
  "seed": { "exam_syllabus": {...} }
}
```

```jinja2
Analyze: {{ source.page_content }}
```

### Batch Mode

```json
{
  "page_content": "Document text...",
  "url": "https://example.com",
  "seed": { "exam_syllabus": {...} }
}
```

```jinja2
Analyze: {{ page_content }}
```

:::warning
The same template can fail in different modes. `{{ source.field }}` works in online but fails in batch.
:::

## Mode-Agnostic Templates

```jinja2
{% if source is defined %}
  Content: {{ source.page_content }}
{% else %}
  Content: {{ page_content }}
{% endif %}
```

## Context Variables

| Variable | Description | Available In |
|----------|-------------|--------------|
| `source` | Input record (wrapped) | Online only |
| `seed` | Static seed data | Both modes |
| `{action_name}` | Previous action output | Both modes |
| Root fields | Input record fields | Batch only |

## Context Scope

Control data visibility with `context_scope`:

```yaml
actions:
  - name: my_action
    context_scope:
      observe:
        - seed.exam_syllabus
        - prev_action.result
      drop:
        - source.sensitive_field
```

## Best Practices

1. **Choose one mode per workflow** - Don't switch modes mid-workflow
2. **Match template to mode** - Use `source.*` for online, root fields for batch
3. **Use seed data for static content** - Works identically in both modes
4. **Analyze schemas** - Run `agac schema -a my_workflow` to check field dependencies

## See Also

- [Run Modes](./run-modes) - Batch vs online execution
- [Context Scope](../context/context-scope) - Field visibility configuration
