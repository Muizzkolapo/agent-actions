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

Context references in `observe` are auto-resolved by the framework. Only declare what's needed for execution ordering.

## 18. Running Full Data During Development

**Symptom:** Workflow takes 30 minutes to run while iterating on prompts.

**Cause:** Processing all records and files when you only need a few to validate.

**Fix:** Use `record_limit` and `file_limit` to cap processing:
```yaml
actions:
  - name: extract
    record_limit: 10   # Process only 10 records per file
    file_limit: 2       # Walk only 2 files
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
