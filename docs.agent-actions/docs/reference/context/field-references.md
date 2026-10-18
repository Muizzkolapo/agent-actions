---
title: Field References
sidebar_position: 2
---

# Field References

Field references access data from upstream actions using `{{ action_name.field }}` syntax, where `action_name` is the name of the upstream action: `{{ extract_facts.candidate_facts_list }}`.

## Syntax

### Jinja2 Format (Prompts)

```yaml
prompt: |
  Process these facts: {{ extract_facts.candidate_facts_list }}
  Using context: {{ source.content }}
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

`action_name.field` reads what the action produced: the fields its schema lists, plus the `expect` verdict its expectations attach. A field the action only observes or passes through is not in its namespace, so pre-flight refuses a reference to it there. Read such a field from the action that produced it, such as `source.url`.

## Reserved Action Names

Action names cannot use reserved namespaces. The following names are disallowed:

- `action`
- `context_scope`
- `prompt`
- `schema`
- `seed`
- `source`
- `version`
- `workflow`

`action`, `prompt` and `schema` are reserved words, not namespaces: no record carries them. Write `{{ extract_facts.count }}`, not `{{ action.extract_facts.count }}`. Pre-flight refuses a prompt, guard or `context_scope` entry that reads through one of them, and names the spelling to write.

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
  Analyze this content: {{ source.content }}
  From URL: {{ source.url }}
```

### seed

The `seed` reference accesses static seed data loaded via `context_scope.seed`:

```yaml
defaults:
  context_scope:
    seed:
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
  dependencies: [flatten_clusters]
  prompt: |
    Grouped Facts: {{ flatten_clusters.grouped_facts }}
    Content: {{ source.content }}
```

### Guard with Field Reference

```yaml
- name: canonicalize_facts
  dependencies: [fact_extractor]
  guard:
    condition: "fact_extractor.candidate_facts_list != []"
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
  dependencies: [extract]  # Required
  prompt: |
    Validate: {{ extract.data }}
```

## Best Practices

1. **Use explicit dependencies** - Required for all referenced actions
2. **Use Jinja2 syntax** - `{{ action_name.field }}` for prompts
3. **Use selector syntax** - `action_name.field` for guards and context_scope
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
