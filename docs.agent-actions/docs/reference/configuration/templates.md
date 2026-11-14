---
title: Workflow Templates
sidebar_position: 4
---

# Workflow Templates {/* #agentic-workflow-templates */}

Agent Actions supports Jinja2 templating in workflow configuration files. Use it when you copy the same action definitions into more than one workflow. Templating permits reusable patterns, macros and dynamic configuration generation.

Templates work like function definitions in programming. You define a pattern one time, then call it wherever you need it. This keeps your workflows DRY (do not repeat yourself), and makes updates easier. When you change the template, all workflows that use it update automatically.

## Overview

Templates give these features:

- **Reusable macros** - Define action groups one time, and use them in more than one workflow
- **Dynamic generation** - Generate workflows programmatically
- **Configuration inheritance** - Extend base configurations
- **Conditional logic** - Include or exclude actions based on parameters

:::note
Templates are rendered before your workflow runs. Thus the load catches template errors early, during configuration loading, not at runtime.
:::

## What Renders When

When Agent Actions loads a workflow, it renders the file through Jinja before it parses the file as YAML. The load decides the `prompt:` of each action at the point where the load reaches it. This applies to each way that the YAML can write the prompt:

- on the line of the key, or on the lines below it
- as a block scalar
- in a flow mapping, for example `- {name: a, prompt: "..."}`

The load uses exactly the names that are bound at that point:

- the names that the file binds with `{% set %}`, `{% for %}`, `{% import %}` or the parameters of a macro
- the macros and variables of `templates/`
- `load_prompt`
- the globals of Jinja, for example `range`

The load then applies these rules:

- A prompt in which all names are bound renders at load.
- A prompt can read a name that a record or a version supplies (`source`, `seed`, an action of the workflow, `version`, `i`, `idx` or a version `param`). Such a prompt is kept whole and renders for each record, exactly as the same prompt in the prompt store does. This includes its own `{% if %}`, `is defined`, captures, macros and `{% raw %}` blocks. An action named by a tag, such as `name: {{ n }}` in a loop or a macro, counts after the file is parsed. If no action has the name, the load fails as for any undefined name. The prompt can have its own `{{ }}` tags outside its `{% %}` blocks that read only load-time names. Those tags render into the prompt at load. For example, with `{% for n in [1, 2] %}`, `Stage {{ n }} of {{ source.text }}` becomes `Stage 2 of {{ source.text }}`. Other tags of the prompt can read load-time data, for example a list that a `{% for %}` walks or a flag that an `{% if %}` tests. That data is set at the top of the prompt (`{% set fields = ["title", "body"] +%}`).
- In both cases, the `{{ load_prompt("...") }}` tag of a prompt inserts the loaded prompt as written, after the file is parsed. Thus a loaded prompt of several lines keeps its line breaks in any YAML style, and needs no indentation. If a filter processes the tag first (`| indent(6)`), the result is pasted into the YAML text like any other output.
- Other values of a versioned action (`model_vendor`, `model_name`, `intent`, …) can read a version variable. Such a value renders one time for each version, as if the variables of the version were set when the file loads. On an action without `versions:`, such a value fails the load, unless the variable is guarded with `is defined` or `default(...)`.

Only data reaches the per-record render. A prompt that renders for each record has limits. It can use a macro, `load_prompt` or an imported template only in its own `{{ }}` tag, outside its `{% %}` blocks. Such a prompt cannot `{% include %}` anything. If it breaks these rules, the load fails and names the prompt. Define the macro inside the prompt instead.

All other content renders at load. A name that nothing defines fails the load (`'enable_validation' is undefined`), unless it is guarded with `is defined` or `default(...)`. The name does not render as nothing. The same rule applies to a field that a loaded name does not have.

A name that a record or a version supplies also fails the load, if the load reads it at any location that the load renders. Thus a record never sees a branch that was decided one time for all records. These are the locations:

- a value other than a prompt
- a `{% set %}` block, a macro body or a `caller()` body that a prompt outputs
- a test with `is defined`

To give a per-record tag to a prompt through a macro or a captured block, wrap the tag in `{% raw %}...{% endraw %}`. The prompt receives the tag as text and renders it for each record.

The top level of each `templates/` file runs one time when the folder loads, to collect its macros and variables. At that time, only the macros and variables of the folder are bound. At the top level, an undefined name renders as nothing.

A `templates/` file can use a macro or a variable of another file without an import. The names of the files do not affect this. The files run in name order, but a file runs before each file that reads a name that it sets. All of the files read the same names:

