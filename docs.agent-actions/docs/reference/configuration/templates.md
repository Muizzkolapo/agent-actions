---
title: Agentic Workflow Templates
sidebar_position: 4
---

# Agentic Workflow Templates

What happens when you find yourself copying the same action definitions across multiple agentic workflows? Agent Actions supports Jinja2 templating in agentic workflow configuration files, enabling reusable patterns, macros, and dynamic configuration generation.

Think of templates like function definitions in programming: you define a pattern once, then call it wherever you need it. This keeps your agentic workflows DRY (Don't Repeat Yourself) and makes updates easier—change the template, and all agentic workflows using it update automatically.

## Overview

Let's explore what templates provide:

- **Reusable macros** - Define action groups once, use across agentic workflows
- **Dynamic generation** - Generate agentic workflows programmatically
- **Configuration inheritance** - Extend base configurations
- **Conditional logic** - Include/exclude actions based on parameters

:::info
Templates are rendered before your agentic workflow runs. This means template errors are caught early, during configuration loading rather than at runtime.
:::

## What Renders When

Loading a workflow renders the file through Jinja before it is parsed as YAML. Each action's `prompt:` is decided where the load reaches it, with exactly the names bound there: names the file binds with `{% set %}`, `{% for %}`, `{% import %}` or a macro's parameters, the macros and variables of `templates/`, `load_prompt`, and Jinja's own globals such as `range`.

- A prompt whose names are all bound renders at load, as it always has.
- A prompt that reads a name a record or a version supplies (`source`, `seed`, an action of the workflow, `version`, `i`, `idx` or a version `param`) is kept whole and renders per record, exactly as the same prompt in the prompt store does, `{% if %}`, `is defined`, captures and macros of its own included. Its own `{{ }}` tags outside its `{% %}` blocks that read only load-time names render into it at load: with `{% for n in [1, 2] %}`, `Stage {{ n }} of {{ source.text }}` becomes `Stage 2 of {{ source.text }}`. Load-time data its other tags read, such as a list a `{% for %}` walks or a flag an `{% if %}` tests, is set at its top (`{% set fields = ["title", "body"] +%}`).
- A versioned action's other values (`model_vendor`, `model_name`, `intent`, …) that read a version variable render once per version, as if the version's variables were set when the file loads. On an action without `versions:` such a value fails the load, unless the variable is guarded with `is defined` or `default(...)`.

Only data reaches the per-record render. A prompt that renders per record can use a macro, `load_prompt` or an imported template only in a `{{ }}` tag of its own outside its `{% %}` blocks, and cannot `{% include %}` anything; otherwise the load fails naming it. Define the macro inside the prompt instead.

Everything else renders at load. A name nothing defines fails the load (`'enable_validation' is undefined`) instead of rendering as nothing, unless it is guarded with `is defined` or `default(...)`, and so does a field a loaded name lacks. A name a record or a version supplies, read anywhere the load renders, also fails the load, so a record never sees a branch decided once for all of them: in a value other than a prompt, in a `{% set %}` block, macro body or `caller()` body that a prompt outputs, or tested with `is defined`. To hand a per-record tag to a prompt through a macro or a captured block, wrap it in `{% raw %}...{% endraw %}`; the prompt receives the tag as text and renders it per record.

The top level of each `templates/` file runs once as the folder loads, to collect its macros and variables, with nothing bound; there, as before, an undefined name renders as nothing.

## Template Location

Templates are stored in the `templates/` directory:

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

Here's where it gets interesting. Define reusable action groups with Jinja2 macros—these become building blocks you can compose into larger agentic workflows:

```jinja2
\{# templates/thinkific_tools.jinja2 #\}

\{% macro thinkific_tools() -\%\}
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
\{%- endmacro \%\}
```

### Parameterized Macros

Create macros that accept parameters:

```jinja2
\{% macro validation_chain(first_dependency, schema_name) -\%\}
  - name: validate_structure
    kind: llm
    dependencies: [\{\{ first_dependency \}\}]
    schema: \{\{ schema_name \}\}
    prompt: $prompts.validate_structure

  - name: validate_content
    dependencies: [validate_structure]  # Input source
    schema: \{\{ schema_name \}\}_content
    prompt: $prompts.validate_content
\{%- endmacro \%\}
```

## Using Templates in Agentic Workflows

Import and use macros in agentic workflow files. Consider what happens when you import a macro—you're essentially including a pre-defined set of actions:

```yaml
# agent_config/my_workflow.yml
\{% from 'thinkific_tools.jinja2' import thinkific_tools \%\}

name: my_workflow
description: "Workflow using template macros"

actions:
  - name: prepare_data
    kind: tool
    impl: prepare_data
    intent: "Prepare data for processing"

  # Include macro-defined actions
\{\{ thinkific_tools() | indent(2) \}\}
```

Dependencies come from each action's own `dependencies:` key. A top-level
`plan:` block is not part of the schema and is refused.

## Rendered Output

You might wonder how to verify your templates expanded correctly. Agent Actions renders templates before execution, and the rendered agentic workflow is saved to:

```
artefact/rendered_workflows/my_workflow.yml
```

Use this for debugging template expansion:

```bash
# View rendered workflow
cat artefact/rendered_workflows/my_workflow.yml

# Compare original vs rendered
diff agent_workflow/my_workflow/agent_config/my_workflow.yml \
     artefact/rendered_workflows/my_workflow.yml
```

## Template Variables

### Built-in Variables

The load supplies no variables of its own: only `load_prompt`, the macros and variables of `templates/`, and Jinja's globals (`range`, `dict`, `namespace`, …). Anything else a tag names comes from the file itself.

### Custom Variables

Define variables in the workflow:

```yaml
\{% set model = "gpt-4o-mini" \%\}
\{% set api_key = "OPENAI_API_KEY" \%\}

defaults:
  model_name: \{\{ model \}\}
  api_key: \{\{ api_key \}\}
```

## Conditional Actions

Include actions conditionally on a variable the file sets:

```jinja2
\{% set enable_validation = true \%\}

\{% if enable_validation \%\}
  - name: validate_output
    kind: llm
    schema: validation_result
    prompt: $prompts.validate
\{% endif \%\}
```

## Loops for Repeated Patterns

Generate multiple actions with loops:

```jinja2
\{% for stage in [1, 2, 3] \%\}
  - name: process_stage_\{\{ stage \}\}
    kind: llm
    intent: "Process stage \{\{ stage \}\}"
    schema: stage_\{\{ stage \}\}_output
    prompt: $prompts.process_stage
    \{% if stage > 1 \%\}
    dependencies: [process_stage_\{\{ stage - 1 \}\}]
    \{% endif \%\}
\{% endfor \%\}
```

## Debugging Templates

To see the rendered output, use `agac run` which writes compiled prompts into the `prompt_trace` table.

When workflow rendering fails, the framework saves the partial rendered YAML to `.agent-actions/cache/rendered_workflows/<workflow>_failed.yml` and prints the path in the error message. You can `cat` that file to inspect template expansion and context-scope output that produced the failure.

For deeper debugging, use `agac inspect context -a my_workflow <action_name>` to see what data namespaces and variables are available for a specific action's template.

## Best Practices

Let's walk through some patterns that make templates easier to maintain.

### 1. Keep Macros Focused

```jinja2
\{# Good: Single responsibility #\}
\{% macro extraction_actions() \%\}...\{% endmacro \%\}
\{% macro validation_actions() \%\}...\{% endmacro \%\}

\{# Avoid: Monolithic macros #\}
\{% macro entire_workflow() \%\}...\{% endmacro \%\}
```

### 2. Use Descriptive Names

```jinja2
\{# Good #\}
\{% macro quiz_generation_chain(source_action) \%\}

\{# Avoid #\}
\{% macro m1(s) \%\}
```

### 3. Document Parameters

```jinja2
\{#
  Create a validation chain for the given source.

  Args:
    source_action: Name of the upstream action to validate
    schema_name: Base schema name for validation

  Returns:
    Two validation actions: validate_structure, validate_content
#\}
\{% macro validation_chain(source_action, schema_name) \%\}
```

### 4. Test Rendered Output

Always verify template expansion before running:

```bash
# Validate (any rendering failure surfaces non-zero with the saved YAML path).
agac inspect -a my_workflow
```

### 5. Use Whitespace Control

Jinja2 whitespace control prevents extra newlines:

```jinja2
\{# Without control: extra blank lines #\}
\{% macro actions() \%\}
  - name: action1
\{% endmacro \%\}

\{# With control: clean output #\}
\{%- macro actions() -\%\}
  - name: action1
\{%- endmacro -\%\}
```

## Common Patterns

Here are some patterns you'll encounter frequently when building agentic workflows with templates.

### Base Configuration Extension

```jinja2
\{# templates/base.jinja2 #\}
\{% macro base_defaults() \%\}
defaults:
  json_mode: true
  granularity: record
  run_mode: online
  model_vendor: openai
  model_name: gpt-4o-mini
  api_key: OPENAI_API_KEY
\{% endmacro \%\}
```

```yaml
\{# Agentic workflow using base #\}
\{% from 'base.jinja2' import base_defaults \%\}

name: my_workflow
\{\{ base_defaults() \}\}

actions:
  - name: my_action
    # Uses base defaults
```

### Feature Flags

Feature flags let you toggle parts of your agentic workflow on and off. This is useful for A/B testing or gradually rolling out new actions:

```jinja2
\{% set features = \{
  'enable_caching': true,
  'enable_validation': true,
  'enable_monitoring': false
\} \%\}

\{% if features.enable_validation \%\}
  - name: validate_output
    ...
\{% endif \%\}
```

:::warning
Templates add a layer of indirection. When debugging agentic workflow issues, always check the rendered output in `artefact/rendered_workflows/` to see what configuration actually ran.
:::
