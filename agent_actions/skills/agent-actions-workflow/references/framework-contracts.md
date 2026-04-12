# Framework Contracts Reference

What each framework feature promises, its current status, and how to work with it. Items marked **Working** describe correct behavior you need to follow. Items marked **Known limitation** or **Partially implemented** describe gaps with workarounds.

---

## Context Scope

### 1. Guard filtering: guards check INPUT, not OUTPUT

**Status:** Working — by design.

Guards evaluate the **input** to an action (upstream output), not the action's own output. Place the guard on the action that *consumes* the field, not the one that *produces* it.

```yaml
# Guard goes on the consumer, not the producer
- name: validate_data           # Produces validation_status — no guard
- name: next_action
  dependencies: [validate_data]
  guard:
    condition: 'validation_status == "PASS"'  # Checks validate_data's output
```

If all records are filtered (0 records downstream), the guard condition was false for every record. Fix: adjust upstream prompts, lower thresholds, or allow multiple statuses.

### 2. Dependency not in context_scope

**Status:** Working — caught by static analyzer.

Every dependency must appear in `context_scope`. The static analyzer raises `Dependency 'X' declared but not referenced in context_scope`.

```yaml
dependencies: [generate_output]
context_scope:
  observe:
    - generate_output.*  # Required — must reference the dependency
    - source.raw_data
```

### 3. Versioned actions require wildcard observe

**Status:** Working — versions expand action names at runtime.

```yaml
context_scope:
  observe:
    - filter_quality.*   # Wildcard captures ALL version expansions
```

Do not reference specific fields (`filter_quality.vote`) — use wildcard to capture all version outputs.

### 4. Drop directives on passthrough fields

**Status:** Known limitation — drop only applies to observed namespaces.

Drop directives only affect schema fields in observed namespaces. Passthrough fields bypass the LLM context entirely and merge after validation — `drop` cannot remove them.

```yaml
# If you need to exclude a field, don't passthrough it:
context_scope:
  passthrough:
    - upstream_action.field_i_want    # Selective, not wildcard
```

### 5. Missing passthrough when injecting content

**Status:** Working — by design.

Tool actions that inject content must explicitly forward upstream fields via `passthrough`. Without it, downstream actions lose access.

```yaml
- name: inject_opener
  context_scope:
    observe: [upstream.quiz_type]
    passthrough:
      - upstream.*                    # Forward ALL upstream fields
```

With passthrough, UDF returns `dict` (not list) with only new fields.

---

## UDF Patterns

### 6. Content wrapper

**Status:** Working — framework provides data in `content` key.

Always use the safety wrapper. In record mode, data is usually already unwrapped, but the wrapper handles both cases:

```python
def my_udf(data):
    content = data.get('content', data)  # Always use this
    return [{'result': content['my_field']}]
```

### 7. Return type: list vs dict

**Status:** Working — return type depends on config.

- Without passthrough: return `list[dict]`
- With passthrough in YAML: return `dict` with only new fields

### 8. Namespaced field access

**Status:** Working — fields are namespaced by action name, by design.

UDFs receive upstream fields nested under the action name that produced them. Flat access (`content.get("field")`) returns None.

```python
# CORRECT — namespaced access
score = content.get("aggregate_scores", {}).get("consensus_score", 0)

# WRONG — flat access returns None
score = content.get("consensus_score", 0)
```

### 9. UDF defaults must match schema types

**Status:** Working — JSON Schema validation enforced.

Default/fallback values must match the schema type. `None` fails validation for `type: string` or `type: array`.

```python
service_tier = ""      # empty string satisfies type: string
assigned_teams = []    # empty list satisfies type: array
```

### 10. Duplicate UDF function names

**Status:** Working — caught at import time.

`@udf_tool()` function names must be unique across all tool directories. Move shared code to `tools/shared/`.

### 11. Missing return type annotation

**Status:** Working — required for correct schema inference.

```python
@udf_tool()
def my_udf(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [result]  # List!
```

### 12. dispatch_task()

**Status:** Partially implemented — works reliably in schema injection. May fail in prompt templates if the function returns None.

`dispatch_task()` calls a UDF function during prompt/schema rendering and injects the result. In prompt templates, if the function returns None, it raises an error rather than inserting an empty value.

**Workaround:** Use a tool action with passthrough as an alternative for dynamic content:

```yaml
- name: inject_opener
  kind: tool
  impl: inject_random_opener
  context_scope:
    passthrough: [upstream.*]

- name: write_question
  dependencies: [inject_opener]
  context_scope:
    observe: [inject_opener.*]
```

See: **[Dynamic Content Injection](dynamic-content-injection.md)**

---

## Guards

### 13. Guard conditions see flattened field names

**Status:** Working — by design. See Guards section in SKILL.md for examples.

### 14. Guard conditions with output_field values

**Status:** Known limitation — guard cannot resolve `output_field` values.