- A macro can call a macro of any other file.
- A `{% set %}` can read a variable that another file sets.
- A file can append to a list that another file set.
- A file that is included or imported, with or without context, also reads the names of the folder.

Inside a file, its own macros and variables come first. If two files define the same name, the load gives a warning. In all other places, the name is the one from the file that ran later. That file is the one whose name sorts later (`helpers.j2` over `base.j2`), or the one that reads the names of the other file. Two files can each read the variable of the other file at their top level. Then the file that runs first finds the variable of the other file unset.

## Template Location

Templates are in the `templates/` directory:

```
project/
├── agent_actions.yml
├── templates/
│   ├── common_actions.jinja2
│   ├── thinkific_tools.jinja2
│   └── validation_macros.jinja2
└── agent_workflow/
    └── ...
```

## Macro Definition

Define reusable action groups with Jinja2 macros. You can combine these macros into larger workflows:

```jinja2
{# templates/thinkific_tools.jinja2 #}

{% macro thinkific_tools(first_dependency) -%}
- name: format_quiz_object
  kind: tool
  impl: format_quiz_object_with_html
  intent: "Format quiz object with HTML text"
  dependencies: [{{ first_dependency }}]
  schema: formatted_quiz
  context_scope:
    observe: [{{ first_dependency }}.*]

- name: add_asterisk_to_correct_answer
  kind: tool
  impl: add_asterisk_to_correct_answer
  intent: "Add asterisk marker to correct answer option"
  dependencies: [format_quiz_object]
  schema: formatted_quiz
  context_scope:
    observe: [format_quiz_object.*]

- name: convert_html_json_to_thinkific
  kind: tool
  impl: convert_html_json_to_thinkific
  granularity: File
  intent: "Convert HTML JSON format to Thinkific-compatible structure"
  dependencies: [add_asterisk_to_correct_answer]
  schema: thinkific_quiz
  context_scope:
    observe: [add_asterisk_to_correct_answer.*]
{%- endmacro %}
```

Write the macro body from column 0. The `-%}` at the end of the first line removes the indentation that follows it. Thus, if the body is indented inside the macro, its first line starts at column 0 and the other lines stay indented. A tool action needs a `schema`. Each action needs a `context_scope`. An action at `File` granularity needs a `dependencies` entry, because a first action always reads one record at a time.

### Parameterized Macros

Create macros that accept parameters:

```jinja2
{% macro validation_chain(first_dependency, schema_name) -%}
- name: validate_structure
  kind: llm
  intent: "Check the structure of the output"
  dependencies: [{{ first_dependency }}]
  schema: {{ schema_name }}
  prompt: $prompts.validate_structure
  context_scope:
    observe: [{{ first_dependency }}.*]

- name: validate_content
  kind: llm
  intent: "Check the content of the output"
  dependencies: [validate_structure]  # Input source
  schema: {{ schema_name }}_content
  prompt: $prompts.validate_content
  context_scope:
    observe: [validate_structure.*]
{%- endmacro %}
```

## Using Templates in Workflows {/* #using-templates-in-agentic-workflows */}

Import and use macros in workflow files. When you import a macro, you include a predefined set of actions:

```yaml
# agent_config/my_workflow.yml
{% from 'thinkific_tools.jinja2' import thinkific_tools %}

name: my_workflow
description: "Workflow using template macros"

actions:
  - name: prepare_data
    kind: tool
    impl: prepare_data
    intent: "Prepare data for processing"
    schema: prepared_data
    context_scope:
      observe: [source.*]

  # Include macro-defined actions
  {{ thinkific_tools("prepare_data") | indent(2) }}
```

Put two spaces before the call. `indent(2)` indents each line after the first line. The two spaces set the indentation of the first line.

Dependencies come from the `dependencies:` key of each action. A top-level `plan:` block is not part of the schema. The load refuses it.

## Rendered Output

To verify that your templates expanded correctly, examine the rendered workflow. `agac run` renders the templates before execution, and saves the rendered workflow to:

```
artefact/rendered_workflows/my_workflow.yml
```

The saved file also holds the resolved prompts and the compiled schemas. Thus it differs from your file by more than the template tags. Use it to debug the template expansion:

```bash
# View rendered workflow
cat artefact/rendered_workflows/my_workflow.yml

# Compare original vs rendered
diff agent_workflow/my_workflow/agent_config/my_workflow.yml \
     artefact/rendered_workflows/my_workflow.yml
```

## Template Variables

### Built-in Variables

The load supplies no variables of its own. It supplies only `load_prompt`, the macros and variables of `templates/`, and the globals of Jinja (`range`, `dict`, `namespace`, …). Each other name that a tag uses comes from the file itself.

