---
title: Seed Data
sidebar_position: 4
---

# Seed Data

Seed data loads static reference data (syllabi, rubrics, lookups) into the workflow context. All actions can use the data, and you do not repeat the data in each action.

## Configuration

```yaml
defaults:
  context_scope:
    seed:
      exam_syllabus: $file:syllabus.json
      grading_rubric: $file:rubric.yaml
```

A FILE tool and a FILE HITL action also get the declared seed. If you observe `seed.rules`, each record of the tool input holds `rules`. `rules` is a flat key, like any observed field. A `drop` under `seed` (`drop: [seed.rules.internal_notes]`) applies to that record in the same way as it applies to a prompt. The seed goes only into the tool input, never into a stored record. A record that the tool returns is stored without the entries that the seed supplied.

### File Reference Syntax

| Syntax | Description |
|--------|-------------|
| `$file:filename.json` | Loads a JSON file from the seed data directory |
| `$file:filename.yaml` | Loads a YAML file (`.yaml` or `.yml`) from the seed data directory |
| `$file:filename.csv` | Loads a CSV file as a list of rows. Each row is a mapping of column name to text. |
| `$file:filename.md` | Loads a Markdown file or a `.txt` file as one string |
| `$file:path/to/file.json` | Loads a file from a subdirectory in the seed data directory |

Pre-flight reads each seed file in the same way as the run. Thus a file that pre-flight
accepts loads in the same way at run time. A malformed file is refused before the run, with
the parse error of its format. A CSV file may start with a UTF-8 byte order mark. The byte
order mark is not part of the name of the first column. A quoted cell keeps its line breaks
as written. Read a CSV row by position: `{{ seed.codes[0].code }}`.

### Custom Directory Name

The default seed data directory is `seed_data/`. You can change it in `agent_actions.yml`:

```yaml
seed_data_path: reference_data   # defaults to "seed_data" if omitted
```

The value is a folder name. If the value has a path separator or `..`, the value is ignored with a warning, and `seed_data` is used.

### Shared Folders

A file that several workflows read is kept one time, in a shared folder. List the shared folders in `agent_actions.yml`. Give each folder relative to the project root:

```yaml
seed_data_paths: [shared_seeds]
```

The file of each `$file:` reference is looked for in this order. The reference resolves to the first folder that holds the file:

1. The folder of the workflow (`agent_workflow/<workflow>/seed_data/`, or the `seed_data_path` name)
2. The project folder (`seed_data/` at the project root, or the `seed_data_path` name)
3. Each folder of `seed_data_paths`, in order

Thus a workflow can keep its own `syllabus.json` and read `question_design_rules.json` from `shared_seeds/` with no copy. The rules are:

- The file of the workflow has priority over a shared file of the same name. `agac inspect context` shows the shared file that it hides.
- If two shared folders hold the same name, the result is an error that names the two folders. The project folder counts as one shared folder. There is no silent selection. Keep the file in one folder.
- A listed folder that does not exist, or that is outside the project root, is a configuration error.
- If no folder holds the file, the result is an error that lists each folder that was searched.

In the editor, go-to-definition on a `$file:` reference opens the same file that the run reads.

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

A [guard](../execution/guards.md#context-access) reads the same seed data. Thus a condition can
compare a record field with a seed value:

```yaml
guard:
  condition: 'score_review.score >= seed.thresholds.min_score'
  on_false: filter
```

A prompt or a guard that reads a seed key that its action does not declare is refused before the run.
Pre-flight also shows a warning when a field such as `seed.rubric.criteria` is missing from a JSON or
YAML mapping. Pre-flight does not check past a list, for example the rows of a CSV file or a JSON array.

## Multiple Seed Files

```yaml
defaults:
  context_scope:
    seed:
      syllabus: $file:exam_syllabus.json
      rubric: $file:grading_rubric.yaml
```

Use the assigned name to get each file: `{{ seed.syllabus.exam_name }}`, `{{ seed.rubric.criteria }}`.

## Choosing a Seed File per Record

A seed key can name one file for each value of a staged record field. Each record then gets the file for its own value. The prompt reads `{{ seed.syllabus }}` as before.

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

The first record renders with `dbt_syllabus.json` as `seed.syllabus`. The second record renders with `snowflake_syllabus.json`. Both records get `question_design_rules.json` as `seed.rules`. A seed key may select by any staged field (a customer, a language, a product line). One action may have several selected keys, each with its own field.

Rules:

- `select_by` is `source.<field>`. The field does not have to be observed. The selection reads the record before `observe`/`drop` apply.
- The value of the record must be a string or an integer. The value is compared with the map keys as text. Thus `1` and `"1"` both select the file under `1:`.
- A record with a value that is missing, null, of another type, or not in the map stops the run before any model call. Staging checks each record of each input file against the selected seeds of each action. Pre-flight checks that each file in the map exists. It also checks that template references such as `seed.syllabus.domains` exist in each of these files.

```
Seed 'syllabus' in action 'generate_question': record value 'snowflak' for 'source.exam' is not in the file map. Known values: dbt, snowflake. (staging/pages.json, record 3)
```

For a record, a guard reads the same file as the prompt. Thus `seed.syllabus.domains` in a guard clause is the syllabus of that record. There is no default file. A value that the map does not name is an error, never a silent fallback. `agac inspect context -a <workflow> <action>` shows the file that each value gets.

## Seed Data vs Source Data

| Aspect | Seed Data | Source Data |
|--------|-----------|-------------|
| **Scope** | The same for all records, or one file for each value of a record field | Different for each record |
| **Loaded from** | `seed_data/` directory | `agent_io/staging/` directory |
| **Reference** | `{{ seed.name.field }}` | `{{ source.field }}` |

## Best Practices

1. **Keep seed data focused**: Use specific files, not monolithic configuration files.
2. **Use descriptive names**: Use `grading_criteria`, not `data1`.
3. **Version seed data**: Include version/effective_date in the seed files.

## Workflow-Level vs Action-Level

Workflow-level (recommended):

```yaml
defaults:
  context_scope:
    seed:
      syllabus: $file:syllabus.json
```

Per-action (merged with the defaults):

```yaml
actions:
  - name: specialized_action
    context_scope:
      seed:
        special_data: $file:special.json
```
