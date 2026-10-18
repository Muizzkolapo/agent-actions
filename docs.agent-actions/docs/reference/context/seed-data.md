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
    seed:
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

### Shared Folders

A file several workflows read lives once, in a shared folder. List shared folders in `agent_actions.yml`, relative to the project root:

```yaml
seed_data_paths: [shared_seeds]
```

Each `$file:` reference is looked for in this order, and resolves to the first folder that holds it:

1. the workflow's own folder (`agent_workflow/<workflow>/seed_data/`)
2. the project folder (`seed_data/` at the project root, or the `seed_data_path` name)
3. each folder of `seed_data_paths`, in order

So a workflow can keep its own `syllabus.json` and read `question_design_rules.json` from `shared_seeds/` with no copy. Rules:

- The workflow's file wins over a shared file of the same name. `agac inspect context` shows the shared file it hides.
- A name held by two shared folders (the project folder counts as one) is an error that names both. There is no silent pick: keep the file in one folder.
- A listed folder that does not exist, or that is outside the project root, is a configuration error.
- A file found nowhere is an error that lists every folder searched.

The editor's go-to-definition on a `$file:` reference opens the same file the run reads.

## Directory Structure

```
my_project/
├── agent_actions.yml                # seed_data_paths: [shared_seeds]
├── shared_seeds/
│   └── question_design_rules.json   # read by every workflow that names it
└── agent_workflow/my_workflow/
    ├── agent_config/
    │   └── my_workflow.yml
    ├── agent_io/
    └── seed_data/                   # this workflow's own files (or your custom name)
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

A [guard](../execution/guards.md#context-access) reads the same seed data, so a condition can
compare a record against a reference file:

```yaml
guard:
  condition: 'score_review.score >= seed.thresholds.min_score'
  on_false: filter
```

A prompt or guard that reads a seed key its action does not declare is refused before the run.

## Multiple Seed Files

```yaml
defaults:
  context_scope:
    seed:
      syllabus: $file:exam_syllabus.json
      rubric: $file:grading_rubric.yaml
```

Access each with its assigned name: `{{ seed.syllabus.exam_name }}`, `{{ seed.rubric.criteria }}`.

## Choosing a Seed File per Record

A seed key can name one file per value of a staged record field. Each record then gets the file for its own value, and the prompt reads `{{ seed.syllabus }}` as before.

```yaml
defaults:
  context_scope:
    seed:
      rules: $file:question_design_rules.json      # one file for every record
      syllabus:
        select_by: source.exam                     # a field of the staged record
        files:
          dbt: $file:dbt_syllabus.json
          snowflake: $file:snowflake_syllabus.json
```

```json
[
  { "exam": "dbt",       "title": "Incremental models", "content": "..." },
  { "exam": "snowflake", "title": "Micro-partitions",   "content": "..." }
]
```

The first record renders with `dbt_syllabus.json` as `seed.syllabus`; the second with `snowflake_syllabus.json`. Both get `question_design_rules.json` as `seed.rules`. A seed key may select by any staged field (a customer, a language, a product line), and one action may have several selected keys, each with its own field.

Rules:

- `select_by` is `source.<field>`. The field does not have to be observed; selection reads the record before `observe`/`drop` apply.
- The record's value must be a string or an integer. It is matched against the map keys as text, so `1` and `"1"` both pick the file under `1:`.
- A record whose value is missing, null, of another type, or not in the map stops the run before any model call. Staging checks every row of every input file against every action's selected seeds; preflight checks that every file in the map exists and that template references such as `seed.syllabus.domains` exist in every one of them.

```
Seed 'syllabus' in action 'generate_question': record value 'snowflak' for 'source.exam' is not in the file map. Known values: dbt, snowflake. (staging/pages.json, record 3)
```

A guard reads the same file the prompt does for a record, so `seed.syllabus.domains` in a guard clause is the record's own syllabus. There is no default file: a value the map does not name is an error, never a silent fallback. `agac inspect context <workflow> <action>` shows which file each value gets.

## Seed Data vs Source Data

| Aspect | Seed Data | Source Data |
|--------|-----------|-------------|
| **Scope** | Same for all records, or one file per value of a record field | Different per record |
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
    seed:
      syllabus: $file:syllabus.json
```

Per-action (merged with defaults):

```yaml
actions:
  - name: specialized_action
    context_scope:
      seed:
        special_data: $file:special.json
```