With `json_mode: false` and `output_field`, the value lives under the output field name in the data namespace, but guard conditions cannot resolve it.

**Workaround:** Use a tool action to post-process instead of a guard.

### 15. Guard-filtered fields cause downstream schema failures

**Status:** Known limitation — filtered records have absent fields.

When `on_false: "filter"` removes records, fields produced by the filtered action are absent for those records. Downstream schemas that require those fields fail.

**Workaround:** Declare the field in the schema but NOT in `required`. In the UDF, omit the key (not set it to None) when the upstream was filtered:

```python
if content.get("response_text"):
    result["merchant_response"] = {"response_text": content["response_text"]}
```

### 16. Guard operators

**Status:** Working — all comparison operators supported.

Guards support `==`, `!=`, `>`, `>=`, `<`, `<=`, `and`, `or`, `not`, `IN`/`NOT IN`, `CONTAINS`/`NOT CONTAINS`, `LIKE`/`NOT LIKE`, `BETWEEN`/`NOT BETWEEN`, `IS NULL`/`IS NOT NULL`, and built-in functions (`len()`, `str()`, `int()`, `float()`, `abs()`, `min()`, `max()`).

Quote string literals: `status == "approved"` — unquoted strings are treated as field names.

---

## Schemas

### 17. Schema files must be flat

**Status:** Working — framework searches `schema/` non-recursively.

Schema names are globally unique. Place all schema files directly in `schema/`, not in subdirectories.

```yaml
schema: extract_claims              # Name only — not review_analyzer/extract_claims
```

### 18. additionalProperties: false blocks unlisted UDF fields

**Status:** Working — standard JSON Schema behavior.

If your schema has `additionalProperties: false`, every field your UDF returns must be listed in the schema. Add computed/derived fields explicitly.

### 19. Schema field name doesn't match LLM output

**Status:** Working — schema enforces exact field names.

If the schema says `id: claims` but the LLM produces `factual_claims` (influenced by prompt wording), the field flows through with the wrong name. Fix: rename the schema field to match what the LLM naturally produces, then update all observe references.

---

## Workflow Configuration

### 20. Cross-workflow: impl vs action name

**Status:** Working — use the `name:` field from the YAML, not the `impl:` function name.

```yaml
# CORRECT — action name
dependencies:
  - workflow: upstream
    action: format_code_blocks

# WRONG — impl/function name
dependencies:
  - workflow: upstream
    action: generate_vscode_mockup
```

### 21. Versions range off-by-one

**Status:** Working — range is inclusive on both ends.

`range: [0, 3]` creates versions 0,1,2,3 (4 versions). Use `range: [1, 3]` for 3 versions (1-indexed), matching the observe references.

### 22. seed_data. vs seed. namespace

**Status:** Working — the config key and reference prefix differ, by design.

The config key is `seed_path:` (or `seed_data:`) but the runtime namespace is `seed.` — not `seed_data.`.

```yaml
observe: [seed.rubric]              # Correct
# NOT: seed_data.rubric             # Wrong — silently resolves to empty
```

In prompts: `{{ seed.rubric.score_range }}`. In UDFs: `content.get("seed", {}).get("rubric", {})`.

### 23. Redundant dependencies

**Status:** Working — auto-inference handles context dependencies.

`dependencies` controls execution ordering. Actions referenced in `observe`/`passthrough` but not in `dependencies` are auto-inferred as context dependencies. If an action is already transitively upstream, don't list it again.

### 24. Legacy workflow format

**Status:** Deprecated — use `actions:` list with `dependencies:`.

The `plan:` section format is legacy. Use the current `actions:` format with explicit `dependencies:`.

### 25. Reprompt validation UDF not discovered

**Status:** Working — UDF must be in the tool discovery path.

Put reprompt validation UDFs in `tools/shared/reprompt_validations.py` with a `tools/shared/__init__.py`. The static analyzer validates UDF names exist at `agac validate` time.

---

## Execution

### 26. Empty output looks like success

**Status:** Working — by design (guards filter silently).

Workflows show "success" even when guards filter all records. Always verify:
- Check record counts in each `sample.json`
- Look for 2-byte files (empty arrays: `[]`)
- Check `events.json` for guard/error events

### 27. Stale cache poisons re-runs

**Status:** Known limitation — failed runs cache empty results.

Failed runs cache empty results. Next run picks up cached empties instead of re-running. Changing `record_limit` or `file_limit` between runs automatically invalidates the cache.

**Workaround:**
```bash
rm -rf agent_workflow/<workflow>/agent_io/target/*
rm -rf agent_workflow/<workflow>/agent_io/source/
agac run -a <workflow>
```

### 28. Running full data during development

**Status:** Working — use record_limit and file_limit.

Use `record_limit` and `file_limit` to cap processing during development. `record_limit` works on **any action** — not just start nodes:

```yaml
- name: expensive_llm_action
  record_limit: 2     # Test prompt on 2 records before full API spend
```

Remove limits when ready for production.
