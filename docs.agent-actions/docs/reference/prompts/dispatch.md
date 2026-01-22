---
title: Dynamic Dispatch
sidebar_position: 2
---

# Dynamic Dispatch

What if your agentic workflow needs to choose different prompts or schemas based on runtime data? For example, a quiz generator might need different authoring instructions depending on whether the question tests "understanding" vs "implementation" knowledge.

The `dispatch_task()` function solves this by calling Python UDFs at template render time, allowing data-driven selection of prompts, schemas, or any configuration value.

## How It Works

When Agent Actions renders a prompt or schema, it scans for `dispatch_task('function_name')` calls and replaces them with the return value from that UDF. The UDF receives the current context (source data, seed data, upstream outputs) and can return any value - strings, dictionaries, or complete schema definitions.

```
Template with dispatch_task() → UDF executes → Return value replaces call
```

## Basic Usage

### In Prompts

Use `dispatch_task()` anywhere in a prompt to inject dynamic content:

```markdown
{prompt ScenarioGenerator_prompt}
dispatch_task('handle_quiz_type')
{end_prompt}
```

When this prompt renders, Agent Actions:
1. Calls the `handle_quiz_type` UDF
2. Passes current context (source fields, seed data, upstream outputs)
3. Replaces `dispatch_task('handle_quiz_type')` with the returned string

### In Schemas

Dynamic schema selection works the same way. Instead of hardcoding a schema, let a UDF return the appropriate schema based on context:

```yaml
- name: generate_question
  prompt: $quiz_gen.ScenarioGenerator_prompt
  schema: dispatch_task('select_output_schema')
```

The UDF can return a complete schema definition:

```python
@udf_tool
def select_output_schema(input_data: dict) -> dict:
    quiz_type = input_data.get("quiz_type", "").upper()

    if quiz_type == "MULTIPLE_CHOICE":
        return {
            "name": "mc_question",
            "fields": [
                {"id": "question", "type": "string", "required": True},
                {"id": "options", "type": "array", "required": True},
                {"id": "answer", "type": "string", "required": True}
            ]
        }
    else:
        return {
            "name": "open_question",
            "fields": [
                {"id": "question", "type": "string", "required": True},
                {"id": "model_answer", "type": "string", "required": True}
            ]
        }
```

## Creating a Dispatch UDF

Dispatch UDFs follow the same pattern as other UDFs, decorated with `@udf_tool`:

```python
from typing import Any, TypedDict
from agent_actions import udf_tool


class DispatchInput(TypedDict, total=False):
    quiz_type: str
    difficulty: str
    # Any fields from source, seed, or upstream actions


class DispatchOutput(TypedDict):
    authoring_prompt: str
    quiz_type_used: str


@udf_tool(input_type=DispatchInput, output_type=DispatchOutput)
def handle_quiz_type(input_data: Any) -> dict:
    """Return appropriate authoring prompt based on quiz type."""

    # Normalize input (may come as string or dict)
    if isinstance(input_data, str):
        import json
        try:
            input_data = json.loads(input_data)
        except json.JSONDecodeError:
            input_data = {}

    quiz_type = str(input_data.get("quiz_type", "")).upper()

    prompts = {
        "UNDERSTANDING": "Generate a conceptual question testing comprehension...",
        "APPLICATION": "Generate a practical question testing configuration...",
        "IMPLEMENTATION": "Generate a question testing command/parameter selection...",
        "ANALYSIS": "Generate a diagnostic question testing root cause identification..."
    }

    selected_prompt = prompts.get(quiz_type, prompts["APPLICATION"])

    return {
        "authoring_prompt": selected_prompt,
        "quiz_type_used": quiz_type or "APPLICATION"
    }
```

### Key Points

1. **Input is JSON-serialized context** - The UDF receives all available context as a JSON string or dict
2. **Return value replaces the call** - Whatever you return becomes the prompt/schema content
3. **Type preservation** - When `dispatch_task()` is the entire value (not embedded in text), the return type is preserved (dict stays dict)

## Context Available to Dispatch UDFs

The dispatch UDF receives the current record's context, including:

| Context | Description | Example Access |
|---------|-------------|----------------|
| Source fields | Current input record | `input_data.get("page_content")` |
| Seed data | Configuration from seed files | `input_data.get("exam_syllabus")` |
| Upstream outputs | Results from previous actions | `input_data.get("extract_facts")` |

This enables decisions based on any data flowing through the agentic workflow.

## Real-World Example

Consider a quiz generator that produces different question types. The `quiz_type` field from an earlier classification action determines which authoring prompt to use:

### 1. Classifier Action (upstream)

```yaml
- name: classify_content
  prompt: |
    Classify this content for quiz generation.
    Content: {{ source.content }}

    Return: {"quiz_type": "UNDERSTANDING|APPLICATION|IMPLEMENTATION|ANALYSIS"}
  schema: classification_schema
```

