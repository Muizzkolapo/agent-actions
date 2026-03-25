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
{{ source.data | tojson }}              {# Serialize as JSON (most common) #}
{{ source.text | upper }}               {# Uppercase text #}
{{ source.items | length }}             {# Count items #}
{{ source.optional_field | default("N/A") }}  {# Fallback value #}
{{ source.tags | join(", ") }}          {# Join list as string #}
```

:::tip tojson Filter
The `| tojson` filter is essential when passing structured data (dicts, lists) into prompts. Without it, Python's string representation is used, which can confuse the LLM. All examples use `| tojson` for seed data and complex fields:

```markdown
{{ seed.brand_voice | tojson }}
{{ extract_context.key_terms | tojson }}
```
:::

### Version Variables

When using [versioned actions](../execution/versions), these variables are available in prompts:

| Variable | Type | Description |
|----------|------|-------------|
| `{{ i }}` | int | Current iteration number (from `range`) |
| `{{ version.length }}` | int | Total number of iterations |

```markdown
You are evaluator {{ i }} of {{ version.length }}.
```

### Load Other Prompts

```markdown
{prompt Main_Analysis}
{{ load_prompt("common.Standard_Header") }}

## Analysis Content
{{ source.content }}
{end_prompt}
```

## Advanced Patterns (Production Cookbook)

These patterns come from production agentic workflows and show what's possible with Jinja2 in prompts.

### Arithmetic in Templates

Use inline math to set dynamic constraints based on upstream tool output:

```markdown
{prompt Generate_Distractor}
{% if add_answer_text.distractor_1_word_target == "lesser_than" %}
Your distractor must be SHORTER: Write {{ add_answer_text.correctAnswerWords - 2 }} to {{ add_answer_text.correctAnswerWords - 1 }} words
{% elif add_answer_text.distractor_1_word_target == "equal_to" %}
Your distractor must match length: Write exactly {{ add_answer_text.correctAnswerWords }} words
{% elif add_answer_text.distractor_1_word_target == "greater_than" %}
Your distractor must be LONGER: Write {{ add_answer_text.correctAnswerWords + 2 }} to {{ add_answer_text.correctAnswerWords + 4 }} words
{% endif %}
{end_prompt}
```

### Loop Index to Letter Conversion

Convert numeric loop indices to letters (A, B, C, D) using chained filters:

```markdown
{prompt Format_Options}
{% for option in reconstruct_options.options %}
{{ loop.index | string | replace('1', 'A') | replace('2', 'B') | replace('3', 'C') | replace('4', 'D') }}. {{ option }}
{% endfor %}
{end_prompt}
```

### Dictionary Iteration with Filtering

Iterate over a dictionary's key-value pairs and filter by key pattern:

```markdown
{prompt Summarize_Alternatives}
{% for key, value in merge_alternatives.items() %}
{% if 'issue_description' in key %}
- {{ value }}
{% endif %}
{% endfor %}
{end_prompt}
```

### Array of Objects Iteration

Loop through structured arrays with nested field access:

```markdown
{prompt Analyze_References}
{% for ref in source.referenced_in %}
- **Section**: {{ ref.section_name }}
  **Objective**: {{ ref.objective }}
  **Relevance**: {{ ref.relevance }}
{% endfor %}
{end_prompt}
```

### Deep Seed Data Traversal

Access deeply nested seed data structures:

```markdown
{prompt Extract_Facts}
Extract facts relevant to the {{ seed.exam_syllabus.exam_name }} exam.

## Target Audience
{{ seed.exam_syllabus.audience_profile.description }}

## Skills Measured
{% for skill in seed.exam_syllabus.skills_measured %}
### {{ skill.skill_area }} (Weight: {{ skill.weight }})
{% for section in skill.sections %}
- {{ section }}
{% endfor %}
{% endfor %}
{end_prompt}
```

### Chaining Upstream References to Prevent Duplication

When generating multiple alternatives, reference previous outputs to avoid repetition:

```markdown
{prompt Generate_Distractor_2}
## EXISTING OPTIONS (DO NOT DUPLICATE)
- Correct answer: {{ add_answer_text.answer_text }}
- Distractor 1: {{ generate_distractor_1.distractor_1 }}

Write a DIFFERENT distractor that uses a wrong approach.
{end_prompt}

{prompt Generate_Distractor_3}
## EXISTING OPTIONS (DO NOT DUPLICATE)
- Correct answer: {{ add_answer_text.answer_text }}
- Distractor 1: {{ generate_distractor_1.distractor_1 }}
- Distractor 2: {{ generate_distractor_2.distractor_2 }}

Write a DIFFERENT distractor that covers an edge case.
{end_prompt}
```

### Ensemble Voting with Version Variables

Create independent evaluators that don't see each other's work:

```markdown
{prompt Validate_Answer}
You are validator {{ i }} of {{ version.length }}, working independently.

## Question
{{ reconstruct_options.question }}

## Options
{% for option in reconstruct_options.options %}
{{ loop.index | string | replace('1', 'A') | replace('2', 'B') | replace('3', 'C') | replace('4', 'D') }}. {{ option }}
{% endfor %}

## Claimed Answer
{{ reconstruct_options.answer }}

Verify whether the claimed answer is correct based on the source material.
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
