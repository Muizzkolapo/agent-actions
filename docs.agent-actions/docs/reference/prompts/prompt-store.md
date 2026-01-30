---
title: Prompt Store
sidebar_position: 1
---

# Prompt Store

The Prompt Store provides centralized management for reusable prompt templates. Prompts are written in Markdown files with Jinja2 templating support.

## Syntax

### Prompt Definition

```markdown
{prompt Extract_Facts}
Extract facts from the following content.

Content: {{ source.page_content }}

Return JSON matching the schema.
{end_prompt}
```

### Prompt Reference

Reference prompts in YAML using the `$` syntax:

```yaml
- name: extract_facts
  prompt: $qanalabs_quiz_gen.Extract_Facts
```

Format: `$filename.Prompt_Name` (filename without `.md`)

## Directory Structure

Prompts can be at project level (shared) or workflow level (domain-specific):

```
project/
├── prompt_store/                    # Shared prompts
│   └── common.md
└── agent_workflow/
    └── my_workflow/
        └── prompt_store/            # Workflow-specific prompts
            └── my_prompts.md
```

Agent Actions searches recursively—use unique filenames across your project.

## Creating Prompts

### With Seed Data

```markdown
{prompt Fact_extraction}
Extract facts relevant to the {{ seed.exam_syllabus.exam_name }} exam.

## Target Audience
{{ seed.exam_syllabus.audience_profile.description }}

## Source Content
{{ source.page_content }}
{end_prompt}
```

### With Jinja2 Loops

```markdown
{prompt Generate_Questions}
{% for skill in seed.exam_syllabus.skills_measured %}
## {{ skill.skill_area }}
{% for objective in skill.objectives %}
- {{ objective }}
{% endfor %}
{% endfor %}
{end_prompt}
```

### With Conditionals

```markdown
{prompt Validate_Content}
{% if source.content_type == "technical" %}
Apply strict technical accuracy checks.
{% else %}
Apply general readability checks.
{% endif %}

Content: {{ source.content }}
{end_prompt}
```

## Workflow Reference

```yaml
actions:
  - name: fact_extractor
    prompt: $qanalabs_quiz_gen.Fact_extraction
    schema: candidate_facts_list

  - name: canonicalize_facts
    dependencies: fact_extractor
    prompt: $qanalabs_quiz_gen.Canonicalize_Facts
    schema: candidate_facts_list
```

## Inline Prompts

For simple, one-off prompts, use inline YAML:

```yaml
- name: simple_validate
  prompt: |
    Validate these facts: {{ extract_facts.facts }}
    Return: {"valid": true/false, "reason": "..."}
```

Use inline when prompt is specific to one action. Use prompt store when prompts are reused or complex.

## Template Variables

| Variable | Source | Example |
|----------|--------|---------|
| `{{ source.field }}` | Input record data | `{{ source.page_content }}` |
| `{{ seed.name.field }}` | Seed data files | `{{ seed.exam_syllabus.exam_name }}` |
| `{{ action_name.field }}` | Upstream action output | `{{ extract_facts.facts }}` |

## Jinja2 Features

### Filters

```markdown
{{ source.text | upper }}
{{ source.items | length }}
{{ source.optional_field | default("N/A") }}
```

### Load Other Prompts

```markdown
{prompt Main_Analysis}
{{ load_prompt("common.Standard_Header") }}

## Analysis Content
{{ source.content }}
{end_prompt}
```

## Best Practices

1. **Use descriptive names**: `{prompt Extract_Technical_Facts}` not `{prompt prompt1}`
2. **Structure complex prompts**: Use consistent section headers (CONTEXT, TASK, OUTPUT FORMAT)
3. **Separate concerns**: Group related prompts in files (`extraction.md`, `validation.md`)

## Debugging Prompts

Enable `prompt_debug` to see rendered prompts:

```yaml
- name: extract_facts
  prompt: $qanalabs_quiz_gen.Fact_extraction
  prompt_debug: true
```
