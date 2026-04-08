# Common Pitfalls Reference

Frequent mistakes and how to avoid them.

## 1. Guards Filtering All Records

**Symptom:** Downstream actions have 0 records (sample.json contains `[]`).

**Cause:** Guard condition evaluated to false for ALL records.

**Example:**
```
validate_code_quality: 5 records (all validation_status="FAIL")
generate_explanation:  0 records (guard filters all)
```

**Fix:**
- Fix upstream prompts to produce passing values
- Lower threshold: `>= 7` instead of `>= 8`
- Allow multiple statuses: `'status == "PASS" or status == "NEEDS_REVIEW"'`

## 2. Duplicate UDF Function Names

**Symptom:** Error about duplicate function name.

**Cause:** Same `@udf_tool()` function name in multiple directories.

**Fix:**
- Remove one duplicate
- Rename to unique names
- Move shared code to `tools/shared/`

## 3. Forgetting Content Wrapper

**Symptom:** KeyError or wrong output.

**Wrong:**
```python
def my_udf(data):
    return [{'result': data['my_field']}]
```

**Correct:**
```python
def my_udf(data):
    content = data.get('content', data)
    return [{'result': content['my_field']}]
```

## 4. UDF Returning Dict Instead of List

**Wrong:**
```python
return {'result': 'value'}
```

**Correct:**
```python
return [{'result': 'value'}]
```

## 5. Guard on Wrong Action

**Symptom:** Guard doesn't filter as expected.

**Cause:** Guards check INPUT, not OUTPUT.

**Wrong:**
```yaml
- name: validate_data
  guard:
    condition: 'validation_status == "PASS"'  # Checks INPUT!
```

**Correct:**
```yaml
- name: validate_data
  # No guard - produces validation_status

- name: next_action
  dependencies: [validate_data]
  guard:
    condition: 'validation_status == "PASS"'  # Checks validate_data OUTPUT
```

## 6. Cross-Workflow: impl vs Action Name

**Wrong:**
```yaml
dependencies:
  - workflow: upstream
    action: generate_vscode_mockup  # This is impl name!
```

**Correct:**
```yaml
dependencies:
  - workflow: upstream
    action: format_code_blocks  # This is action name
```

## 7. Empty Output Looks Like Success

**Symptom:** Workflow shows "success" but no useful output.

**Cause:** Guards filtered everything, or missing schema/prompt.

**Always verify:**
- Check record counts in each sample.json
- Look for 2-byte files (empty arrays)
- Check events.json for errors

## 8. Dependency Not in context_scope

**Error:** `Dependency 'X' declared but not referenced in context_scope`

**Wrong:**
```yaml
dependencies: [generate_output]
context_scope:
  observe:
    - source.raw_data  # Missing generate_output!
```

**Correct:**
```yaml
dependencies: [generate_output]
context_scope:
  observe:
    - generate_output.*  # REQUIRED
    - source.raw_data
```

## 9. Versioned Actions Context Scope

**Wrong:**
```yaml
context_scope:
  observe:
    - filter_quality.vote  # Won't work with versions!
```

**Correct:**
```yaml
context_scope:
  observe:
    - filter_quality.*  # Wildcard captures ALL versions
```

## 10. Schema Files in Nested Directory / Schema References with Folder Prefix

**Error:** `Schema file not found`

**Cause:** Framework only looks in `schema/`, not recursively. Schema names are globally unique.

**Wrong file path:** `schema/my_workflow/my_schema.yml`

**Correct file path:** `schema/my_schema.yml`

**Wrong reference in YAML:**
```yaml
schema: review_analyzer/extract_claims   # Folder prefix not allowed!
```

**Correct reference in YAML:**
```yaml
schema: extract_claims                   # Name only - globally unique
```

## 11. Legacy Workflow Format

**Symptom:** Workflow uses `plan:` section.

**Legacy:**
```yaml
plan:
  - action_a
  - action_b <- action_a
```

**Current:**
```yaml
actions:
  - name: action_a
    dependencies: []

  - name: action_b
    dependencies: [action_a]
```

## 12. Missing Return Type in UDF

**Always return `list[dict[str, Any]]`:**

```python
@udf_tool()
def my_udf(data: dict[str, Any]) -> list[dict[str, Any]]:
    # ...
    return [result]  # List!
```

## 13. dispatch_task() in Prompt Templates

**Symptom:** LLM outputs the literal text `dispatch_task('function_name')` instead of the function result.

**Cause:** `dispatch_task()` in prompt templates is unreliable - it may not be processed before the prompt is sent to the LLM.

