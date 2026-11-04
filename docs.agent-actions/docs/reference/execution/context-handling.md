---
title: Context Handling
sidebar_position: 3
---

# Context Handling

Agent Actions builds prompt context the same way in both batch and online modes. **The template pattern is `{{ source.field }}` in both modes**, and the rest of this page explains why.

## Mode Differences

There are none, as far as your templates are concerned. Both batch and online start each record with an empty `base` dict and merge in only what `context_scope` admits — under the namespaces it admits them. The final Jinja context is identical in both modes for the same `context_scope` configuration.

| Property                       | Online | Batch |
|--------------------------------|--------|-------|
| Starting `base` for templates  | `{}`   | `{}`  |
| Source data injected under     | `source` namespace | `source` namespace |
| Seed data injected under       | `seed` namespace   | `seed` namespace   |
| Upstream action output under   | `{action_name}` namespace | `{action_name}` namespace |
| Correct template pattern       | `{{ source.field }}` | `{{ source.field }}` |
| Bare `{{ field }}` works       | ❌     | ❌    |

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

**Use `{{ source.field }}` in both batch and online prompts.** The framework injects each record's input under the `source` namespace before rendering, so `{{ source.field }}` resolves to the per-record value identically in both modes.

**Do not** use bare `{{ field }}`. `base` is empty before rendering, so `field` is undefined and rendering the template fails (Jinja `StrictUndefined`) — in either mode.

:::warning Common pitfall
Neither mode accepts unwrapped variables such as `{{ content }}` in place of `{{ source.content }}`. If a prompt reads `{{ passage }}`, write `{{ source.passage }}` instead.
:::

## Mode-Agnostic Templates

Templates need no `{% if source is defined %}` conditionals or other mode-detection scaffolding. They are mode-agnostic by construction:

```jinja2
Content: {{ source.content }}
```

This renders the same way whether the action's `run_mode` is `online` or `batch`.

## Context Variables

| Variable        | Description                  | Available In |
|-----------------|------------------------------|--------------|
| `source`        | Input record (always wrapped under this namespace) | Both modes |
| `seed`          | Static seed data             | Both modes   |
| `{action_name}` | Previous action output (also a namespace) | Both modes |

Whatever appears in your `context_scope.observe` list is what reaches the template — under the namespace prefix it was declared with. Nothing is injected at the root level.

## Context Scope

Control data visibility with `context_scope`:

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

The same configuration works identically in both modes.

## Best Practices

1. **Always namespace fields in templates** — `{{ source.field }}`, `{{ seed.field }}`, `{{ upstream_action.field }}`. Never bare `{{ field }}`.
2. **Pick a mode for cost/latency reasons, not for templating reasons** — `run_mode: batch` changes when LLM calls happen, not what context the prompt sees.
3. **Use seed data for static content** — works identically in both modes.
4. **Inspect rendered prompts** — `agac traces -w <workflow> -a <action>` shows the exact text the LLM received.

## See Also

- [Run Modes](./run-modes) — Batch vs online execution (what changes when you flip the mode)
- [Context Scope](../context/context-scope) — Field visibility configuration
