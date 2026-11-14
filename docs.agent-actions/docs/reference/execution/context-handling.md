---
title: Context Handling
sidebar_position: 3
---

# Context Handling

Agent Actions makes the prompt context in the same way in batch mode and in online mode. **The template pattern is `{{ source.field }}` in the two modes.** The rest of this page gives the reason.

## Mode Differences

For your templates, the two modes have no differences. In batch mode and in online mode, each record starts with an empty `base` dict. The framework then merges in only the data that `context_scope` admits, under the namespaces that it admits. For the same `context_scope` configuration, the final Jinja context is identical in the two modes.

| Property                       | Online | Batch |
|--------------------------------|--------|-------|
| The start `base` for templates  | `{}`   | `{}`  |
| The namespace of the source data | `source` namespace | `source` namespace |
| The namespace of the seed data   | `seed` namespace   | `seed` namespace   |
| The namespace of the upstream action output | `{action_name}` namespace | `{action_name}` namespace |
| The correct template pattern       | `{{ source.field }}` | `{{ source.field }}` |
| A bare `{{ field }}` works       | No     | No    |

### Online Mode

```json
{
  "source": {
    "content": "Document text...",
    "url": "https://example.com"
  },
  "seed": { "exam_syllabus": {...} }
}
```

```jinja2
Analyze: {{ source.content }}
```

### Batch Mode

```json
{
  "source": {
    "content": "Document text...",
    "url": "https://example.com"
  },
  "seed": { "exam_syllabus": {...} }
}
```

```jinja2
Analyze: {{ source.content }}
```

**Use `{{ source.field }}` in batch prompts and in online prompts.** Before the framework renders a prompt, it puts the input of each record under the `source` namespace. Thus `{{ source.field }}` gives the value of each record identically in the two modes.

**Do not** use a bare `{{ field }}`. Before the framework renders the template, `base` is empty. Thus `field` is not defined, and the template render fails (Jinja `StrictUndefined`). This occurs in the two modes.

:::warning[CAUTION]
Do not use unwrapped variables, for example `{{ content }}` in place of `{{ source.content }}`. The two modes do not accept them. If a prompt contains `{{ passage }}`, write `{{ source.passage }}` in its place.
:::

## Mode-Agnostic Templates

A template does not need `{% if source is defined %}` conditionals or other code that finds the mode. By design, a template works in the two modes:

```jinja2
Content: {{ source.content }}
```

This template renders in the same way when the `run_mode` of the action is `online` and when it is `batch`.

## Context Variables

| Variable        | Description                  | Available In |
|-----------------|------------------------------|--------------|
| `source`        | The input record (always under this namespace) | The two modes |
| `seed`          | Static seed data             | The two modes   |
| `{action_name}` | The output of an upstream action (also a namespace) | The two modes |

Each item in your `context_scope.observe` list gets to the template. It is under the namespace prefix that the list declares for it. The framework puts no data at the root level.

## Context Scope

Use `context_scope` to control which data an action can see:

```yaml
actions:
  - name: my_action
    dependencies: [prev_action]
    context_scope:
      observe:
        - source.content
        - seed.exam_syllabus
        - prev_action.result
      drop:
        - source.sensitive_field
```

The same configuration works identically in the two modes.

## Best Practices

1. **Always put a namespace on the fields in a template** — `{{ source.field }}`, `{{ seed.field }}`, `{{ upstream_action.field }}`. Never use a bare `{{ field }}`.
2. **Select a mode for cost or latency, not for templates** — `run_mode: batch` changes when the LLM calls occur. It does not change the context that the prompt sees.
3. **Use seed data for static content** — seed data works identically in the two modes.
4. **Examine the rendered prompts** — `agac traces -w <workflow> -a <action>` shows the exact text that the LLM received.

## See Also

- [Run Modes](./run-modes) — Batch execution and online execution (what changes when you change the mode)
- [Context Scope](../context/context-scope) — Configure the fields that an action can see
