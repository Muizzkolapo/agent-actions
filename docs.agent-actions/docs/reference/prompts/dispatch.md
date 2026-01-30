---
title: Dynamic Dispatch
sidebar_position: 2
---

# Dynamic Dispatch

The `dispatch_task()` function calls tools at template render time, enabling data-driven selection of prompts, schemas, or configuration values.

## Basic Usage

### In Prompts

```markdown
{prompt ScenarioGenerator_prompt}
dispatch_task('handle_quiz_type')
{end_prompt}
```

### In Schemas

```yaml
- name: generate_question
  prompt: $quiz_gen.ScenarioGenerator_prompt
  schema: dispatch_task('select_output_schema')
```

## Creating a Dispatch Tool

```python
from agent_actions import udf_tool

@udf_tool
def handle_quiz_type(input_data: dict) -> dict:
    """Return appropriate authoring prompt based on quiz type."""
    quiz_type = input_data.get("quiz_type", "APPLICATION").upper()

    prompts = {
        "UNDERSTANDING": "Generate a conceptual question...",
        "APPLICATION": "Generate a practical question...",
    }

    return {
        "authoring_prompt": prompts.get(quiz_type, prompts["APPLICATION"]),
        "quiz_type_used": quiz_type
    }
```

The tool receives context (source fields, seed data, upstream outputs) and the return value replaces the `dispatch_task()` call.

## Capturing Dispatch Results

Enable `add_dispatch` to preserve the dispatch tool's output in the action output:

```yaml
- name: generate_question
  prompt: $quiz_gen.ScenarioGenerator_prompt
  schema: question_schema
  add_dispatch: true
```

## When to Use Dispatch

| Use dispatch when | Use Jinja2 when |
|-------------------|-----------------|
| Complex conditional logic | Simple if/else |
| Schema structure depends on input | Minor text variations |
| Unit-testable Python needed | Template-level logic sufficient |

## See Also

- [Prompt Store](./prompt-store) - Managing reusable prompts
- [Tool Actions](../tools) - Creating custom tools
- [Schema Reference](../schemas/) - Schema definition format