### Custom Variables

Define variables in the workflow:

```yaml
{% set model = "gpt-4o-mini" %}
{% set api_key = "OPENAI_API_KEY" %}

defaults:
  model_vendor: openai
  model_name: {{ model }}
  api_key: {{ api_key }}
```

## Conditional Actions

Include actions on the condition of a variable that the file sets:

```jinja2
{% set enable_validation = true %}

{% if enable_validation %}
  - name: validate_output
    kind: llm
    intent: "Validate the output"
    schema: validation_result
    prompt: $prompts.validate
    context_scope:
      observe: [source.*]
{% endif %}
```

## Loops for Repeated Patterns

Generate more than one action with loops:

```jinja2
{% for stage in [1, 2, 3] %}
  - name: process_stage_{{ stage }}
    kind: llm
    intent: "Process stage {{ stage }}"
    schema: stage_{{ stage }}_output
    prompt: $prompts.process_stage
    {% if stage > 1 %}
    dependencies: [process_stage_{{ stage - 1 }}]
    context_scope:
      observe: [process_stage_{{ stage - 1 }}.*]
    {% else %}
    context_scope:
      observe: [source.*]
    {% endif %}
{% endfor %}
```

## Debugging Templates

To see the rendered output, use `agac run`. It saves the rendered workflow under `artefact/rendered_workflows/`, and writes the compiled prompts into the `prompt_trace` table.

If the rendered text is not valid YAML, the framework saves it to `.agent-actions/cache/rendered_workflows/<workflow>_failed.yml`. The error shows the line and the column of the failure in the rendered text, with the lines around it. The saved file has the same line numbers. The error does not print the saved path. A Jinja error, for example an undefined name, is reported without a saved file.

For deeper debugging, use `agac inspect context -a my_workflow <action_name>`. It shows the data namespaces and variables that are available to the template of a specific action.

## Best Practices

These patterns make templates easier to maintain.

### 1. Keep Macros Focused

```jinja2
{# Good: Single responsibility #}
{% macro extraction_actions() %}...{% endmacro %}
{% macro validation_actions() %}...{% endmacro %}

{# Avoid: Monolithic macros #}
{% macro entire_workflow() %}...{% endmacro %}
```

### 2. Use Descriptive Names

```jinja2
{# Good #}
{% macro quiz_generation_chain(source_action) %}

{# Avoid #}
{% macro m1(s) %}
```

### 3. Document Parameters

```jinja2
{#
  Create a validation chain for the given source.

  Args:
    source_action: Name of the upstream action to validate
    schema_name: Base schema name for validation

  Returns:
    Two validation actions: validate_structure, validate_content
#}
{% macro validation_chain(source_action, schema_name) %}
```

### 4. Test Rendered Output

Always verify the template expansion before you run the workflow:

```bash
# Render and validate; a rendering failure exits non-zero.
agac inspect -a my_workflow
```

### 5. Use Whitespace Control

Jinja2 whitespace control prevents extra newlines:

```jinja2
{# Without control: extra blank lines #}
{% macro actions() %}
  - name: action1
{% endmacro %}

{# With control: clean output #}
{%- macro actions() -%}
  - name: action1
{%- endmacro -%}
```

## Common Patterns

These patterns occur frequently when you build workflows with templates.

### Base Configuration Extension

```jinja2
{# templates/base.jinja2 #}
{% macro base_defaults() %}
defaults:
  json_mode: true
  granularity: record
  run_mode: online
  model_vendor: openai
  model_name: gpt-4o-mini
  api_key: OPENAI_API_KEY
{% endmacro %}
```

```yaml
{# Agentic workflow using base #}
{% from 'base.jinja2' import base_defaults %}

name: my_workflow
description: "Workflow built on shared defaults"
{{ base_defaults() }}

actions:
  - name: my_action
    intent: "Uses the base defaults"
    prompt: $prompts.my_action
    schema: my_action_output
    context_scope:
      observe: [source.*]
```

### Feature Flags

Feature flags let you enable or disable parts of your workflow. This is useful for A/B testing, or to release new actions gradually:

```jinja2
{% set features = {
  'enable_caching': true,
  'enable_validation': true,
  'enable_monitoring': false
} %}

{% if features.enable_validation %}
  - name: validate_output
    ...
{% endif %}
```

:::warning[CAUTION]
Templates add a layer of indirection. When you debug a workflow problem, always examine the rendered output in `artefact/rendered_workflows/`. It shows the configuration that actually ran.
:::
