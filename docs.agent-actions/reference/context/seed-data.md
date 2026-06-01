---
title: Seed Data
sidebar_position: 4
---

# Seed Data

Seed Data loads static reference data (syllabi, rubrics, lookups) into workflow context—available to all actions without repetition.

## Configuration

```yaml
defaults:
  context_scope:
    seed_path:
      exam_syllabus: $file:syllabus.json
      grading_rubric: $file:rubric.yaml
```

### File Reference Syntax

| Syntax | Description |
|--------|-------------|
| `$file:filename.json` | Load JSON file from the seed data directory |
| `$file:filename.yaml` | Load YAML file from the seed data directory |
| `$file:path/to/file.json` | Load from subdirectory within the seed data directory |

### Custom Directory Name

The seed data directory defaults to `seed_data/`. You can change it in `agent_actions.yml`:

```yaml
seed_data_path: reference_data   # defaults to "seed_data" if omitted
```

## Directory Structure

```
my_workflow/
├── agent_config/
│   └── my_workflow.yml
├── agent_io/
└── seed_data/           # Seed data files here (or your custom name)
    ├── syllabus.json
    └── rubric.yaml
```

## Accessing Seed Data

Use the `seed` prefix in field references:

```yaml
prompt: |
  Exam: {{ seed.exam_syllabus.exam_name }}
  {% for skill in seed.exam_syllabus.skills_measured %}
  - {{ skill.skill_area }}
  {% endfor %}
```

## Multiple Seed Files

```yaml
defaults:
  context_scope:
    seed_path:
      syllabus: $file:exam_syllabus.json
      rubric: $file:grading_rubric.yaml
```

Access each with its assigned name: `{{ seed.syllabus.exam_name }}`, `{{ seed.rubric.criteria }}`.

## Seed Data vs Source Data

| Aspect | Seed Data | Source Data |
|--------|-----------|-------------|
| **Scope** | Same for all records | Different per record |
| **Loaded from** | `seed_data/` directory | `agent_io/staging/` directory |
| **Reference** | `{{ seed.name.field }}` | `{{ source.field }}` |

## Best Practices

1. **Keep seed data focused**: Use specific files, not monolithic configs
2. **Use descriptive names**: `grading_criteria` not `data1`
3. **Version seed data**: Include version/effective_date in seed files

## Workflow-Level vs Action-Level

Workflow-level (recommended):

```yaml
defaults:
  context_scope:
    seed_path:
      syllabus: $file:syllabus.json
```

Per-action (merged with defaults):

```yaml
actions:
  - name: specialized_action
    context_scope:
      seed_path:
        special_data: $file:special.json
```
