# Schema Design Guide

## Formats

**Inline** (3 or fewer simple fields, prototyping):

```yaml
schema:
  issue_type: string
  severity: string!          # ! = required
  tags: array[string]
  confidence: number
```

**File** (enums, descriptions, shared, nested objects) — place in `schema/` flat, reference by name:

```yaml
# schema/classify_issue.yml
fields:
  - id: issue_type
    type: string
  - id: severity
    type: string
    enum: ["low", "medium", "high", "critical"]
  - id: tags
    type: array
    items: {type: string}
additionalProperties: false
```

```yaml
schema: classify_issue       # Name only, no path prefix
```

## Types

| Shorthand | JSON Schema | Notes |
|-----------|-------------|-------|
| `string` / `string!` | `{"type": "string"}` | `!` = required |
| `integer` | `{"type": "integer"}` | |
| `number` | `{"type": "number"}` | |
| `boolean` | `{"type": "boolean"}` | |
| `array` / `array[string]` | `{"type": "array"}` | Typed items with bracket syntax |
| `object` | `{"type": "object"}` | |

## Rules

- **Schema = produced fields only.** Forwarded fields go in `passthrough`, not schema.
- **Field names must match LLM output.** Schema says `claims` but prompt says "extract factual claims" = LLM outputs `factual_claims` = validation fails. Align names or add explicit output instructions in prompt.
- **`additionalProperties: false`** rejects any field not in schema. UDF-computed fields must be listed.
- **`type: object` without `properties`** = `additionalProperties: false` = rejects nested fields. Always define properties.
- **Schema files must be flat** in `schema/`. No subdirectories. Names globally unique.
- **`None` defaults fail validation.** Use `""` for string, `[]` for array.

## Required vs Optional

```yaml
# File schema
required: [summary, confidence]    # Must always be present
# additional_notes omitted = optional

# Inline — use ! suffix
schema:
  summary: string!           # Required
  additional_notes: string   # Optional
```

Make optional: fields from guard-filtered upstreams, conditional fields, fields handled with `.get()` defaults.

## Nested Objects

```yaml
fields:
  - id: results
    type: array
    items:
      type: object
      properties:
        id: {type: string}
        title: {type: string}
        score: {type: number}
      required: [id, title]
  - id: metadata
    type: object
    properties:
      total_count: {type: integer}
      query: {type: string}
```

## TypedDict for UDFs

`dict[str, Any]` converts to `additionalProperties: {type: string}` -- forces all values to strings. Use nested TypedDict:

```python
class SearchMetadata(TypedDict, total=False):
    total_count: int
    method: str

class MyOutput(TypedDict, total=False):
    results: list[MatchingItem]
    metadata: SearchMetadata    # Not dict[str, Any]
```

## Version-Expanded Schemas

```yaml
versions:
  param: stage
  range: [1, 3]
schema:
  distractor_${stage}: string    # Expands to distractor_1, distractor_2, distractor_3
```

Verify: `agac render -a workflow | grep -A 10 "schema:"`

## Common Mistakes

| Mistake | Symptom | Fix |
|---------|---------|-----|
| Field name mismatch | `declared fields not found` | Align schema `id:` with LLM output |
| Unlisted UDF field + `additionalProperties: false` | `Additional properties are not allowed` | Add field to schema |
| `dict[str, Any]` in TypedDict | Values become strings | Use nested TypedDict |
| Schema in subdirectory | Schema not found | Place in `schema/` flat |
| Forwarded fields in schema | Duplicate data, wasted tokens | Use `passthrough` |
| `None` default for `type: string` | Validation error | Use `""` |
