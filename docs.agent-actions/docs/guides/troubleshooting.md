---
title: Troubleshooting
sidebar_position: 10
---

# Troubleshooting

What happens when something goes wrong in your agentic workflow? This guide helps you debug and fix common errors. Let's explore the error types, their causes, and how to resolve them.

## Error Types

### SchemaValidationError

The most common error. Occurs when data fails JSON Schema validation.

```
SchemaValidationError: Input schema validation failed for tool 'add_answer_text'
at target_word_counts -> correct_answer_words: 18 is not of type 'string'
[Context: function=add_answer_text, validation_type=input,
 error_path=target_word_counts -> correct_answer_words,
 failed_value=18, schema_constraint={'type': 'string'}]
```

**Context Fields:**

| Field | Description | Example |
|-------|-------------|---------|
| `error_path` | Dot-path to failing field | `target_word_counts -> correct_answer_words` |
| `failed_value` | The actual value received | `18`, `'some text'`, `['a', 'b']` |
| `schema_constraint` | Expected schema rule | `{'type': 'string'}` |
| `function` | Tool that failed | `add_answer_text` |
| `validation_type` | Input or output validation | `input`, `output` |

### ProcessingError

Wraps lower-level errors with record context. Think of this as a breadcrumb trail—it tells you which specific record caused the problem.

```
ProcessingError: Failed to process item
[Context: source_guid=37812c37-80a2-596b-8747-8f93e7a34e7f,
         agent_name=add_answer_text]
```

**Context Fields:**

| Field | Description |
|-------|-------------|
| `source_guid` | UUID of the record being processed |
| `agent_name` | Action that failed |

### AgentActionsError

Top-level agentic workflow failure. This wraps other errors to provide the full context of what went wrong.

```
AgentActionsError: Error generating target: Failed to process content
[Context: file_path=/path/to/data.json,
         agent_name=my_workflow]
```

## Common Errors & Fixes

Let's walk through the most common errors and how to fix them.

### Template Variable Error

**Error:**
```
Template rendering failed for agent 'write_question'

  Reference: classify.question_type
  Namespace 'classify' exists: YES
  Field 'question_type' in namespace: NO
  Available in 'classify': question_category, difficulty_level, tags

  Did you mean 'classify.question_category'?

Fix: Check that 'classify' produces the referenced field.
```

**Cause:** Template references a field that doesn't exist in the namespace. The error message shows:
- Whether the namespace (e.g., `classify`) exists
- Whether the field exists within that namespace
- Available fields you can use instead
- A suggestion if there's a similar field name (typo detection)

**Fix options:**

1. **Check the field name** - Use the suggested alternative if it's a typo
2. **Verify the dependency** - Ensure the action producing this field is in your `dependencies` list
3. **Check the upstream action's output** - Verify the action produces the expected field

---

### Source Data Structure Mismatch

**Error:**
```
Template rendering failed for agent 'my_action'

  Reference: source.content
  Namespace 'source' exists: NO
  Available namespaces: items, metadata
```

**Cause:** Source data is a wrapper object, not a flat array of records. This happens when your JSON file has metadata alongside the actual records.

**Wrong format:**
```json
{
  "exam_name": "My Exam",
  "items": [
    {"id": "1", "content": "..."},
    {"id": "2", "content": "..."}
  ]
}
```

Prompt expects `{{ source.content }}` but `source` is the wrapper, not individual items.

**Correct format:**
```json
[
  {"id": "1", "content": "..."},
  {"id": "2", "content": "..."}
]
```

**Fix options:**

1. **Restructure input** - Extract array to staging file:
   ```python
   data = json.load(open("wrapper.json"))
   records = data["items"]
   json.dump(records, open("staging/data.json", "w"))
   ```

2. **Add preprocessing action** - First action extracts items:
   ```yaml
   - name: extract_items
    kind: tool
    impl: extract_items_from_wrapper
    granularity: file
   ```

3. **Update prompts** - If wrapper is intentional:
   ```jinja2
   {% for item in source.items %}
     {{ item.content }}
   {% endfor %}
   ```

---

### Type Mismatch

**Error:**
```
18 is not of type 'string'
```

**Cause:** Integer value where string expected.

**Fix:** Convert in your tool:
```python
data['field'] = str(data['field'])
```

Or fix the TypedDict:
```python
# If the field can be int or string
field: Union[int, str]
```

---

### Array vs String Mismatch

**Error:**
```
'Audit client code...' is not of type 'array'
```

**Cause:** String value where array expected.

**Fix:** Normalize in your tool:
```python
answer_text = data.get('answer_text')
if isinstance(answer_text, str):
    answer_text = [answer_text]
```

---

### Unexpected Field

**Error:**
```
'new_field' was unexpected
```

**Cause:** Field exists in data but not declared in TypedDict.

**Fix:** Add field to TypedDict:
```python
class MyInput(TypedDict, total=False):
    existing_field: str
    new_field: str  # Add the missing field
```

Or use `total=False` to allow any fields.

---

### Mixed-Type Dict Values

**Error:**
```
'greater_than' is not of type 'integer'
```

