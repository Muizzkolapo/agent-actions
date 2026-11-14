---
title: Field References
sidebar_position: 2
---

# Field References

A field reference gets data from an upstream action with the `{{ action_name.field }}` syntax. `action_name` is the name of the upstream action. For example: `{{ extract_facts.candidate_facts_list }}`.

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

A field reference has this structure:

```
action_name.field_path
```

| Component | Description | Example |
|-----------|-------------|---------|
| `action_name` | The name of the upstream action | `extract_facts` |
| `field_path` | The path to the field (a dot separates each level of a nested field) | `response.data.count` |

`action_name.field` reads the output of the action. The output is the fields that its schema lists, plus the `expect` verdict that its expectations attach. A field that the action only observes or passes through is not in its namespace. Thus pre-flight refuses a reference to that field in that namespace. Read such a field from the action that produced it, for example `source.url`.

## Reserved Action Names

An action name cannot be a reserved namespace. These names are not permitted:

- `action`
- `context_scope`
- `prompt`
- `schema`
- `seed`
- `source`
- `version`
- `workflow`

`action`, `prompt` and `schema` are reserved words, not namespaces. No record carries them. Write `{{ extract_facts.count }}`, not `{{ action.extract_facts.count }}`. Pre-flight refuses a prompt, a guard or a `context_scope` entry that reads through one of these words. Pre-flight also names the correct spelling.

### Nested Field Access

Use dot notation to get deeply nested fields:

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

The `source` reference gets the input data of the current record:

```yaml
prompt: |
  Analyze this content: {{ source.content }}
  From URL: {{ source.url }}
```

### seed

The `seed` reference gets the static seed data that `context_scope.seed` loads:

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

An action reads only the actions that are upstream of it through its `dependencies`. List each action that it reads, or an action downstream of that action:

```yaml
- name: validate
  dependencies: [extract]  # Required: `extract` is read below
  prompt: |
    Validate: {{ extract.data }}
```

## Best Practices

1. **Use explicit dependencies** - Each action that a reference names must be upstream of the action through its `dependencies`.
2. **Use Jinja2 syntax** - Use `{{ action_name.field }}` in prompts.
3. **Use selector syntax** - Use `action_name.field` in guards and context_scope.
4. **Use the schema command** - Run `agac schema -a <workflow>` to see the fields that each action takes and produces.

## Version Field Patterns

Each iteration of a version action keeps its output in a separate namespace (`extract_strategies_1`, `extract_strategies_2`). A consumer declares `version_consumption` and uses the wildcard syntax to refer to all iterations:

```yaml
- name: analyze_strategies
  dependencies: [extract_strategies]
  version_consumption:
    source: extract_strategies
    pattern: merge
  context_scope:
    observe:
      - extract_strategies.*  # Matches the namespaces extract_strategies_1, extract_strategies_2, ...
```

See [Version Actions](../execution/versions) for the complete documentation.

## See Also

- [Version Actions](../execution/versions) - Version configuration and consumption patterns
- [Context Scope](./context-scope) - Field visibility and flow control
