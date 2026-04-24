# Schema Design Guide

How to design output schemas that work correctly with LLMs, UDFs, and downstream actions.

## Schema Formats

### Inline schema (quick, small actions)

```yaml
- name: classify_issue
  schema:
    issue_type: string
    severity: string!              # ! marks required
    tags: array[string]
    confidence: number
```

### File schema (reusable, complex structures)

Place in `schema/classify_issue.yml`:

```yaml
fields:
  - id: issue_type
    type: string
    description: "Category of the issue"
  - id: severity
    type: string
    enum: ["low", "medium", "high", "critical"]
  - id: tags
    type: array
    items: {type: string}
  - id: confidence
    type: number
    description: "0.0 to 1.0 confidence score"
additionalProperties: false
```

Reference by name only (no path prefix):

```yaml
- name: classify_issue
  schema: classify_issue           # Loads schema/classify_issue.yml
```

Schema files must be flat — directly in `schema/`, not in subdirectories. Names are globally unique.

### When to use which

| Situation | Use |
|-----------|-----|
| 3 or fewer simple fields | Inline |
| Enum constraints or descriptions needed | File |
| Schema shared across actions | File |
| Nested objects or arrays of objects | File |
| Rapid prototyping | Inline → convert to file when stable |

## Type Reference

| YAML shorthand | JSON Schema | Python | Notes |
|---------------|-------------|--------|-------|
| `string` | `{"type": "string"}` | `str` | |
| `integer` | `{"type": "integer"}` | `int` | |
| `number` | `{"type": "number"}` | `float` | |
| `boolean` | `{"type": "boolean"}` | `bool` | |
| `array` | `{"type": "array"}` | `list` | Untyped items |
| `array[string]` | `{"type": "array", "items": {"type": "string"}}` | `list[str]` | Typed items |
| `object` | `{"type": "object"}` | `dict` | |

Append `!` to mark required: `severity: string!`

## Schema Only Contains Computed Fields

The schema defines what the LLM or UDF **produces** — not what it receives. Forwarded fields belong in `passthrough`, not in the schema.

```yaml
# CORRECT — only LLM-produced fields
- name: generate_summary
  schema:
    summary: string
    key_points: array[string]
  context_scope:
    observe: [source.*]
    passthrough: [source.id, source.url]      # Forwarded, not in schema

# WRONG — mixing produced and forwarded fields
- name: generate_summary
  schema:
    summary: string
    key_points: array[string]
    id: string                    # This is forwarded, not produced!
    url: string                   # Same — should be in passthrough
```

## Field Names Must Match LLM Output

The schema field name must match what the LLM naturally produces. If the schema says `claims` but the prompt says "extract factual claims", the LLM might output `factual_claims` instead.

```yaml
# Schema says:
fields:
  - id: claims

# But prompt says:
# "Extract all factual claims..."
# LLM outputs: {"factual_claims": [...]}
# → Schema validation fails: missing "claims"
```

**Fix:** Align the schema field name with how the prompt describes the output, or add an explicit output section to the prompt:

```markdown
Return JSON with these exact field names:
- "claims": array of factual claims
```

## Required vs Optional Fields

Use `required` for fields that must always be present. Omit it for fields that may be absent (e.g., when a guard filters some records upstream).

```yaml
# File schema
fields:
  - id: summary
    type: string
  - id: confidence
    type: number
  - id: additional_notes
    type: string
required:
  - summary
  - confidence
# additional_notes is optional — absent won't fail validation
```

```yaml
# Inline schema — use ! suffix
schema:
  summary: string!              # Required
  confidence: number!           # Required
  additional_notes: string      # Optional
```

**When to use required:**
- Fields that downstream actions depend on via `observe`
- Fields used in guard conditions
- Core output fields that the action must always produce

**When to leave optional:**
- Fields that only appear in certain conditions
- Fields downstream actions handle with `.get()` defaults
- Fields produced by guard-filtered upstream actions

## additionalProperties

Controls whether the LLM can return fields not in the schema.

```yaml
additionalProperties: false        # Reject extra fields
additionalProperties: true         # Allow extra fields (default)
```

**Use `false` when:**
- Your UDF expects an exact field set
- You want to enforce strict output contracts
- You're using `content.copy()` and don't want garbage fields propagating

**Gotcha with UDFs:** If your UDF computes and returns extra fields (e.g., `enriched_title`, `word_count`), they must be listed in the schema when `additionalProperties: false`. Otherwise validation rejects them.

## Nested Objects

For complex output structures, define nested objects explicitly:

```yaml
# File schema: schema/search_results.yml
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

## TypedDict Mapping for UDFs

When UDFs return nested objects, use nested `TypedDict` classes — not `dict[str, Any]`. The framework converts `dict[str, Any]` to `additionalProperties: {type: string}`, forcing all values to strings.

```python
# BAD — schema validation errors (all values forced to string)
class MyOutput(TypedDict, total=False):
    metadata: dict[str, Any]           # int/float values become strings

# GOOD — types preserved correctly
class SearchMetadata(TypedDict, total=False):
    total_count: int
    method: str

class MatchingItem(TypedDict, total=False):
    id: str
    score: float

class MyOutput(TypedDict, total=False):
    results: list[MatchingItem]
    metadata: SearchMetadata
```

## Version-Expanded Schemas

Dynamic template variables in versioned action schemas expand at render time:

```yaml
- name: generate_distractors
  versions:
    param: stage
    range: [1, 3]
  schema:
    distractor_${stage}: string        # → distractor_1, distractor_2, distractor_3
    why_incorrect_${stage}: string
```

Use `agac render -a workflow` to verify expansion:
```bash
agac render -a my_workflow | grep -A 10 "schema:"
```

## Common Schema Mistakes

| Mistake | Symptom | Fix |
|---------|---------|-----|
| Field name doesn't match LLM output | `declared fields not found` | Align schema `id:` with LLM's natural output |
| UDF returns unlisted field with `additionalProperties: false` | `Additional properties are not allowed` | Add field to schema |
| `dict[str, Any]` in TypedDict | All values become strings | Use nested TypedDict with explicit types |
| Schema in subdirectory | Schema not found | Place directly in `schema/` (flat) |
| Forwarded fields in schema | Duplicate data, wasted tokens | Move to `passthrough` |
| `None` default for `type: string` | `None is not of type 'string'` | Use empty string `""` as default |
| Missing `required` on guard-checked field | Guard sees None, unexpected behavior | Add to `required` or handle in guard |

## Debugging Schemas

```bash
# See compiled schemas (inlined and expanded)
agac render -a my_workflow

# Check what an action actually produced
cat agent_io/target/<action>/sample.json | python3 -c "
import json, sys; data = json.load(sys.stdin)
if data:
    content = data[0]['content']
    for ns, fields in content.items():
        if isinstance(fields, dict):
            print(f'{ns}: {list(fields.keys())}')
"

# Compare schema field names with actual output (check the action's own namespace)
diff <(grep 'id:' schema/my_schema.yml | awk '{print $3}') \
     <(cat agent_io/target/my_action/sample.json | python3 -c "
import json, sys; data = json.load(sys.stdin)
if data:
    fields = data[0]['content'].get('my_action', {})
    for k in fields: print(k)
")
```
