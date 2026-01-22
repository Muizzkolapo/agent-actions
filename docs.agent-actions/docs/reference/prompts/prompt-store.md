---
title: Prompt Store
sidebar_position: 1
---

# Prompt Store

As agentic workflows grow, prompts can become scattered across configuration files, making them hard to maintain and version. The Prompt Store solves this by providing a centralized system for managing reusable prompt templates. Prompts are written in Markdown files with Jinja2 templating support, enabling dynamic content injection from source data and seed data.

## Overview

Let's explore what the prompt store provides:

- **Reusability** - Define prompts once, use across multiple actions
- **Maintainability** - Edit prompts in Markdown without touching YAML config
- **Templating** - Inject dynamic content with Jinja2 syntax
- **Organization** - Group related prompts in namespaced files

## Syntax

### Prompt Definition

Prompts are defined in Markdown files using delimiter tags:

```markdown
\{prompt Prompt_Name\}
Your prompt content here.

Supports Jinja2 templating: \{\{ source.field \}\}

Multiple paragraphs and markdown formatting allowed.
\{end_prompt\}
```

### Prompt Reference

How do you use these prompts in your agentic workflow? Reference prompts in your YAML configuration using the `$` syntax:

```yaml
- name: extract_facts
  prompt: $qanalabs_quiz_gen.Fact_extraction
```

Format: `$filename.Prompt_Name`

| Component | Description |
|-----------|-------------|
| `$` | Prompt store reference prefix |
| `filename` | Markdown file name (without `.md`) |
| `Prompt_Name` | Name defined in `{prompt Name}` tag |

## Directory Structure

Prompts can be organized at **project level** (shared across workflows) or **workflow level** (domain-specific). Agent Actions searches recursively from the project root, so both locations work:

### Project-Level Prompts (Shared)

```
project/
├── agent_actions.yml
├── prompt_store/                    # Shared across all workflows
│   ├── common.md                    # Shared prompts
│   └── validation.md                # Reusable validation prompts
└── agent_workflow/
    └── ...
```

### Workflow-Level Prompts (Domain-Specific)

```
project/
├── agent_actions.yml
└── agent_workflow/
    └── quiz_generation/
        ├── agent_config/
        ├── prompt_store/            # Workflow-specific prompts
        │   ├── qanalabs_quiz_gen.md
        │   └── feynman.md
        └── seed_data/
```

### Mixed Approach (Recommended for Multi-Workflow Projects)

```
project/
├── agent_actions.yml
├── prompt_store/                    # Shared prompts
│   └── common.md
└── agent_workflow/
    ├── quiz_generation/
    │   └── prompt_store/            # Quiz-specific prompts
    │       └── quiz_prompts.md
    └── document_analysis/
        └── prompt_store/            # Analysis-specific prompts
            └── analysis_prompts.md
```

When you reference `$quiz_prompts.Extract_Facts`, Agent Actions searches recursively and finds the file regardless of its location. If multiple files have the same name, the first match is used—so use unique filenames across your project.

## Creating Prompts

### Basic Prompt

```markdown
\{prompt Extract_Entities\}
Extract all named entities from the following text.

## Text to Process
\{\{ source.content \}\}

## Output Format
Return entities as a JSON array with name, type, and context.
\{end_prompt\}
```

### Prompt with Seed Data

```markdown
\{prompt Fact_extraction\}
Extract facts relevant to the \{\{ seed.exam_syllabus.exam_name \}\} exam.

## Target Audience
\{\{ seed.exam_syllabus.audience_profile.description \}\}

## Source Content
\{\{ source.page_content \}\}
\{end_prompt\}
```

### Prompt with Jinja2 Loops

```markdown
\{prompt Generate_Questions\}
Generate questions based on the following learning objectives:

\{\% for skill in seed.exam_syllabus.skills_measured \%\}
## \{\{ skill.skill_area \}\} (\{\{ skill.weight \}\})
\{\% for section in skill.sections \%\}
### \{\{ section.section_name \}\}
\{\% for objective in section.objectives \%\}
- \{\{ objective \}\}
\{\% endfor \%\}
\{\% endfor \%\}
\{\% endfor \%\}

## Source Facts
\{\{ flatten_clusters.grouped_facts \}\}
\{end_prompt\}
```

### Prompt with Conditionals

```markdown
\{prompt Validate_Content\}
Validate the following content for quality.

\{\% if source.content_type == "technical" \%\}
Apply strict technical accuracy checks.
\{\% else \%\}
Apply general readability checks.
\{\% endif \%\}

Content: \{\{ source.content \}\}
\{end_prompt\}
```

## Example from qanalabs

### Prompt Store File

````markdown
\{prompt Fact_extraction\}
Extract **atomic, testable facts** about \{\{ seed.exam_syllabus.platform_name \}\}.

## LEARNING OBJECTIVES CONTEXT

\{\% for ref in source.referenced_in \%\}
**Section**: \{\{ ref.section_name \}\}
**Objective**: \{\{ ref.objective \}\}
**Relevance**: \{\{ ref.relevance \}\}
\{\% endfor \%\}

## TARGET AUDIENCE PROFILE

**Exam**: \{\{ seed.exam_syllabus.exam_name \}\}

\{\{ seed.exam_syllabus.audience_profile.description \}\}

**Target Responsibilities**:
\{\% for resp in seed.exam_syllabus.audience_profile.responsibilities \%\}
- \{\{ resp \}\}
\{\% endfor \%\}

