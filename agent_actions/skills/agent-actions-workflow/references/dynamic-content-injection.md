# Dynamic Content Injection Patterns

How to inject dynamic, randomized, or computed content into LLM prompts.

## The Problem

You need to inject dynamic content (randomized values, computed text, conditional prompts) into your workflow. The naive approach of using `dispatch_task()` in prompts **does not work reliably** - the LLM may output the literal text instead of the function result.

## Solution: Tool Action Injection Pattern

Use a **tool action** to inject dynamic content between the upstream action and the LLM action that needs it.

### Pattern Overview

```
[upstream_action] → [inject_action (tool)] → [llm_action]
```

The tool action:
1. Reads context from upstream
2. Computes/randomizes the dynamic content
3. Adds it to the context for the LLM action

### Example: Randomized Scenario Openers

**Goal:** Each question should start with a different randomized opener based on question type.

**WRONG - Using dispatch_task in prompt (unreliable):**
```markdown
{prompt Write_Question}
Use this opener: dispatch_task('get_opener')
...
{end_prompt}
```
This often results in the LLM outputting `"dispatch_task('get_opener')"` literally.

**RIGHT - Using tool action injection:**

**Step 1: Create the UDF**
```python
import random
from agent_actions import udf_tool

OPENERS = {
    "debugging": [
        "During monitoring, you notice",
        "Your team observes",
        "A production incident reveals",
    ],
    "design_review": [
        "During a design review, an engineer proposes",
        "A colleague suggests",
        "In an architecture discussion, a team member suggests",
    ],
    "violation": [
        "An integration test fails because",
        "A security review reveals",
        "During an audit, you find",
    ],
}

@udf_tool()
def inject_random_opener(data: dict) -> dict:
    """Inject a randomized scenario opener based on question type."""
    content = data.get('content', data)

    # Get question type from upstream context
    quiz_type = content.get('quiz_type_used', 'general').lower()

    # Map quiz type to opener category
    type_to_category = {
        'consequence': 'design_review',
        'diagnosis': 'debugging',
        'violation': 'violation',
    }
    category = type_to_category.get(quiz_type, 'design_review')

    # Random selection
    opener = random.choice(OPENERS.get(category, OPENERS['design_review']))

    return {
        "suggested_opener": opener,
        "quiz_type": quiz_type.upper()
    }
```

**Step 2: Configure the tool action**
```yaml
- name: inject_opener
  dependencies: [get_authoring_prompt]
  kind: tool
  impl: inject_random_opener
  intent: "Inject randomized scenario opener based on question type"
  granularity: Record
  context_scope:
    observe:
      - get_authoring_prompt.quiz_type_used
    passthrough:
      - get_authoring_prompt.*    # Forward all fields from upstream
```

**Step 3: Use in prompt template**
```markdown
{prompt Write_Question}
## SCENARIO OPENER (MANDATORY)

**Your assigned opener**: {{ inject_opener.suggested_opener }}

YOU MUST START YOUR QUESTION WITH THIS EXACT OPENER PHRASE.
...
{end_prompt}
```

**Step 4: Update LLM action to depend on injector**
```yaml
- name: write_question
  dependencies: [inject_opener]    # Changed from get_authoring_prompt
  context_scope:
    observe:
      - inject_opener.*            # Access injected fields
      - source.page_content
```

### Key Points

1. **Tool actions run Python code** - Full control over logic, randomization, conditionals

2. **Use `passthrough` to forward fields** - Don't lose upstream context
   ```yaml
   context_scope:
     observe:
       - upstream.specific_field    # Fields you compute from
     passthrough:
       - upstream.*                 # Forward everything else
   ```

3. **Randomization happens per-record** - Each record gets independent random values

4. **Return dict, not list** - When using passthrough, return a dict with just the new fields

### When to Use This Pattern

| Use Case | Example |
|----------|---------|
| Randomized prompts | Different scenario openers |
| Conditional prompts | Different instructions based on type |
| Computed values | Dynamic word counts, thresholds |
| Type-based routing | Different templates per category |

### Common Mistakes

| Mistake | Fix |
|---------|-----|
| dispatch_task() in prompt | Use tool action injection |
| Missing passthrough | Add `passthrough: [upstream.*]` |
| LLM ignores injected value | Make prompt instruction emphatic |
| Same value for all records | Ensure random.choice() called per record |

## Dispatch in Prompts: Shared Prompt with Dynamic Fields

When multiple actions share the same prompt but need different output field names (e.g., `_1`, `_2`, `_3` suffixes), use `dispatch_task()` to generate the entire prompt with the correct field names baked in.

### The Problem

Three parallel actions share one prompt but each needs different output fields:
- `generate_distractor_1` → `explanation_why_it_is_incorrect_1`
- `generate_distractor_2` → `explanation_why_it_is_incorrect_2`
- `generate_distractor_3` → `explanation_why_it_is_incorrect_3`

If the prompt uses generic field names, gpt-4o-mini drops the suffix ~15% of the time.

### Solution: dispatch_task() generates the full prompt

**Step 1: Create the dispatch tool**

```python
from agent_actions import udf_tool

def _detect_number(context: dict) -> int:
    """Detect which variant from observed field names."""
    for key in context:
        if isinstance(context[key], dict):
            for field in context[key]:
                for n in (1, 2, 3):
                    if f"distractor_{n}_text" in field:
                        return n
    return 1

@udf_tool
def generate_distractor_prompt(input_data: dict) -> dict:
    n = _detect_number(input_data)
    prompt_text = f"""Your prompt text here...

## OUTPUT
```json
{{{{
  "thinking_process_{n}": "...",
  "explanation_why_it_is_incorrect_{n}": "..."
}}}}
```"""
    return {"authoring_prompt": prompt_text}
```

**Step 2: Single prompt with dispatch**

```markdown
{prompt Generate_Distractor_Explanation}
dispatch_task('generate_distractor_prompt')
{end_prompt}
```

**Step 3: All actions reference the same prompt**

```yaml
- name: generate_distractor_1
  prompt: $quiz_gen.Generate_Distractor_Explanation
- name: generate_distractor_2
  prompt: $quiz_gen.Generate_Distractor_Explanation
- name: generate_distractor_3
  prompt: $quiz_gen.Generate_Distractor_Explanation
```

### Key Requirements

- Dispatch tools **must** use `@udf_tool` decorator — plain functions won't be discovered
- Signature: `context_data_str: str, *args` → returns `str` (the prompt text)
- The returned string replaces the `dispatch_task()` call in the prompt
- Use `{{{{` and `}}}}` for literal braces in f-strings containing JSON
- Must be at `tools/` root directory — subdirectories (`tools/shared/`, `tools/workflow-name/`) won't be found
- Parse context with `json.loads(context_data_str)` — the framework passes a JSON string, not a dict

### Common Pitfalls

- **Jinja in examples**: If your prompt contains `{{ ref('table') }}` as an example, the framework's Jinja engine will try to resolve it. Strip Jinja-like syntax from prompt examples or use plain text descriptions instead.
- **Field name leaking**: If the prompt references `distractor_1_text` by name, the LLM may output it literally ("People might choose distractor_1_text because..."). Use natural language ("the wrong option") instead.
- **Third-person references**: LLMs default to "This option claims..." which sounds academic. Instruct them to discuss ideas directly.

## Alternative: Schema Field Injection

For simpler cases, you can use schema-level dispatch:

```yaml
schema:
  computed_field: dispatch_task('compute_function')
```

However, **tool action injection is more reliable** and gives you full Python control.
