# Workflow Template Macros

This document explains the Jinja2 macros available in `question_workflow.jinja2` for building quiz generation workflows.

## Table of Contents

1. [Overview](#overview)
2. [LLM-Based Workflow Macros](#llm-based-workflow-macros)
3. [Tool-Based Workflow Macros](#tool-based-workflow-macros)
4. [Multi-Tool Pipeline Macros](#multi-tool-pipeline-macros)
5. [Common Patterns](#common-patterns)
6. [Complete Examples](#complete-examples)

---

## Overview

The `question_workflow.jinja2` template provides reusable Jinja2 macros for generating workflow YAML configurations. These macros help you:

- **Reduce repetition**: Define common patterns once, reuse everywhere
- **Ensure consistency**: Generated workflows follow the same structure
- **Compose workflows**: Build complex workflows from smaller, reusable components
- **Parameterize configurations**: Change behavior through parameters without duplicating code

### Basic Usage Pattern

```jinja2
{% from 'question_workflow.jinja2' import macro_name %}

{{ macro_name(
    param1='value1',
    param2='value2'
) }}
```

---

## LLM-Based Workflow Macros

### `quiz_workflow`

Generates a single LLM-based agent action with schema validation and JSON mode support.

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `agent_type` | string | *required* | Name of the agent/action |
| `model_vendor` | string | *required* | LLM provider (e.g., "openai", "anthropic") |
| `model_name` | string | *required* | Model identifier (e.g., "gpt-4", "claude-sonnet-4") |
| `dependencies` | list | *required* | List of action names this depends on |
| `api_key` | string | *required* | Environment variable name for API key |
| `schema_name` | string | *required* | Schema name for validation (if `schema` not provided) |
| `prompt` | string | *required* | Prompt template path (e.g., "$namespace.prompt_name") |
| `few_shot` | int | 0 | Number of few-shot examples |
| `prompt_debug` | bool | False | Enable prompt debugging |
| `is_operational` | bool | True | Whether action is active |
| `side_collection` | list | [] | Additional collections to include |
| `json_mode` | bool | True | Enable JSON mode for LLM |
| `granularity` | string | "Record" | Processing granularity ("Record" or "File") |
| `run_mode` | string | "online" | Execution mode |
| `tokenizer_model` | string | "o200k_base" | Tokenizer to use |
| `split_method` | string | "tiktoken" | Text splitting method |
| `remove_collection` | list | [] | Collections to remove |
| `schema` | dict | None | Inline schema (overrides `schema_name`) |
| `where_clause` | string/dict | None | Filter clause for data |

**Example:**

```jinja2
{% from 'question_workflow.jinja2' import quiz_workflow %}

actions:
{{ quiz_workflow(
    agent_type='fact_extractor',
    model_vendor='openai',
    model_name='gpt-4',
    dependencies=[],
    api_key='OPENAI_API_KEY',
    schema_name='candidate_facts_list',
    prompt='$qanalabs-quiz-gen.Fact_extraction',
    few_shot=3,
    granularity='Record'
) }}
```

**Generates:**

```yaml
    agent_type: fact_extractor
    dependencies: []
    api_key: OPENAI_API_KEY
    model_vendor: openai
    model_name: gpt-4
    schema_name: candidate_facts_list
    few_shot: 3
    is_operational: true
    side_collection: []
    json_mode: true
    run_mode: online
    granularity: Record
    remove_collection: []
    where_clause:
      clause: >-
        some_field == "value"
      scope: item
    prompt: $qanalabs-quiz-gen.Fact_extraction
    tokenizer_model: o200k_base
    split_method: tiktoken
    prompt_debug: false
```

---

### `quiz_workflow_loop`

Generates multiple sequential LLM actions where each depends on the previous one.

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `prompts` | list | *required* | List of prompt paths (agent names derived from last segment) |
| *(other params)* | - | - | Same as `quiz_workflow` |

**Example:**

```jinja2
{% from 'question_workflow.jinja2' import quiz_workflow_loop %}

{% set alignment_prompts = [
    "$alignment.alignment_with_key_ideas",
    "$alignment.depth_of_understanding",
    "$alignment.relevance_and_appropriateness"
] %}

actions:
{{ quiz_workflow_loop(
    agent_type='alignment',
    model_vendor='openai',
    model_name='gpt-4',
    dependencies=[],
    api_key='OPENAI_API_KEY',
    prompts=alignment_prompts,
    schema_name='validation_schema'
) }}
```

**Generates:**

```yaml
actions:
    agent_type: alignment_with_key_ideas
    dependencies: []
    # ... other config ...
    prompt: $alignment.alignment_with_key_ideas

    agent_type: depth_of_understanding
    dependencies: [alignment_with_key_ideas]
    # ... other config ...
    prompt: $alignment.depth_of_understanding

    agent_type: relevance_and_appropriateness
    dependencies: [depth_of_understanding]
    # ... other config ...
    prompt: $alignment.relevance_and_appropriateness
```

---

## Tool-Based Workflow Macros

### `tooling_workflow`

Generates a single tool-based action (non-LLM processing like data transformation, validation, etc.).

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `agent_type` | string | *required* | Name of the action |
| `model_name` | string | *required* | Tool implementation function name |
| `dependencies` | list | *required* | List of action names this depends on |
| `description` | string | *required* | Human-readable description of what the tool does |
| `model_vendor` | string | "tool" | Always "tool" for tool-based actions |
| `is_operational` | bool | True | Whether action is active |
| `granularity` | string | "Record" | Processing granularity |
| `side_collection` | list | [] | Additional collections to include |
| `remove_collection` | list | [] | Collections to remove |
| `where_clause` | string/dict | None | Filter clause for data |

**Example:**

```jinja2
{% from 'question_workflow.jinja2' import tooling_workflow %}

actions:
  - name: cluster_list
    kind: tool
{{ tooling_workflow(
    agent_type='cluster_list',
    model_name='cluster_list',
    dependencies=['fact_extractor'],
    description='Group extracted facts into logical clusters',
    granularity='Record'
) }}
```

**Generates:**

```yaml
  - name: cluster_list
    kind: tool
    agent_type: cluster_list
    dependencies: ['fact_extractor']
    model_vendor: tool
    model_name: cluster_list
    is_operational: true
    granularity: Record
    side_collection: []
    description: 'Group extracted facts into logical clusters'
```

---

### `file_tooling_workflow`

Specialized version of `tooling_workflow` for file-level operations.

**Parameters:**

Same as `tooling_workflow` with `granularity` typically set to "File".

**Example:**

```jinja2
{% from 'question_workflow.jinja2' import file_tooling_workflow %}

actions:
{{ file_tooling_workflow(
    agent_type='combine_by_cluster',
    model_name='combine_records_to_items',
    dependencies=['cluster_list'],
    description='Combine records by cluster and ID for processing',
    granularity='File'
) }}
```

---

### `conditional_tooling_workflow`

Tool workflow with a conditional execution clause.

**Parameters:**

All `tooling_workflow` parameters plus:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `conditional_clause` | string | *required* | Condition expression (e.g., "needs_split == true") |

**Example:**

```jinja2
{% from 'question_workflow.jinja2' import conditional_tooling_workflow %}

actions:
{{ conditional_tooling_workflow(
    agent_type='create_new_clusters',
    model_name='create_new_clusters',
    dependencies=['validate_clusters'],
    description='Create new clusters when validation indicates need for splitting',
    conditional_clause='should_keep_cluster == false'
) }}
```

---

## Multi-Tool Pipeline Macros

### `multi_tool_workflow`

Generates a complete standalone workflow with multiple tools in a dependency chain.

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `workflow_name` | string | *required* | Name of the workflow |
| `description` | string | "Multi-step tool pipeline" | Workflow description |
| `version` | string | "1.0.0" | Workflow version |
| `observe` | list | [] | Global fields to observe across all actions |
| `tools` | list | [] | List of tool configurations (see below) |

**Tool Configuration Object:**

```python
{
    'name': 'tool_action_name',           # Required: action name
    'impl': 'function_name',              # Required: implementation function
    'intent': 'What this tool does',      # Required: description
    'granularity': 'Record',              # Optional: Record or File
    'depends_on': 'previous_action_name', # Optional: dependency
    'guard': 'condition_expression'       # Optional: guard condition
}
```

**Example:**

```jinja2
{% from 'question_workflow.jinja2' import multi_tool_workflow %}

{{ multi_tool_workflow(
    workflow_name='run_thinkific_gen',
    description='Convert quiz objects to Thinkific-compatible format with HTML formatting',
    version='2.0.0',
    observe=['question_type', 'batch_name'],
    tools=[
        {
            'name': 'format_quiz_object',
            'impl': 'format_quiz_object_with_html',
            'intent': 'Format quiz object with HTML text'
        },
        {
            'name': 'add_asterisk_to_correct_answer',
            'impl': 'add_asterisk_to_correct_answer',
            'intent': 'Add asterisk marker to correct answer option',
            'depends_on': 'format_quiz_object'
        },
        {
            'name': 'convert_html_json_to_thinkific',
            'impl': 'convert_html_json_to_thinkific',
            'granularity': 'File',
            'intent': 'Convert HTML JSON format to Thinkific-compatible structure',
            'depends_on': 'add_asterisk_to_correct_answer'
        }
    ]
) }}
```

**Generates:**

```yaml
name: run_thinkific_gen
description: "Convert quiz objects to Thinkific-compatible format with HTML formatting"
version: "2.0.0"

defaults:
  granularity: Record
  observe: ['question_type', 'batch_name']

actions:
  - name: format_quiz_object
    kind: tool
    impl: format_quiz_object_with_html
    intent: "Format quiz object with HTML text"
  - name: add_asterisk_to_correct_answer
    kind: tool
    impl: add_asterisk_to_correct_answer
    intent: "Add asterisk marker to correct answer option"
  - name: convert_html_json_to_thinkific
    kind: tool
    impl: convert_html_json_to_thinkific
    granularity: File
    intent: "Convert HTML JSON format to Thinkific-compatible structure"

plan:
  - format_quiz_object
  - add_asterisk_to_correct_answer <- format_quiz_object
  - convert_html_json_to_thinkific <- add_asterisk_to_correct_answer
```

---

### `tool_pipeline`

Generates only the **actions** section for a tool pipeline (no plan). Useful for inlining tools into existing workflows.

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `tools` | list | [] | List of tool configurations |
| `first_dependency` | string | None | Not used (reserved for future) |

**Example:**

```jinja2
{% from 'question_workflow.jinja2' import tool_pipeline %}

{% set thinkific_tools = [
    {
        'name': 'format_quiz_object_html',
        'impl': 'format_quiz_object_with_html',
        'intent': 'Format quiz object with HTML text',
        'guard': 'questionable != "Low Value"'
    },
    {
        'name': 'add_asterisk',
        'impl': 'add_asterisk_to_correct_answer',
        'intent': 'Add asterisk marker',
        'guard': 'questionable != "Low Value"'
    }
] %}

actions:
  # ... existing actions ...

{{ tool_pipeline(tools=thinkific_tools) }}
```

**Generates:**

```yaml
actions:
  # ... existing actions ...

  - name: format_quiz_object_html
    kind: tool
    impl: format_quiz_object_with_html
    guard: 'questionable != "Low Value"'
    intent: "Format quiz object with HTML text"

  - name: add_asterisk
    kind: tool
    impl: add_asterisk_to_correct_answer
    guard: 'questionable != "Low Value"'
    intent: "Add asterisk marker"
```

---

### `tool_plan`

Generates only the **plan** section for a tool pipeline. Useful for inlining tool dependencies into existing workflows.

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `tools` | list | [] | List of tool configurations (same as `tool_pipeline`) |
| `first_dependency` | string | None | Action name that the first tool depends on |

**Example:**

```jinja2
{% from 'question_workflow.jinja2' import tool_plan %}

{% set thinkific_tools = [
    {
        'name': 'format_quiz_object_html',
        'impl': 'format_quiz_object_with_html',
        'intent': 'Format with HTML'
    },
    {
        'name': 'add_asterisk',
        'impl': 'add_asterisk_to_correct_answer',
        'intent': 'Add asterisk',
        'depends_on': 'format_quiz_object_html'
    },
    {
        'name': 'convert_to_thinkific',
        'impl': 'convert_html_json_to_thinkific',
        'intent': 'Convert to Thinkific',
        'depends_on': 'add_asterisk'
    }
] %}

plan:
  # ... existing plan steps ...
  - format_quiz_text <- OptionsCombiner

{{ tool_plan(tools=thinkific_tools, first_dependency='format_quiz_text') }}
```

**Generates:**

```yaml
plan:
  # ... existing plan steps ...
  - format_quiz_text <- OptionsCombiner

  - format_quiz_object_html <- format_quiz_text
  - add_asterisk <- format_quiz_object_html
  - convert_to_thinkific <- add_asterisk
```

---

## Common Patterns

### Pattern 1: Standalone Workflow

Create a complete workflow in a separate `.yml.jinja2` file:

```jinja2
{% from 'question_workflow.jinja2' import multi_tool_workflow %}

{{ multi_tool_workflow(
    workflow_name='my_workflow',
    description='My tool pipeline',
    tools=[...]
) }}
```

Then render it to YAML:

```bash
python3 -c "
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader(['path/to/templates']))
template = env.get_template('my_workflow.yml.jinja2')
print(template.render())
" > my_workflow.yml
```

---

### Pattern 2: Inline Tool Pipeline

Add a reusable tool pipeline into an existing workflow:

```jinja2
{% from 'question_workflow.jinja2' import tool_pipeline, tool_plan %}

{% set my_tools = [
    {'name': 'step1', 'impl': 'func1', 'intent': 'Do step 1'},
    {'name': 'step2', 'impl': 'func2', 'intent': 'Do step 2', 'depends_on': 'step1'}
] %}

name: main_workflow
description: "Main workflow with embedded pipeline"

actions:
  - name: existing_action
    kind: tool
    impl: existing_func
    intent: "Existing action"

  # Inline the tool pipeline
{{ tool_pipeline(tools=my_tools) }}

plan:
  - existing_action

  # Inline the plan steps
{{ tool_plan(tools=my_tools, first_dependency='existing_action') }}
```

---

### Pattern 3: Sequential LLM Processing

Chain multiple LLM prompts where each builds on the previous:

```jinja2
{% from 'question_workflow.jinja2' import quiz_workflow_loop %}

{% set validation_prompts = [
    "$validation.check_accuracy",
    "$validation.check_completeness",
    "$validation.final_review"
] %}

actions:
{{ quiz_workflow_loop(
    agent_type='validation',
    model_vendor='openai',
    model_name='gpt-4',
    dependencies=['generate_content'],
    api_key='OPENAI_API_KEY',
    prompts=validation_prompts,
    schema_name='validation_schema'
) }}
```

---

### Pattern 4: Conditional Tool Execution

Execute tools only when certain conditions are met:

```jinja2
{% from 'question_workflow.jinja2' import tooling_workflow %}

actions:
  - name: validate_quality
    kind: tool
{{ tooling_workflow(
    agent_type='validate_quality',
    model_name='quality_validator',
    dependencies=['generate_quiz'],
    description='Validate quiz quality',
    where_clause={
        'clause': 'score > 0.7',
        'scope': 'item'
    }
) }}
```

---

## Complete Examples

### Example 1: Simple Quiz Generation Workflow

```jinja2
{% from 'question_workflow.jinja2' import quiz_workflow, tooling_workflow %}

name: simple_quiz_gen
version: "1.0.0"

defaults:
  model_vendor: openai
  model_name: gpt-4
  api_key: OPENAI_API_KEY
  granularity: Record

actions:
  - name: extract_facts
{{ quiz_workflow(
    agent_type='extract_facts',
    model_vendor='openai',
    model_name='gpt-4',
    dependencies=[],
    api_key='OPENAI_API_KEY',
    schema_name='facts_schema',
    prompt='$quiz.extract_facts'
) }}

  - name: cluster_facts
    kind: tool
{{ tooling_workflow(
    agent_type='cluster_facts',
    model_name='cluster_list',
    dependencies=['extract_facts'],
    description='Cluster related facts together'
) }}

  - name: generate_questions
{{ quiz_workflow(
    agent_type='generate_questions',
    model_vendor='openai',
    model_name='gpt-4',
    dependencies=['cluster_facts'],
    api_key='OPENAI_API_KEY',
    schema_name='question_schema',
    prompt='$quiz.generate_questions'
) }}

plan:
  - extract_facts
  - cluster_facts <- extract_facts
  - generate_questions <- cluster_facts
```

---

### Example 2: Complex Workflow with Embedded Pipeline

```jinja2
{% from 'question_workflow.jinja2' import quiz_workflow, tool_pipeline, tool_plan %}

{% set formatting_tools = [
    {
        'name': 'add_html_formatting',
        'impl': 'format_with_html',
        'intent': 'Add HTML formatting to questions'
    },
    {
        'name': 'validate_html',
        'impl': 'validate_html_structure',
        'intent': 'Validate HTML structure',
        'depends_on': 'add_html_formatting'
    },
    {
        'name': 'export_to_platform',
        'impl': 'export_questions',
        'granularity': 'File',
        'intent': 'Export to learning platform',
        'depends_on': 'validate_html'
    }
] %}

name: quiz_with_export
version: "2.0.0"

defaults:
  model_vendor: openai
  api_key: OPENAI_API_KEY
  granularity: Record

actions:
  - name: generate_quiz
{{ quiz_workflow(
    agent_type='generate_quiz',
    model_vendor='openai',
    model_name='gpt-4',
    dependencies=[],
    api_key='OPENAI_API_KEY',
    schema_name='quiz_schema',
    prompt='$quiz.generate'
) }}

  # Embed the formatting pipeline
{{ tool_pipeline(tools=formatting_tools) }}

plan:
  - generate_quiz

  # Connect the pipeline to the main workflow
{{ tool_plan(tools=formatting_tools, first_dependency='generate_quiz') }}
```

---

### Example 3: Using Variables for DRY Configuration

```jinja2
{% from 'question_workflow.jinja2' import quiz_workflow %}

{% set common_config = {
    'model_vendor': 'openai',
    'model_name': 'gpt-4',
    'api_key': 'OPENAI_API_KEY',
    'few_shot': 3,
    'granularity': 'Record'
} %}

name: dry_workflow
version: "1.0.0"

actions:
  - name: step1
{{ quiz_workflow(
    agent_type='step1',
    dependencies=[],
    schema_name='schema1',
    prompt='$workflow.step1',
    **common_config
) }}

  - name: step2
{{ quiz_workflow(
    agent_type='step2',
    dependencies=['step1'],
    schema_name='schema2',
    prompt='$workflow.step2',
    **common_config
) }}

plan:
  - step1
  - step2 <- step1
```

---

## Tips and Best Practices

1. **Define tool configurations as variables**: Store complex tool lists in Jinja variables for reusability
2. **Use `tool_pipeline` + `tool_plan` together**: For embedding tool chains into larger workflows
3. **Use `multi_tool_workflow`**: For standalone, self-contained tool pipelines
4. **Keep defaults in workflow YAML**: Use macro parameters for action-specific overrides only
5. **Use meaningful action names**: They become node IDs in the execution plan
6. **Document your macros**: Add comments explaining what each macro call does
7. **Version your workflows**: Always include a version string for tracking changes
8. **Test rendered output**: Always render and validate the YAML before deploying

---

## Rendering Jinja Templates

### Method 1: Python Script

```python
from jinja2 import Environment, FileSystemLoader

env = Environment(loader=FileSystemLoader(['path/to/templates']))
template = env.get_template('my_workflow.yml.jinja2')
output = template.render()
print(output)
```

### Method 2: Command Line

```bash
python3 -c "
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader(['templates']))
template = env.get_template('workflow.yml.jinja2')
print(template.render())
" > output.yml
```

### Method 3: Using a Build Script

Create a `build_workflows.py`:

```python
from jinja2 import Environment, FileSystemLoader
import os

def build_workflow(template_name, output_name):
    env = Environment(loader=FileSystemLoader(['qanalabs/templates']))
    template = env.get_template(template_name)
    output = template.render()

    with open(output_name, 'w') as f:
        f.write(output)
    print(f"Generated: {output_name}")

if __name__ == "__main__":
    build_workflow('my_workflow.yml.jinja2', 'output/my_workflow.yml')
```

---

## Troubleshooting

**Issue**: `TemplateNotFound` error

**Solution**: Ensure your `FileSystemLoader` paths include both the templates directory and any subdirectories where templates are located:

```python
env = Environment(loader=FileSystemLoader([
    'qanalabs/templates',
    'qanalabs/agent_workflow/my_workflow/agent_config'
]))
```

**Issue**: Generated YAML has incorrect indentation

**Solution**: Check that your macro doesn't have extra whitespace. Use `{%-` and `-%}` to strip whitespace:

```jinja2
{%- for tool in tools -%}
  - name: {{ tool.name }}
{%- endfor -%}
```

**Issue**: Variables not available in macro

**Solution**: Pass variables as macro parameters or use Jinja's `set` outside the macro call:

```jinja2
{% set my_var = 'value' %}
{{ my_macro(param=my_var) }}
```

---

## Additional Resources

- [Jinja2 Documentation](https://jinja.palletsprojects.com/)
- [YAML Specification](https://yaml.org/spec/)
- Workflow schema documentation (internal)

---

## Contributing

When adding new macros to `question_workflow.jinja2`:

1. Add the macro implementation
2. Document it in this README with:
   - Parameter table
   - Example usage
   - Generated output example
3. Add it to the Table of Contents
4. Include it in a complete example if applicable
5. Test the rendered output











#-------------------------------------------------
 Example usage in qanalabs-quiz-gen.yml.jinja2:

  {% from 'question_workflow.jinja2' import quiz_workflow, tooling_workflow, tool_pipeline, tool_plan %}
  {% set thinkific_tools = [
      {
          'name': 'format_quiz_object_html',
          'impl': 'format_quiz_object_with_html',
          'intent': 'Format quiz object with HTML text',
          'guard': 'questionable != "Low Value"'
      },
      {
          'name': 'add_asterisk_to_correct_answer',
          'impl': 'add_asterisk_to_correct_answer',
          'intent': 'Add asterisk marker to correct answer option',
          'depends_on': 'format_quiz_object_html',
          'guard': 'questionable != "Low Value"'
      },
      {
          'name': 'convert_html_json_to_thinkific',
          'impl': 'convert_html_json_to_thinkific',
          'granularity': 'File',
          'intent': 'Convert HTML JSON format to Thinkific-compatible structure',
          'depends_on': 'add_asterisk_to_correct_answer'
      }
  ] %}

  name: qanalabs-quiz-gen
  description: "Educational quiz generation workflow"
  version: "2.0.0"

  defaults:
    # ... your defaults ...

  actions:
    # ... your existing actions ...

    - name: format_quiz_text
      kind: tool
      impl: format_quiz_object
      intent: "Format the quiz"
      granularity: Record
      guard: 'questionable != "Low Value"'

    # Inline the thinkific tools
  {{ tool_pipeline(tools=thinkific_tools) }}

  plan:
    # ... your existing plan steps ...
    - format_quiz_text <- OptionsCombiner
    # Inline the thinkific plan with first dependency
  {{ tool_plan(tools=thinkific_tools, first_dependency='format_quiz_text') }}

  This will render to:

  actions:
    # ... existing actions ...

    - name: format_quiz_object_html
      kind: tool
      impl: format_quiz_object_with_html
      granularity: Record
      guard: 'questionable != "Low Value"'
      intent: "Format quiz object with HTML text"

    - name: add_asterisk_to_correct_answer
      kind: tool
      impl: add_asterisk_to_correct_answer
      granularity: Record
      guard: 'questionable != "Low Value"'
      intent: "Add asterisk marker to correct answer option"

    - name: convert_html_json_to_thinkific
      kind: tool
      impl: convert_html_json_to_thinkific
      granularity: File
      intent: "Convert HTML JSON format to Thinkific-compatible structure"

  plan:
    # ... existing plan ...
    - format_quiz_text <- OptionsCombiner
    - format_quiz_object_html <- format_quiz_text
    - add_asterisk_to_correct_answer <- format_quiz_object_html
    - convert_html_json_to_thinkific <- add_asterisk_to_correct_answer

  The key benefits:
  1. tool_pipeline: Generates just the actions (no plan)
  2. tool_plan: Generates just the plan steps
  3. first_dependency: Connects the first tool in the pipeline to your existing workflow
  4. Reusable: Define the thinkific tools once as a variable, use in multiple places

  This way you can compose workflows from reusable pipeline components using Jinja macros!