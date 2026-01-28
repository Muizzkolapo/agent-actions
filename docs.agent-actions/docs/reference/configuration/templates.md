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
    dependencies: validate_structure  # Input source
    schema: \{\{ schema_name \}\}_content
    prompt: $prompts.validate_content
\{%- endmacro \%\}
```

### Dependency Macros

Define execution plans with dependency macros:

```jinja2
\{% macro thinkific_plan(first_dependency) -\%\}
    format_quiz_object <- \{\{ first_dependency \}\}
  - add_asterisk_to_correct_answer <- format_quiz_object
  - convert_html_json_to_thinkific <- add_asterisk_to_correct_answer
\{%- endmacro \%\}
```

## Using Templates in Agentic Workflows

Import and use macros in agentic workflow files. Consider what happens when you import a macro—you're essentially including a pre-defined set of actions:

```yaml
# agent_config/my_workflow.yml
\{% from 'thinkific_tools.jinja2' import thinkific_tools, thinkific_plan \%\}

name: my_workflow
description: "Workflow using template macros"

actions:
  - name: prepare_data
    kind: tool
    impl: prepare_data
    intent: "Prepare data for processing"

  # Include macro-defined actions
\{\{ thinkific_tools() | indent(2) \}\}

# Dependency plan
plan:
\{\{ thinkific_plan('prepare_data') | indent(2) \}\}
```

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

| Variable | Description |
|----------|-------------|
| `workflow_name` | Current workflow name |
| `env` | Environment variables dict |
| `now` | Current timestamp |

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

Include actions conditionally:

```jinja2
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

## Debug Mode

When templates don't expand as expected, enable template debugging to see expansion details:

```bash
# Render template without executing
agac render -a my_workflow

# Enable debug output
agac render -a my_workflow --debug
```

Log output shows template processing:

```
19:56:59.641 INFO     Starting render template
19:56:59.657 INFO     Rendered template saved to: artefact/rendered_workflows/my_workflow.yml
```

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
# Render and review
agac render -a my_workflow > /dev/null && \
cat artefact/rendered_workflows/my_workflow.yml
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

### Environment-Specific Configuration

Consider what happens when you need different settings for development vs production. Templates let you branch based on environment variables:

```jinja2
\{% if env.AGENT_ACTIONS_ENV == 'production' \%\}
  model_name: gpt-4o
  run_mode: batch
\{% else \%\}
  model_name: gpt-4o-mini
  run_mode: online
\{% endif \%\}
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