## Output

Return JSON matching the schema.
\{end_prompt\}


\{prompt Canonicalize_Facts\}
You are a fact canonicalization agent. Identify duplicate facts and produce
a single canonical version for each group.

## INPUT STRUCTURE:
- `candidate_facts_list`: Array of facts from source document

## YOUR TASK:
1. Identify semantic duplicates
2. Create canonical versions
3. Preserve best metadata

## OUTPUT FORMAT:
Return deduplicated facts using the same schema.
\{end_prompt\}
````

### Workflow Reference

```yaml
actions:
  - name: fact_extractor
    prompt: $qanalabs_quiz_gen.Fact_extraction
    schema: candidate_facts_list

  - name: canonicalize_facts
    dependencies: fact_extractor  # Input source
    prompt: $qanalabs_quiz_gen.Canonicalize_Facts
    schema: candidate_facts_list
```

## Inline Prompts

Not every prompt needs to live in the store. For simple, one-off prompts, use inline YAML:

```yaml
- name: simple_validate
  prompt: |
    Validate these facts: {{ extract_facts.facts }}

    Return: {"valid": true/false, "reason": "..."}
```

Use inline prompts when:
- Prompt is specific to one action
- Prompt is simple (< 10 lines)
- No reuse is expected

Use prompt store when:
- Prompt is reused across actions
- Prompt is complex with multiple sections
- Prompt needs independent versioning

## Available Template Variables

| Variable | Source | Example |
|----------|--------|---------|
| `{{ source.field }}` | Input record data | `{{ source.page_content }}` |
| `{{ seed.name.field }}` | Seed data files | `{{ seed.exam_syllabus.exam_name }}` |
| `{{ action_name.field }}` | Upstream action output | `{{ extract_facts.facts }}` |

## Jinja2 Features

### Loops

```markdown
\{\% for item in source.items \%\}
- \{\{ item.name \}\}: \{\{ item.value \}\}
\{\% endfor \%\}
```

### Conditionals

```markdown
\{\% if source.count > 10 \%\}
Process in batches.
\{\% else \%\}
Process all at once.
\{\% endif \%\}
```

### Filters

```markdown
\{\{ source.text | upper \}\}
\{\{ source.items | length \}\}
\{\{ source.data | tojson \}\}
```

### Default Values

```markdown
\{\{ source.optional_field | default("N/A") \}\}
```

### Custom Filters

Agent Actions provides additional Jinja2 filters:

| Filter | Description | Example |
|--------|-------------|---------|
| `dedent` | Remove common leading whitespace | `{{ text \| dedent }}` |

### Global Functions

Available in all templates:

| Function | Description | Example |
|----------|-------------|---------|
| `load_prompt("filename.Prompt_Name")` | Load another prompt dynamically | `{{ load_prompt("common.Header") }}` |

```markdown
\{prompt Main_Analysis\}
\{\{ load_prompt("common.Standard_Header") \}\}

## Analysis Content
\{\{ source.content \}\}

\{\{ load_prompt("common.Standard_Footer") \}\}
\{end_prompt\}
```

## Best Practices

### 1. Use Descriptive Names

```markdown
\{prompt Extract_Technical_Facts\}    <!-- Good -->
\{prompt prompt1\}                    <!-- Avoid -->
```

### 2. Document Expected Context

```markdown
\{prompt Generate_Quiz_Question\}
<!-- Required context:
     - seed.exam_syllabus: Exam metadata with skills_measured
     - source.facts: Array of extracted facts
     - flatten_clusters.cluster_name: Topic cluster
-->
...
\{end_prompt\}
```

### 3. Structure Complex Prompts

````markdown
\{prompt Complex_Analysis\}
## CONTEXT
\{\{ source.background \}\}

## TASK
Perform detailed analysis.

## CONSTRAINTS
- Maximum 500 words
- Focus on technical accuracy

## OUTPUT FORMAT
```json
\{...\}
```
\{end_prompt\}
````

### 4. Use Consistent Formatting

All prompts in a file should follow consistent patterns for:
- Section headers
- Output format specification
- Constraint documentation

### 5. Separate Concerns

```
prompt_store/
├── extraction.md       # Fact/entity extraction prompts
├── validation.md       # Validation and quality prompts
├── generation.md       # Content generation prompts
└── common.md          # Shared utility prompts
```

## Debugging Prompts

Enable `prompt_debug` to see rendered prompts:

```yaml
- name: extract_facts
  prompt: $qanalabs_quiz_gen.Fact_extraction
  prompt_debug: true
```

This outputs the fully rendered prompt after Jinja2 processing, showing exactly what the LLM receives.

## Error Handling

When prompts fail to load or render, Agent Actions provides specific error messages to help you diagnose the problem.

### Missing Prompt

```
ConfigurationError: Prompt 'nonexistent.Prompt_Name' not found in prompt store
```

Check that:
1. File `nonexistent.md` exists in `prompt_store/`
2. `{prompt Prompt_Name}` tag is properly defined
3. Reference matches exact case (prompt names are case-sensitive)

### Missing Template Variable

```
TemplateError: 'source.missing_field' is undefined in prompt 'Extract_Facts'
```

Ensure referenced fields exist in source data or upstream outputs.

### Invalid Jinja2 Syntax

```
TemplateSyntaxError: Unexpected end of template in 'My_Prompt'
```

Check for unclosed `{% %}` blocks or missing `{% endfor %}`/`{% endif %}`.