**Wrong:**
```markdown
{prompt Write_Question}
Use this opener: dispatch_task('get_opener')
...
{end_prompt}
```

**Correct:** Use a tool action to inject dynamic content:

```yaml
# Step 1: Tool action injects content
- name: inject_opener
  kind: tool
  impl: inject_random_opener
  context_scope:
    passthrough:
      - upstream.*

# Step 2: LLM action uses injected content
- name: write_question
  dependencies: [inject_opener]
  context_scope:
    observe:
      - inject_opener.*
```

```markdown
{prompt Write_Question}
Use this opener: {{ inject_opener.suggested_opener }}
...
{end_prompt}
```

See: **[Dynamic Content Injection](dynamic-content-injection.md)**

## 14. `seed_data.` vs `seed.` Namespace

**Symptom:** Seed data in prompts/observe resolves to empty or undefined.

**Cause:** The config key is `seed_data:` (or `seed_path:`) but the runtime namespace is `seed.` — not `seed_data.`.

**Wrong:**
```yaml
observe:
  - seed_data.rubric         # ← Wrong namespace
```
```
{{ seed_data.rubric.score_range }}   ← Won't resolve
```

**Correct:**
```yaml
observe:
  - seed.rubric              # ← Correct namespace
```
```
{{ seed.rubric.score_range }}        ← Works
```

## 15. UDF Defaults Don't Match Schema Types

**Symptom:** Schema validation errors on UDF output despite fields being present.

**Cause:** Default/fallback values in the UDF don't match the schema type.

**Wrong:**
```python
service_tier = None    # schema says type: string → None fails validation
assigned_teams = None  # schema says type: array → None fails validation
```

**Correct:**
```python
service_tier = ""      # empty string satisfies type: string
assigned_teams = []    # empty list satisfies type: array
```

## 16. Stale Cache Poisons Re-runs

**Symptom:** Re-running after a failure completes in 0.03s with empty output. Actions show "completed" from cached empty results.

**Cause:** Failed runs cache empty results. Next run picks up cached empties instead of re-running.

**Fix:**
```bash
rm -rf agent_workflow/<workflow>/agent_io/target/*
rm -rf agent_workflow/<workflow>/agent_io/source/
agac run -a <workflow>
```

## 17. Redundant Dependencies

**Symptom:** Action declares dependencies it doesn't need.

**Cause:** Confusing execution ordering (`dependencies`) with data access (`context_scope`). If action B is already upstream of action C through the dependency chain, you don't need to declare B as a dependency of D — only declare C.

**Wrong:**
```yaml
- name: assign_team
  dependencies: [classify_issue, assess_severity]  # classify_issue is redundant
```

**Correct:**
```yaml
- name: assign_team
  dependencies: [assess_severity]  # classify_issue is transitively upstream
```

`dependencies` controls execution ordering and file flow. If an action is already transitively upstream through the dependency chain, listing it again is redundant.

## 18. Running Full Data During Development

**Symptom:** Workflow takes 30 minutes to run while iterating on prompts.

**Cause:** Processing all records and files when you only need a few to validate.

**Fix:** Use `record_limit` and `file_limit` to cap processing. `record_limit` works on **any action** — not just start nodes — so you can test a single downstream action without re-running the full pipeline:
```yaml
actions:
  - name: extract
    record_limit: 10   # Process only 10 records per file
    file_limit: 2       # Walk only 2 files

  - name: expensive_llm_action
    dependencies: [extract]
    record_limit: 2     # Test prompt on 2 records before full API spend
```

Remove limits when ready for production. Changing limits between runs automatically invalidates the action's completion status so it re-executes.

## 19. Missing passthrough When Injecting Content

**Symptom:** Downstream action can't access upstream fields after injection.

**Cause:** Tool action doesn't forward upstream fields.

**Wrong:**
```yaml
- name: inject_opener
  context_scope:
    observe:
      - upstream.quiz_type    # Only observes, doesn't forward
```

**Correct:**
```yaml
- name: inject_opener
  context_scope:
    observe:
      - upstream.quiz_type
    passthrough:
      - upstream.*            # Forward ALL upstream fields
```

**Note:** With passthrough, UDF returns `dict` (not list) with ONLY new fields.

## 20. Guard Conditions Can't Reference `output_field` Values

**Symptom:** Guard condition `severity != "low"` doesn't filter as expected.

**Cause:** With `output_field`, the value lives under the output field name in the data namespace, but guard conditions can't resolve it. This is a known framework limitation.

**No working syntax currently.** If you need to filter on non-JSON output, use a tool action to post-process instead of a guard.

