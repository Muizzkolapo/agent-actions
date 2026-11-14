---
title: Prompt Store
sidebar_position: 1
---

# Prompt Store

The Prompt Store keeps reusable prompt templates in one central location. You write the prompts in Markdown files, with support for Jinja2 templating.

## Syntax

### Prompt Definition

```markdown
{prompt Extract_Facts}
Extract facts from the following content.

Content: {{ source.content }}

Return JSON matching the schema.
{end_prompt}
```

### Prompt Reference

Reference prompts in YAML with the `$` syntax:

```yaml
- name: extract_facts
  prompt: $my_workflow.Extract_Facts
```

Format: `$filename.Prompt_Name` (the filename without `.md`). A prompt name must be unique in its file.

## Directory Structure

Prompts can be at the project level (shared) or at the workflow level (domain-specific):

```
project/
├── prompt_store/                    # Shared prompts
│   └── common.md
└── agent_workflow/
    └── my_workflow/
        └── prompt_store/            # Workflow-specific prompts
            └── my_prompts.md
```

Agent Actions searches recursively. Thus, use unique filenames across your project.

## Creating Prompts

### With Seed Data

```markdown
{prompt Fact_extraction}
Extract facts relevant to the {{ seed.exam_syllabus.exam_name }} exam.

## Target Audience
{{ seed.exam_syllabus.audience_profile.description }}

## Source Content
{{ source.content }}
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
    prompt: $my_workflow.Fact_extraction
    schema: candidate_facts_list

  - name: canonicalize_facts
    dependencies: [fact_extractor]
    prompt: $my_workflow.Canonicalize_Facts
    schema: candidate_facts_list
```

## Inline Prompts

For simple prompts that you use one time, use inline YAML:

```yaml
- name: simple_validate
  dependencies: [extract_facts]
  prompt: |
    Validate these facts: {{ extract_facts.facts }}
    Return: {"valid": true/false, "reason": "..."}
```

Use an inline prompt when the prompt is specific to one action. Use the prompt store when prompts are reused or complex.

## Template Variables

| Variable | Source | Example |
|----------|--------|---------|
| `{{ source.field }}` | Input record data | `{{ source.content }}` |
| `{{ seed.name.field }}` | Seed data files | `{{ seed.exam_syllabus.exam_name }}` |
| `{{ action_name.field }}` | Upstream action output | `{{ extract_facts.facts }}` |

Agent Actions reads a field by its name, even when the name is also a dictionary method (`items`, `keys`, `values`, `get`). For example, `{{ source.items }}` is the `items` field. A record without that field fails like any missing field. A call to the method still works: `{{ source.get('description', '') }}`, `{% for key, value in source.items() %}`.

The same calls work on an upstream action, as in `{% for key, value in extract_facts.items() %}`. Pre-flight reads a call to `items()`, `keys()` or `values()` as a use of the whole action, not of a field named after the method. Pre-flight checks the field named in `extract_facts.get('facts', '')` against the schema of the action. This is the same check as for `extract_facts.facts`. Thus pre-flight refuses a misspelt field before the run, in both forms.

## Jinja2 Features

### Filters

```markdown
{{ source.data | tojson }}              {# Serialize as JSON (most common) #}
{{ source.text | upper }}               {# Uppercase text #}
{{ source.items | length }}             {# Count items #}
{{ source.optional_field | default("N/A") }}  {# Fallback value #}
{{ source.tags | join(", ") }}          {# Join list as string #}
```

:::note[tojson Filter]
The `| tojson` filter is essential when you pass structured data (dicts, lists) into prompts. Without the filter, the prompt gets the Python string representation, which can confuse the LLM.
:::

Use the `| tojson` filter for seed data and complex fields:

```markdown
{{ seed.brand_voice | tojson }}
{{ extract_context.key_terms | tojson }}
```

### Version Variables

When you use [versioned actions](../execution/versions), these variables are available in prompts:

| Variable | Type | Description |
|----------|------|-------------|
| `{{ i }}` | int | The current iteration number (from `range`) |
| `{{ version.length }}` | int | The total number of iterations |

```markdown
You are evaluator {{ i }} of {{ version.length }}.
```

### Load Other Prompts

`{{ load_prompt("file.Prompt") }}` inserts another store prompt, as written, when the workflow loads. The tags of the inserted prompt then render for each record, like the rest of the prompt. A loaded prompt may load other prompts in turn. Write each call as a separate tag, with the name of the prompt as a quoted string. The load fails on any other form. The load also fails on prompts that load each other in a cycle, and names those prompts.

```markdown
{prompt Main_Analysis}
{{ load_prompt("common.Standard_Header") }}

## Analysis Content
{{ source.content }}
{end_prompt}
```

The inline `prompt:` of an action in the workflow file can load a store prompt the same way, for any number of lines. The loaded text goes in as written, exactly as in a store prompt. This is true for each YAML style that the `prompt:` uses: a `|` or `>` block, or a quoted value. The line breaks of the loaded text are kept, and its lines are not read as YAML. Thus the loaded text needs no indentation of its own. If a filter is applied to it first, for example `{{ load_prompt("common.Standard_Header") | indent(6) }}`, it becomes ordinary text. The YAML reads that text at the location of the tag.

```yaml
actions:
  - name: analyze
    prompt: |
      {{ load_prompt("common.Standard_Header") }}
      Summarize {{ source.title }}.
```

## Advanced Patterns (Production Cookbook)

These patterns come from production workflows. They show what is possible with Jinja2 in prompts.

### Arithmetic in Templates

Use inline math to set dynamic constraints from the output of an upstream tool:

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

Convert numeric loop indices to letters (A, B, C, D) with chained filters:

```markdown
{prompt Format_Options}
{% for option in reconstruct_options.options %}
{{ loop.index | string | replace('1', 'A') | replace('2', 'B') | replace('3', 'C') | replace('4', 'D') }}. {{ option }}
{% endfor %}
{end_prompt}
```

### Dictionary Iteration with Filtering

Iterate over the key-value pairs of a dictionary, and filter them by a key pattern:

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

Iterate over structured arrays, with access to nested fields:

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

When you generate more than one alternative, reference the previous outputs to prevent repetition:

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

Create independent evaluators that do not see the work of the other evaluators:

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

1. **Use descriptive names**: `{prompt Extract_Technical_Facts}`, not `{prompt prompt1}`
2. **Structure complex prompts**: Use consistent section headers (CONTEXT, TASK, OUTPUT FORMAT)
3. **Separate concerns**: Group related prompts in files (`extraction.md`, `validation.md`)

## Debugging Prompts

To see the rendered prompts, enable `prompt_debug`:

```yaml
- name: extract_facts
  prompt: $my_workflow.Fact_extraction
  prompt_debug: true
```
