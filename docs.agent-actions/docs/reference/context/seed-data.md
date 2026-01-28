---
title: Seed Data
sidebar_position: 4
---

# Seed Data

What happens when every action in your agentic workflow needs access to the same reference data—like an exam syllabus or grading rubric? You could repeat it in every prompt, but that's tedious and error-prone. Seed Data provides a mechanism to load static reference data into agentic workflow context. This is similar to dbt's `seed` concept—pre-loaded data that remains constant across all records in an agentic workflow run.

Think of seed data like a shared reference book that sits on every desk in an office. Each worker (action) can look up the same information without needing their own copy.

## Use Cases

- **Reference data** - Exam syllabi, taxonomies, configuration lookups
- **Domain knowledge** - Product catalogs, entity lists, validation rules
- **Templates** - Standard formats, response structures, grading rubrics
- **Constants** - Thresholds, weights, feature flags

## Syntax

Seed data is configured in `context_scope.seed_data`:

```yaml
defaults:
  context_scope:
    seed_data:
      exam_syllabus: $file:syllabus.json
      grading_rubric: $file:rubric.yaml
```

### File Reference Syntax

| Syntax | Description |
|--------|-------------|
| `$file:filename.json` | Load JSON file from `seed_data/` directory |
| `$file:filename.yaml` | Load YAML file from `seed_data/` directory |
| `$file:path/to/file.json` | Load from subdirectory within `seed_data/` |

## Directory Structure

Seed data files are stored in the agentic workflow's `seed_data/` directory. Consider what happens when Agent Actions loads your agentic workflow—it looks for seed files relative to this location:

```
agent_workflow/
└── my_workflow/
    ├── agent_config/
    │   └── my_workflow.yml
    ├── agent_io/
    │   ├── staging/         # Input data (starting point)
    │   ├── source/          # Metadata tracking
    │   └── target/
    └── seed_data/           # Seed data files here
        ├── syllabus.json
        ├── rubric.yaml
        └── lookups/
            └── categories.json
```

## Accessing Seed Data

Use the `seed` prefix in field references:

```yaml
prompt: |
  You are creating questions for the {{ seed.exam_syllabus.exam_name }} exam.

  The exam covers these skill areas:
  {% for skill in seed.exam_syllabus.skills_measured %}
  - {{ skill.skill_area }} ({{ skill.weight }})
  {% endfor %}
```

Seed data is namespaced under `seed` in prompt context only. It is not flattened
into the top-level record or injected into LLM/tool context by default. That
means you should reference fields as `seed.<name>.<field>` in templates:

```yaml
context_scope:
  drop:
    - seed.exam_syllabus
```

## Reserved Action Names

Action names cannot use reserved namespaces. The following names are disallowed because they're used for built-in functionality and config directives:

| Reserved Name | Purpose |
|---------------|---------|
| `source` | Input data namespace |
| `loop` | Loop iteration namespace |
| `workflow` | Workflow metadata namespace |
| `seed` | Seed data namespace |
| `prompt` | Prompt template namespace |
| `schema` | Schema definition namespace |
| `context_scope` | Config directive (not a runtime namespace) |
| `action` | Action metadata namespace |

These namespaces (except `context_scope`) are always available in templates without explicit dependency declarations.

## Example from qanalabs

### Configuration

```yaml
defaults:
  context_scope:
    seed_data:
      exam_syllabus: $file:mcp_qanalabs_syllabus.json
```

### Seed Data Structure

```json
{
  "exam_name": "Model Context Protocol Specialist",
  "certification": "MCP Specialist (MCP-101)",
  "platform_name": "Model Context Protocol",
  "effective_date": "2025-11-08",
  "audience_profile": {
    "description": "As a Model Context Protocol Specialist...",
    "responsibilities": ["Design and implement MCP server architectures..."],
    "required_knowledge": ["Strong understanding of the MCP specification..."]
  },
  "skills_measured": [
    {
      "skill_area": "Understand MCP Architecture and Core Concepts",
      "weight": "25–30%",
      "sections": [
        {
          "section_name": "Understand the MCP protocol fundamentals",
          "objectives": [
            "Explain the purpose and benefits of MCP",
            "Describe the client-server architecture"
          ]
        }
      ]
    }
  ]
}
```

### Usage in Prompts

