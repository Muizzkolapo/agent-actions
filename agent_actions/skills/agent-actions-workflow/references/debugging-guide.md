# Debugging & Troubleshooting Guide

Common errors and how to fix them in agent-actions workflows.

## Error Types

### SchemaValidationError

Occurs when data fails JSON Schema validation.

**Key Context Fields:**
- `error_path`: Dot-path to problematic field (e.g., `target_word_counts -> correct_answer_words`)
- `failed_value`: The actual value that failed
- `schema_constraint`: Expected schema rule
- `function`: UDF that failed
- `validation_type`: `input` or `output`

**Example:**
```
SchemaValidationError: Input schema validation failed for UDF 'add_answer_text'
at target_word_counts -> correct_answer_words: 18 is not of type 'string'
```

### ProcessingError

Wraps lower-level errors with item context.

**Key Context:**
- `source_guid`: UUID of the data item
- `agent_name`: Action that failed

### AgentActionsError

Top-level workflow failure wrapper.

**Key Context:**
- `file_path`: JSON file being processed
- `agent_name`: Initiating agent

## Common Errors & Fixes

### JSON Parsing Error (Curly Braces in Prompts)

**Symptom:**
```
Problem: expected token ':', got '}'
```

**Cause:** Curly braces in prompt examples are interpreted as Jinja2 template syntax.

**Bad prompt:**
```markdown
{prompt MyPrompt}
Example of broken code: `{{{{{{{{ function() }}}}}s`
{end_prompt}
```

**Fix:** Avoid curly braces in examples - use alternative characters:
```markdown
{prompt MyPrompt}
Example of broken code: `]]]]]d function(argument)`
{end_prompt}
```

**Why:** Prompts use Jinja2 for context (`{{ source.field }}`), so literal `{{` in examples breaks parsing.

### Schema Format Error

**Symptom:**
```
Schema validation failed / unexpected token
```

**Cause:** Using JSON Schema format instead of agent-actions format.

**Wrong:**
```yaml
name: my_schema
type: object
properties:
  field_name:
    type: string
```

**Correct:**
```yaml
name: my_schema
fields:
  - id: field_name
    type: string
    description: "What this field contains"
```

### Type Mismatch

**Symptom:**
```
18 is not of type 'string'
```

**Fix:** Convert types in UDF:
```python
target_word_counts = {
    'correct_answer_words': str(value),  # Convert to string
}
```

### Array vs String

**Symptom:**
```
'Some text...' is not of type 'array'
```

**Fix:** Normalize in UDF:
```python
if isinstance(answer_text, str):
    answer_text = [answer_text]
```

### Mixed Dict Types

**Symptom:**
```
'greater_than' is not of type 'integer'
```

**Fix:** Use plain `dict` instead of `Dict[str, int]`:
```python
# BAD
target_word_counts: Dict[str, int]

# GOOD
target_word_counts: dict
```

### Dict[str, Any] Causes String-Only Schema

**Symptom:** (During UDF schema validation)
```
30 is not of type 'string'
Failed validating 'type' in schema['properties']['metadata']['additionalProperties']:
    {'type': 'string'}
```

**Cause:** `Dict[str, Any]` in TypedDict is incorrectly converted to `additionalProperties: {type: string}`, so all values must be strings.

**Bad:**
```python
class MyOutput(TypedDict, total=False):
    metadata: Dict[str, Any]  # Will only accept string values!
```

**Fix:** Use nested TypedDict with explicit types:
```python
class MetadataOutput(TypedDict, total=False):
    total_count: int      # int type preserved
    search_method: str

class MyOutput(TypedDict, total=False):
    metadata: MetadataOutput  # Proper type handling
```

See **udf-decorator.md → Nested TypedDicts** for complete examples.

### Missing Required Fields

**Symptom:**
```
'field_name' is a required property
```

**Fix:** Ensure UDF provides all schema-required fields. Use reprompting:
```yaml
reprompt: smart  # Retry with error feedback
```

## Debugging Workflow

1. **Check runs.json** for error details:
   ```bash
   grep "FAILED" qanalabs/artefact/runs.json
   ```

2. **Parse error context:**
   - `error_path` → Which field
   - `failed_value` → What was received
   - `schema_constraint` → What was expected

3. **Trace by source_guid:**
   - Find GUID in error
   - Check node outputs in `agent_io/target/node_X_*/`
   - Track data transformation at each stage

4. **Enable prompt debugging:**
   ```yaml
   prompt_debug: true
   ```

## Reprompting System

Auto-retry on schema failures:

| Preset | Max Attempts | JSON Repair | LLM Critique |
|--------|--------------|-------------|--------------|
| `basic` | 3 | Yes | No |
| `smart` | 4 | Yes | Yes (after 2nd) |
| `thorough` | 5 | Yes | Yes (after 1st) |

```yaml
reprompt: smart
# or
reprompt:
  preset: thorough
  max_attempts: 5
```

## Validation Commands

```bash
# Pre-flight validation only
agac run -a workflow --validate-only

# With static typing
agac run -a workflow --validate-only --static-typing

# Debug mode (full tracebacks)
agac run -a workflow --debug
```

## Log Analysis

**Log location:** `qanalabs/logs/agent_actions.log`

**Search patterns:**
```bash
# Find schema errors
grep "SchemaValidationError" logs/agent_actions.log

# Find specific field errors
grep "answer_text" logs/agent_actions.log

# Find function errors
grep "function=add_answer_text" logs/agent_actions.log
```

## Prevention Best Practices

1. **Validate early:**
   ```bash
   agac run -a workflow --validate-only
   ```

2. **Use guards for quality gates:**
   ```yaml
   guard:
     condition: 'score >= 50'
     on_false: "filter"
   ```

3. **Handle edge cases in UDFs:**
   ```python
   value = data.get('field', '')  # Always use .get() with defaults
   ```

4. **Use appropriate types:**
   ```python
   # For polymorphic values
   answer_text: Union[str, List[str]]

   # For mixed-type dicts
   target_counts: dict
   ```
