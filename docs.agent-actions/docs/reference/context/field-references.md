---
title: Field References
sidebar_position: 2
---

# Field References

Field references access data from upstream actions using `{{ action.field }}` syntax.

## Syntax

### Jinja2 Format (Prompts)

```yaml
prompt: |
  Process these facts: {{ extract_facts.candidate_facts_list }}
  Using context: {{ source.page_content }}
```

### Selector Format (Guards and Context Scope)

```yaml
guard:
  condition: "extract_facts.count > 0"
context_scope:
  observe:
    - extract_facts.candidate_facts_list
```

## Reference Structure

A field reference consists of:

```
action_name.field_path
```

| Component | Description | Example |
|-----------|-------------|---------|
| `action_name` | Name of the upstream action | `extract_facts` |
| `field_path` | Path to the field (dot-separated for nested) | `response.data.count` |

## Reserved Action Names

Action names cannot use reserved namespaces. The following names are disallowed:

- `action`
- `context_scope`
- `versions`
- `prompt`
- `schema`
- `seed`
- `source`
- `workflow`

### Nested Field Access

Access deeply nested fields with dot notation:

```yaml
# Upstream output:
# {
#   "response": {
#     "data": {
#       "items": [...]
#     }
#   }
# }

prompt: |
  Items: {{ upstream_action.response.data.items }}
```

## Special Sources

### source

The `source` reference accesses the input data for the current record:

```yaml
prompt: |
  Analyze this content: {{ source.page_content }}
  From URL: {{ source.url }}
```

### seed

The `seed` reference accesses static seed data loaded via `context_scope.seed_path`:

```yaml
defaults:
  context_scope:
    seed_path:
      exam_syllabus: $file:syllabus.json

actions:
  - name: extract_facts
    prompt: |
      Extract facts for {{ seed.exam_syllabus.exam_name }}
```

## Examples

### Prompt with Field References

```yaml
- name: generate_summary
  dependencies: flatten_clusters
  prompt: |
    Grouped Facts: {{ flatten_clusters.grouped_facts }}
    Page Content: {{ source.page_content }}
```

### Guard with Field Reference

```yaml
- name: canonicalize_facts
  dependencies: fact_extractor
  guard:
    condition: "candidate_facts_list != []"
    on_false: filter
```

### Jinja2 Loops

```yaml
prompt: |
  {% for ref in source.referenced_in %}
  - {{ ref.section_name }}: {{ ref.objective }}
  {% endfor %}
```

## Dependencies

Explicit `dependencies` are required for correct execution ordering:

```yaml
- name: validate
  dependencies: extract  # Required
  prompt: |
    Validate: {{ extract.data }}
```

## Best Practices

1. **Use explicit dependencies** - Required for all referenced actions
2. **Use Jinja2 syntax** - `{{ action.field }}` for prompts
3. **Use selector syntax** - `action.field` for guards and context_scope
4. **Use schema command** - Run `agac schema -a workflow` to analyze field dependencies

## Version Field Patterns

Version actions prefix field names to avoid collisions. Use wildcard syntax to reference all iterations:

```yaml
- name: analyze_strategies
  dependencies: [extract_strategies]
  context_scope:
    observe:
      - extract_strategies.*  # Matches extract_strategies_1_*, extract_strategies_2_*, etc.
```

See [Version Actions](../execution/versions) for complete documentation.

## See Also

- [Version Actions](../execution/versions) - Version configuration and field prefix patterns
- [Context Scope](./context-scope) - Field visibility and flow control
- [Workflow Dependencies](../execution/workflow-dependencies) - Dependency patterns
