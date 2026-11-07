---
title: Dynamic Dispatch
sidebar_position: 2
---

# Dynamic Dispatch

The `dispatch_task()` function calls a tool for each record, so a prompt's text, or an action's output schema, can depend on the record.

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

The tool runs once per record and returns that record's schema: a schema definition, or the name of a schema file. It is found as `select_output_schema.py` under the tool path, defining `select_output_schema`. It works in online and batch runs. See [Dynamic Schema Selection](../schemas/#dynamic-schema-selection).

## Creating a Dispatch Tool

```python
import json

from agent_actions import udf_tool


@udf_tool
def handle_quiz_type(input_data: str) -> str:
    """Return appropriate authoring prompt based on quiz type."""
    context = json.loads(input_data)
    quiz_type = context["source"]["quiz_type"].upper()

    prompts = {
        "UNDERSTANDING": "Generate a conceptual question...",
        "APPLICATION": "Generate a practical question...",
    }

    return prompts.get(quiz_type, prompts["APPLICATION"])
```

In a prompt, the tool receives the action's LLM context as a JSON-encoded string: the namespaces and fields the action observes. Decode it with `json.loads()` and read fields from the resulting dict. The return value replaces the `dispatch_task()` call as text (`str()` of the value), so return a string; a dict would appear as its Python repr. A tool that returns `None` fails with `dispatch_task('<name>') returned None. The function must return a value.`

## When to Use Dispatch

| Use dispatch when | Use Jinja2 when |
|-------------------|-----------------|
| Complex conditional logic | Simple if/else |
| Unit-testable Python needed | Template-level logic sufficient |

## See Also

- [Prompt Store](./prompt-store) - Managing reusable prompts
- [Tool Actions](../tools) - Creating custom tools
- [Schema Reference](../schemas/) - Schema definition format