## 21. `additionalProperties: false` Blocks Unlisted UDF Fields

**Symptom:** Schema validation error on a field your UDF returns.

**Cause:** Schema has `additionalProperties: false` but UDF returns a field not listed in the schema.

**Fix:** Add every field your UDF returns to the schema, even computed/derived fields.

```yaml
# If UDF returns {"title": "...", "parties": [...], "risk_score": 0.8}
# then schema must list ALL three:
fields:
  - id: title
    type: string
  - id: parties
    type: array
  - id: risk_score
    type: number
additionalProperties: false
```

## 22. Drop Directives on Passthrough Fields Match Nothing

**Symptom:** Drop directive produces repeated runtime warnings but doesn't drop anything.

**Cause:** Drop directives only apply to schema fields in observed namespaces. Passthrough fields are not in the schema namespace — they're merged after validation.

```yaml
# WRONG — passthrough fields can't be dropped
context_scope:
  drop:
    - upstream_action.passthrough_field  # matches nothing, warns

# If you need to exclude passthrough fields, don't passthrough them:
context_scope:
  passthrough:
    - upstream_action.field_i_want      # selective, not wildcard
```

## 23. Tool UDF Accesses Fields via Flat Keys (Silent Default)

**Symptom:** Tool action produces zero/default values for all records despite upstream actions completing successfully.

**Cause:** UDFs access upstream fields via flat `content.get("field")` but the framework delivers fields **namespaced by action name** — `content["action_name"]["field"]`, not `content["field"]`.

**Wrong:**
```python
score = content.get("consensus_score", 0)  # None — field is namespaced
```

**Correct:**
```python
aggregate = content.get("aggregate_scores", {})
score = aggregate.get("consensus_score", 0)  # Namespaced access
```

## 24. Schema Field Name Doesn't Match LLM Output

**Symptom:** Downstream action fails with "declared fields not found" even though the upstream action completed OK.

**Cause:** The schema says `id: claims` but the LLM produces `factual_claims` (influenced by the prompt wording). Schema validation may not catch this if the field isn't required, and the wrong name flows into the storage backend.

**Fix:**
1. Check the storage backend output for the action
2. Compare actual field names against schema `id:` values
3. Rename the schema field to match what the LLM naturally produces
4. Update all observe references and prompt templates

## 25. Guard-Filtered Fields Cause Schema Validation Failures

**Symptom:** `None is not of type 'object'` or `Additional properties are not allowed` on a downstream tool action.

**Cause:** When an upstream action has `on_false: "filter"`, its output fields are absent for filtered records. If the downstream tool's schema declares those fields:
- As `type: object` (not nullable) → rejects None
- NOT in the schema at all → rejects as "additional properties" when the guard passes

**Fix:** Declare the field in the schema but NOT in `required`. The tool should omit the key (not set it to None) when the upstream was filtered:
```python
if content.get("response_text"):
    result["merchant_response"] = {"response_text": content["response_text"]}
```

## 26. Versions Range Off-by-One

**Symptom:** `Dependency 'action_0' declared but not referenced in context_scope`

**Cause:** `range: [0, 3]` creates versions 0,1,2,3 (4 versions) but the aggregate only observes `action_1.*`, `action_2.*`, `action_3.*`.

**Fix:** Use `range: [1, 3]` for 3 versions (1-indexed), matching the observe references.

## 27. Reprompt Validation UDF Not Discovered

**Symptom:** Framework ignores the `reprompt.validation` setting — no reprompting happens.

**Cause:** The UDF file exists but isn't in the tools discovery path.

**Fix:** Put it in `tools/shared/reprompt_validations.py` with a `tools/shared/__init__.py`:
```
tools/
├── my_workflow/
│   └── my_tool.py
└── shared/
    ├── __init__.py
    └── reprompt_validations.py
```

## 28. Guard Condition Uses != or > Operators

**Symptom:** Guard skips ALL records even when field values should pass the condition.

**Cause:** Known parser bug — the `WhereClauseParser` silently maps `!=` and `>` to `==`.

**Test directly:**
```python
from agent_actions.input.preprocessing.filtering.guard_filter import GuardFilter, FilterItemRequest
gf = GuardFilter()
r = gf.filter_item(FilterItemRequest(data={"severity": "high"}, condition='severity != "low"'))
print(r.matched)  # Returns False — BUG
```

**Workaround:** Avoid `!=` and `>` in guard conditions. Use positive conditions:
- Instead of `severity != "low"` → use `severity == "medium" or severity == "high"`
- Instead of `score > 6` → use `score >= 7`
