---
title: Dynamic Dispatch
sidebar_position: 2
---

# Dynamic Dispatch

The `dispatch_task()` function calls a tool for each record. Thus the text of a prompt, or the output schema of an action, can depend on the record.

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
  schema_options: [short_question, long_question]
```

The action lists the schemas that the tool can choose under `schema_options`. The tool runs one time for each record and returns one of those names. Agent Actions finds the tool as `select_output_schema.py` under the tool path. That file defines `select_output_schema`. The tool works in online and batch runs. See [Dynamic Schema Selection](../schemas/#dynamic-schema-selection).

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

In a prompt, the tool receives the LLM context of the action as a JSON-encoded string. The context contains the namespaces and fields that the action observes. Decode the string with `json.loads()`, then read the fields from the resulting dict. The return value replaces the `dispatch_task()` call as text (`str()` of the value). Thus, return a string. A dict would appear as its Python repr. A tool that returns `None` fails with `dispatch_task('<name>') returned None. The function must return a value.`

## When to Use Dispatch

| Use dispatch when | Use Jinja2 when |
|-------------------|-----------------|
| You need complex conditional logic | Simple if/else is sufficient |
| You need Python that you can unit-test | Template-level logic is sufficient |

## See Also

- [Prompt Store](./prompt-store) - Manage reusable prompts
- [Tool Actions](../tools) - Create custom tools
- [Schema Reference](../schemas/) - Schema definition format
