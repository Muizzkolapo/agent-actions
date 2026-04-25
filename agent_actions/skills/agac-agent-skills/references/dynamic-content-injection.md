# Dynamic Content Injection

## Tool Action Injection (Preferred)

Inject computed/randomized content via a tool action between upstream and LLM action.

```
[upstream] → [inject_action (tool)] → [llm_action]
```

**DO NOT** use `dispatch_task()` directly in prompts for dynamic values -- the LLM outputs the literal string.

### UDF

```python
import random
from agent_actions import udf_tool

OPENERS = {
    "debugging": ["During monitoring, you notice", "Your team observes"],
    "design_review": ["During a design review, an engineer proposes"],
}

@udf_tool()
def inject_random_opener(data: dict) -> dict:
    quiz_type = data.get('quiz_type_used', 'general').lower()
    opener = random.choice(OPENERS.get(quiz_type, OPENERS['design_review']))
    return {"suggested_opener": opener, "quiz_type": quiz_type.upper()}
```

### YAML

```yaml
- name: inject_opener
  dependencies: [get_authoring_prompt]
  kind: tool
  impl: inject_random_opener
  granularity: Record
  context_scope:
    observe:
      - get_authoring_prompt.quiz_type_used
    passthrough:
      - get_authoring_prompt.*    # Forward all upstream fields
```

### Prompt

```markdown
{prompt Write_Question}
**Your assigned opener**: {{ inject_opener.suggested_opener }}
{end_prompt}
```

LLM action depends on `inject_opener`, not on `get_authoring_prompt`.

### Gotchas

- `passthrough: [upstream.*]` required or downstream loses upstream fields
- Return `dict`, not `list` -- passthrough mode expects flat dict
- `random.choice()` runs per-record automatically in Record granularity

---

## dispatch_task() in Prompts

For shared prompts needing different field names per action (e.g. `_1`, `_2`, `_3` suffixes). The dispatch tool generates the full prompt text with correct names baked in.

### Dispatch UDF

```python
from agent_actions import udf_tool

@udf_tool
def generate_distractor_prompt(input_data: dict) -> dict:
    n = _detect_number(input_data)
    prompt_text = f"""Your prompt...
```json
{{{{
  "thinking_process_{n}": "...",
  "explanation_why_it_is_incorrect_{n}": "..."
}}}}
```"""
    return {"authoring_prompt": prompt_text}
```

### Prompt file

```markdown
{prompt Generate_Distractor_Explanation}
dispatch_task('generate_distractor_prompt')
{end_prompt}
```

All variant actions reference the same prompt -- dispatch detects which variant from observed field names.

### Dispatch requirements

- Must use `@udf_tool` decorator -- plain functions not discovered
- Signature: `context_data_str: str, *args` -> returns `str`
- Parse context with `json.loads(context_data_str)` -- framework passes JSON string, not dict
- Must be at `tools/` root -- subdirectories (`tools/shared/`, `tools/workflow-name/`) not found
- Use `{{{{` / `}}}}` for literal braces in f-strings

### Dispatch gotchas

- **Jinja in examples**: `{{ ref('table') }}` in prompt text triggers Jinja resolution. Use plain text instead.
- **Field name leaking**: If prompt mentions `distractor_1_text`, LLM outputs it literally. Use natural language ("the wrong option").
- **Third-person bias**: LLMs default to "This option claims...". Instruct direct discussion.

## Schema Field Injection (Alternative)

```yaml
schema:
  computed_field: dispatch_task('compute_function')
```

Less reliable than tool action injection.