### 2. Prompt Store with Dispatch

```markdown
{prompt ScenarioGenerator_prompt}
dispatch_task('handle_quiz_type')
{end_prompt}
```

### 3. Dispatch UDF

```python
@udf_tool
def handle_quiz_type(input_data: Any) -> dict:
    quiz_type = input_data.get("quiz_type", "APPLICATION")

    # Different prompts for different question types
    if quiz_type == "UNDERSTANDING":
        return {
            "authoring_prompt": """
            Generate a conceptual question testing definition/purpose comprehension.

            SCENARIO: Present a situation requiring concept understanding.
            QUESTION: "Which service should you use?" or "What is the purpose of X?"
            OPTIONS: 4 options, each 15-30 words with specific terminology.
            """
        }
    elif quiz_type == "ANALYSIS":
        return {
            "authoring_prompt": """
            Generate a diagnostic question testing root cause identification.

            SCENARIO: Include specific symptoms (error messages, metrics, timelines).
            QUESTION: "What is the most likely cause?" or "How should you resolve this?"
            OPTIONS: 4 options with diagnostic reasoning.
            """
        }
    # ... other types
```

### 4. Generator Action

```yaml
- name: generate_question
  dependencies: classify_content  # Input source
  prompt: $quiz_gen.ScenarioGenerator_prompt
  schema: question_schema
```

The prompt content changes based on `classify_content.quiz_type` - all without modifying the YAML configuration.

## Capturing Dispatch Results

Sometimes you want to preserve the dispatch UDF's output alongside the LLM response. Enable `add_dispatch` to capture results:

```yaml
- name: generate_question
  prompt: $quiz_gen.ScenarioGenerator_prompt
  schema: question_schema
  add_dispatch: true
```

With `add_dispatch: true`, the UDF's return value is saved in the action's output under the function name:

```json
{
  "question": "What service provides...",
  "options": ["..."],
  "handle_quiz_type": {
    "authoring_prompt": "Generate a conceptual question...",
    "quiz_type_used": "UNDERSTANDING"
  }
}
```

This is useful for debugging or when downstream actions need to know which dispatch path was taken.

## Directory Structure

Dispatch UDFs live in your tools directory alongside other UDFs:

```
project/
├── agent_actions.yml
├── prompt_store/
│   └── quiz_gen.md           # Contains dispatch_task() calls
├── tools/
│   └── my-project/
│       ├── handle_quiz_type.py    # Dispatch UDF
│       └── other_tools.py
└── agent_workflow/
    └── quiz_workflow.yml
```

## When to Use Dispatch

**Use dispatch when:**
- Prompt content varies based on runtime data
- Schema structure depends on input characteristics
- You need conditional logic too complex for Jinja2
- Business rules drive prompt/schema selection

**Prefer static prompts when:**
- All records use the same prompt structure
- Jinja2 templating handles the variation adequately
- Simpler configuration is more maintainable

## Comparison with Jinja2 Conditionals

Both approaches handle dynamic content, but serve different purposes:

| Feature | Jinja2 Conditionals | dispatch_task() |
|---------|---------------------|-----------------|
| Complexity | Simple if/else | Arbitrary Python logic |
| Testability | Template testing | Unit testable Python |
| Reusability | Template-bound | Function reusable across prompts |
| Return types | Strings only | Any type (dict, list, schema) |
| Best for | Minor variations | Major structural changes |

### Jinja2 Example

```markdown
{% if source.content_type == "technical" %}
Apply strict accuracy checks.
{% else %}
Apply readability checks.
{% endif %}
```

### Dispatch Example

```python
@udf_tool
def select_validation_rules(input_data):
    content_type = input_data.get("content_type")
    word_count = len(input_data.get("content", "").split())
    has_code = "```" in input_data.get("content", "")

    # Complex logic not suited for Jinja2
    if content_type == "technical" and has_code:
        return detailed_code_review_prompt()
    elif content_type == "technical":
        return technical_accuracy_prompt()
    elif word_count > 1000:
        return long_form_review_prompt()
    else:
        return standard_review_prompt()
```

## Error Handling

### UDF Not Found

```
ConfigurationError: dispatch_task function 'unknown_function' not found
```

Ensure:
1. UDF file is in the tools directory
2. Function is decorated with `@udf_tool`
3. Tools path is correctly configured (`-u` flag or config)

### Invalid Return Value

```
AgentActionsException: An unexpected error occurred in function 'my_dispatch': ...
```

Check that your UDF:
1. Handles all input cases (including malformed data)
2. Returns the expected type (string for prompts, dict for schemas)
3. Doesn't raise unhandled exceptions

## See Also

- [Prompt Store](./prompt-store) - Managing reusable prompts
- [UDF Decorator Reference](../tools/udf-decorator) - Creating user-defined functions
- [Schema Reference](../schemas/) - Schema definition format