```yaml
- name: extract_facts
  prompt: |
    Extract facts relevant to the {{ seed.exam_syllabus.exam_name }} exam.

    Focus on these learning objectives:
    {% for skill in seed.exam_syllabus.skills_measured %}
    ## {{ skill.skill_area }}
    {% for section in skill.sections %}
    ### {{ section.section_name }}
    {% for objective in section.objectives %}
    - {{ objective }}
    {% endfor %}
    {% endfor %}
    {% endfor %}

    Source content:
    {{ source.page_content }}
```

## Nested Field Access

Access deeply nested seed data with dot notation:

```yaml
prompt: |
  Exam duration: {{ seed.exam_syllabus.exam_details.duration_minutes }} minutes
  Passing score: {{ seed.exam_syllabus.exam_details.passing_score }}

  Prerequisites:
  {% for prereq in seed.exam_syllabus.exam_details.prerequisites %}
  - {{ prereq }}
  {% endfor %}
```

## Multiple Seed Data Files

Load multiple reference files:

```yaml
defaults:
  context_scope:
    seed_data:
      syllabus: $file:exam_syllabus.json
      rubric: $file:grading_rubric.yaml
      categories: $file:lookups/question_categories.json
```

Access each with its assigned name:

```yaml
prompt: |
  Exam: {{ seed.syllabus.exam_name }}
  Grading criteria: {{ seed.rubric.criteria }}
  Category: {{ seed.categories.technical }}
```

## Seed Data vs Source Data

You might wonder when to use seed data versus source data. Here's the key distinction:

| Aspect | Seed Data | Source Data |
|--------|-----------|-------------|
| **Scope** | Same for all records | Different per record |
| **Loaded from** | `seed_data/` directory | `agent_io/staging/` directory |
| **Reference** | `{{ seed.name.field }}` | `{{ source.field }}` |
| **Purpose** | Static reference data | Input data to process |
| **When loaded** | Once at agentic workflow start | Per record execution |

Use seed data for information that applies uniformly across all records. Use source data for the actual content you're processing.

## Best Practices

Let's walk through patterns that make seed data manageable and effective.

### 1. Keep Seed Data Focused

```yaml
# Good: Specific, focused seed files
seed_data:
  exam_syllabus: $file:aws_solutions_architect.json
  scoring_rubric: $file:question_scoring.yaml

# Avoid: Monolithic seed files with everything
seed_data:
  everything: $file:all_config.json
```

### 2. Use Descriptive Names

```yaml
# Good: Clear what each seed contains
seed_data:
  grading_criteria: $file:grading.yaml
  difficulty_levels: $file:difficulty.json

# Avoid: Vague names
seed_data:
  data1: $file:file1.json
  config: $file:config.yaml
```

### 3. Version Seed Data

Include version or effective date in seed files:

```json
{
  "version": "2.0.0",
  "effective_date": "2025-01-01",
  "exam_name": "..."
}
```

### 4. Validate Seed Data Structure

Reference expected fields in prompts:

```yaml
prompt: |
  {% if seed.syllabus.version %}
  Using syllabus version: {{ seed.syllabus.version }}
  {% endif %}
```

## Error Handling

### Missing Seed File

```
ConfigurationError: Seed data file not found: seed_data/missing.json
```

Ensure the file exists in the workflow's `seed_data/` directory.

### Invalid JSON/YAML

```
ParseError: Failed to parse seed data 'exam_syllabus': Invalid JSON at line 15
```

Validate seed data files are properly formatted.

### Missing Field Reference

```
TemplateError: 'seed.exam_syllabus.nonexistent_field' is undefined
```

Check the seed data structure matches your field references.

## Agentic Workflow-Level vs Action-Level

Seed data is typically defined at the defaults level, which makes it available to all actions:

```yaml
# Workflow-level (recommended)
defaults:
  context_scope:
    seed_data:
      syllabus: $file:syllabus.json
```

But can also be specified per-action:

```yaml
actions:
  - name: specialized_action
    context_scope:
      seed_data:
        special_data: $file:special.json
```

Action-level seed data is merged with agentic workflow-level defaults.

## Performance Considerations

:::warning
Seed data is loaded into memory for every action that uses it. Very large seed files (100MB+) can impact performance. Consider splitting monolithic reference data into focused files that actions can load selectively.
:::

- Seed data is loaded once per agentic workflow execution
- Large seed files increase memory usage
- Complex nested structures increase template rendering time
- Consider splitting very large reference data into focused files