**Cause:** Using `Dict[str, int]` but values include strings.

**Fix:** Use plain `dict` for mixed-type dictionaries:
```python
# BAD - Fails if values include strings
target_word_counts: Dict[str, int]

# GOOD - Allows any structure
target_word_counts: dict
```

---

### Missing Required Field

**Error:**
```
'question' is a required property
```

**Cause:** Schema requires field but tool didn't return it.

**Fix:** Ensure tool returns all required fields:
```python
@udf_tool()
def my_function(data: dict) -> dict:
    return {
        'question': data.get('question', ''),  # Always include
        'processed': True
    }
```

Or enable reprompting for LLM actions:
```yaml
reprompt:
  max_attempts: 4
  on_exhausted: return_last
```

## Debugging with Prompt Traces

When an LLM action produces unexpected output, the fastest path to understanding "why" is inspecting the compiled prompt and raw response. Agent Actions captures both automatically.

### Using the Data Explorer

1. Run `agac docs` to generate the documentation catalog
2. Open the Data Explorer in your browser
3. Navigate to the action's output in the Data tab
4. Find the record with unexpected output
5. Click the **Prompt Trace** accordion below the record — it shows:
   - **Compiled Prompt**: The exact text the LLM received (with all template variables resolved)
   - **LLM Response**: The raw text the LLM returned (before parsing)

### What to Look For

- **Missing context**: Template variables resolved to empty strings or wrong values — check your `context_scope` and dependency chain
- **Ambiguous instructions**: The prompt doesn't clearly constrain the output format — tighten the prompt template
- **Schema mismatch**: The LLM response doesn't match the expected JSON structure — consider enabling reprompting
- **Model badge**: Check if the model name matches what you expected — a misconfigured provider can route to the wrong model

### Querying Traces Directly

For bulk analysis across many records:

```bash
sqlite3 my_workflow/agent_io/outputs.db \
  "SELECT record_id, response_text FROM prompt_trace WHERE action_name = 'classify_issue' LIMIT 10"
```

See [Prompt Traces reference](../reference/data-io/prompt-traces.md) for the full table schema and query examples.

---

## Debugging Agentic Workflows

When an error occurs, resist the urge to start changing code immediately. Follow this systematic approach to understand what went wrong before fixing it.

### Step 1: Parse the Error

Extract key information from the error message. Agent Actions provides structured error context—use it:

1. **What type?** `SchemaValidationError`, `ProcessingError`, etc.
2. **Which field?** Look at `error_path`
3. **What value?** Look at `failed_value`
4. **What expected?** Look at `schema_constraint`
5. **Which action?** Look at `function` or `agent_name`

### Step 2: Find the Source Record

Use `source_guid` to trace the record:

```bash
# Find record in node outputs
grep -r "37812c37-80a2-596b-8747-8f93e7a34e7f" agent_io/target/
```

### Step 3: Check Node Outputs

Compare data at each stage:

```bash
# Input to failing node
cat agent_io/target/node_6_*/data.json | head -100

# Previous node output
cat agent_io/target/node_5_*/data.json | head -100
```

### Step 4: Enable Debug Mode

Get detailed tracebacks:

```bash
AGENT_ACTIONS_LOG_LEVEL=DEBUG agac run -a my_workflow
```

### Step 5: Enable Prompt Debug

See rendered prompts for LLM actions:

```yaml
- name: my_action
  prompt: $workflow.My_Prompt
  prompt_debug: true  # Logs full prompt
```

## Data Lineage

Here's where it gets interesting: every record in Agent Actions maintains tracking fields that let you trace its journey through the agentic workflow. This lineage data is invaluable for debugging.

### source_guid

Original content UUID. **Never changes** through the agentic workflow.

```json
"source_guid": "37812c37-80a2-596b-8747-8f93e7a34e7f"
```

Use this to trace any record back to its source, regardless of how many actions it has passed through.

### lineage

Array of all node_ids visited. Grows at each node.

```json
"lineage": [
  "node_0_693094fb-53d1-48d6-bdc9-781a4989d35c",
  "node_1_361c54c6-7080-4527-9a00-aaeccfd0e6ba_0",
  "node_2_e546c260-de10-4f20-8950-e09f01ea468f"
]
```

The `_0` suffix indicates this was the first record from a flattening operation.

### node_id

Identifies the specific processing node:

```
node_0_693094fb-...          # Single output
node_1_361c54c6-..._0        # Flattened, index 0
node_1_361c54c6-..._1        # Flattened, index 1
```

### Node Output Structure

```
agent_io/target/
├── node_0_extract_raw_qa/
│   └── data.json
├── node_1_flatten_questions/
│   └── data.json
├── node_2_classify_type/
│   └── data.json
└── final_workflow_output/
    └── data.json
```

## TypedDict Best Practices

### Use `total=False` for Optional Fields

```python
class MyInput(TypedDict, total=False):
    required_field: str  # Still works, just not enforced
    optional_field: str
```

### Use Plain `dict` for Mixed Types

```python
# When dict values can be int, string, or other types
metadata: dict  # Not Dict[str, int]
```

