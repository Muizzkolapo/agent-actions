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

## Alternative: Schema Field Injection

For simpler cases, you can use schema-level dispatch (if supported):

```yaml
schema:
  computed_field: dispatch_task('compute_function')
```

However, **tool action injection is more reliable** and gives you full Python control.