### Use Union for Polymorphic Fields

```python
# When a field can be different types
answer_text: Union[str, List[str]]
```

### Always Use `.get()` with Defaults

```python
@udf_tool()
def safe_function(data: dict) -> dict:
    value = data.get('field', '')  # Never KeyError
    items = data.get('items', [])
    return {'result': value}
```

## Reprompting

What happens when an LLM returns invalid JSON? Rather than failing immediately, Agent Actions can automatically retry with feedback about what went wrong. This is reprompting.

### Configuration

Reprompt requires explicit configuration:

```yaml
reprompt:
  max_attempts: 3          # Number of retry attempts
  on_exhausted: return_last   # return_last | raise
```

To disable: `reprompt: false`

### Configuration Options

| Option | Description |
|--------|-------------|
| `max_attempts` | Maximum retry attempts (default: 2) |
| `on_exhausted` | Behavior when exhausted: `return_last`, `raise` |

### When to Use

Consider what your agentic workflow needs:

- **Simple schemas** — Low `max_attempts` (2-3)
- **Complex schemas** — Higher `max_attempts` (4-5)
- **Critical outputs** — Maximum attempts, `on_exhausted: raise`

:::warning
Reprompting adds latency and token cost. For high-volume agentic workflows, consider fixing schema issues at the source rather than relying on retries.
:::

## Log Analysis

### Log Location

```
project/logs/agent_actions.log
```

### Search Patterns

```bash
# Find all schema validation errors
grep "SchemaValidationError" logs/agent_actions.log

# Find errors for specific action
grep "agent_name=add_answer_text" logs/agent_actions.log

# Find errors for specific field
grep "error_path=answer_text" logs/agent_actions.log
```

### Execution History

Check `artefact/runs.json` for execution metrics:

```bash
# Count failed runs
grep '"status": "FAILED"' artefact/runs.json | wc -l

# Find recent failures
grep -A5 '"status": "FAILED"' artefact/runs.json | tail -20
```

## Quick Reference

These commands and patterns are your debugging toolkit.

### Debug Commands

```bash
# Debug mode (full tracebacks)
AGENT_ACTIONS_LOG_LEVEL=DEBUG agac run -a workflow
```

### Common Fixes Cheatsheet

| Error Pattern | Quick Fix |
|---------------|-----------|
| `X is not of type 'string'` | `str(value)` or `Union[int, str]` |
| `X is not of type 'array'` | `[value] if isinstance(value, str) else value` |
| `X was unexpected` | Add field to TypedDict |
| `X is a required property` | Return field from tool or use `reprompt` |
| `Dict[str, int]` fails | Use plain `dict` |

### Debug Checklist

When debugging agentic workflow errors, work through this checklist:

1. [ ] Read full error message, note `error_path` and `failed_value`
2. [ ] Find record by `source_guid` in node outputs
3. [ ] Compare data before/after failing action
4. [ ] Check TypedDict matches actual data shape
5. [ ] Enable `prompt_debug: true` for LLM actions
6. [ ] Run with `AGENT_ACTIONS_LOG_LEVEL=DEBUG` for tracebacks
7. [ ] Consider enabling reprompt with `max_attempts: 3` for LLM schema failures

Most errors fall into one of two categories: schema mismatches (the data structure doesn't match expectations) or missing fields (required data wasn't provided). The checklist above helps you identify which category you're dealing with.

## Dependency Patterns

### Understanding Fan-in vs Parallel

When using multiple dependencies, understanding the pattern detection is crucial:

```yaml
# Pattern 1: Parallel Branches (MERGE)
dependencies: [classify_1, classify_2, classify_3]
# Same base name "classify" → outputs are merged
# Execution count: N (from merged outputs)

# Pattern 2: Fan-in (PRIMARY + CONTEXT)
dependencies: [extract, enrich, validate]
# Different actions → first is primary, others via context
# Execution count: N (from extract only)

# Pattern 3: Aggregation (MERGE with reduce_key)
dependencies: [validator_A, validator_B, validator_C]
reduce_key: parent_id
# reduce_key set → all outputs merged and grouped by key
```

### Missing Context Data in Fan-in

**Symptom:** Action only sees data from first dependency, not others.

**Cause:** Fan-in pattern requires context sources to be in `context_scope`:

```yaml
# WRONG - enrich and validate data not accessible
- name: generate_report
  dependencies: [extract, enrich, validate]

# CORRECT - all dependencies in context_scope
- name: generate_report
  dependencies: [extract, enrich, validate]
  context_scope:
    observe:
      - extract.*
      - enrich.*     # Now loaded via historical loader
      - validate.*   # Now loaded via historical loader
```

### Unexpected Execution Count

**Symptom:** Action executes more/fewer times than expected.

**Debug:**
1. Check if dependencies are parallel branches (same base name) or different actions
2. For fan-in: first dependency determines execution count
3. For parallel: merged outputs determine execution count
4. For aggregation: `reduce_key` groups determine execution count

See [Workflow Dependencies](../reference/execution/workflow-dependencies) for pattern details.
