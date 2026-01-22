# Documentation Validation Test Plan

Validate Agent Actions documentation against the real `qanalabs_quiz_gen` workflow.

**Test Project:** `/Users/muizz/Documents/codeshop/qanalabs/qanalabs-actions/qanalabs`
**Workflow:** `qanalabs_quiz_gen`

---

## Test Categories

| Category | Features to Test | Coverage |
|----------|------------------|----------|
| Configuration | Defaults, action config, model settings | High |
| Context | Field references, context_scope, seed data | High |
| Execution | Guards, dependencies, granularity | High |
| Tools | UDFs, @udf_tool decorator, TypedDict | High |
| Data I/O | staging/, source/, target/ structure | High |
| Validation | Schemas, reprompting | High |
| CLI | run, schema, inspect commands | High |

---

## Test 1: Directory Structure (Data I/O)

**Documentation:** `reference/data-io/index.md`

**Claim:** Input data goes in `staging/`, `source/` is metadata, outputs go to `target/`

**Test:**
```bash
cd /Users/muizz/Documents/codeshop/qanalabs/qanalabs-actions/qanalabs
ls -la agent_workflow/qanalabs_quiz_gen/agent_io/
```

**Expected:**
- `staging/` contains input JSON files (combined_scraped_sample.json)
- `source/` contains metadata/tracking
- `target/` contains action output folders (node_0_extract_raw_qa/, etc.)

**Verify:** [ ] staging/ has input data [ ] target/ has node folders [ ] Filenames preserved across stages

---

## Test 2: Workflow Configuration (Configuration)

**Documentation:** `reference/configuration/index.md`, `reference/configuration/defaults.md`

**Claim:** Defaults cascade to all actions, actions can override

**Test:**
```bash
cat agent_workflow/qanalabs_quiz_gen/agent_config/qanalabs_quiz_gen.yml | head -30
```

**Expected in qanalabs_quiz_gen.yml:**
```yaml
defaults:
  model_vendor: openai
  model_name: gpt-5-mini
  json_mode: true
  run_mode: online
  granularity: record
```

**Verify:** [ ] Defaults block exists [ ] Actions inherit defaults [ ] Individual actions can override

---

## Test 3: Field References (Context)

**Documentation:** `reference/context/field-references.md`

**Claim:** Access upstream outputs via `{{ action_name.field }}`

**Test in qanalabs_quiz_gen.yml:**
```yaml
# Action: write_scenario_question references classify_question_type
prompt: |
  Question type: {{ classify_question_type.question_type }}

# Action: add_answer_text references fix_options_format
prompt: |
  Options: {{ fix_options_format.options }}
  Answer: {{ write_scenario_question.answer }}
```

**Verify:** [ ] Field references resolve correctly [ ] Nested fields work (e.g., `{{ seed.exam_syllabus.exam_name }}`)

---

## Test 4: Seed Data (Context)

**Documentation:** `reference/context/seed-data.md`

**Claim:** Static reference data loaded from `seed_data/` directory, accessed via `{{ seed.name }}`

**Test:**
```bash
ls agent_workflow/qanalabs_quiz_gen/seed_data/
cat agent_workflow/qanalabs_quiz_gen/seed_data/mcp_qanalabs_syllabus.json | head -20
```

**In workflow config:**
```yaml
seed_data:
  exam_syllabus: $file:mcp_qanalabs_syllabus.json
```

**In prompts:**
```jinja2
{{ seed.exam_syllabus.exam_name }}
{{ seed.exam_syllabus.skills_measured }}
```

**Verify:** [ ] Seed data loads from seed_data/ [ ] `{{ seed.X }}` syntax works [ ] Same data available to all actions

---

## Test 5: Guards (Execution)

**Documentation:** `reference/execution/guards.md`

**Claim:** Guards skip/filter actions based on conditions

**Test in qanalabs_quiz_gen.yml:**
```yaml
- name: generate_feynman_explanation
  guard:
    condition: "filter_low_quality.question_status == 'KEEP'"
    on_false: filter
```

**Verify:** [ ] Guard condition evaluates correctly [ ] `on_false: filter` filters records [ ] `on_false: skip` skips entire action [ ] Filtered records don't proceed downstream

---

## Test 6: UDFs with @udf_tool (Tools)

**Documentation:** `reference/tools/udf-decorator.md`, `reference/tools/index.md`

**Claim:** Python functions decorated with `@udf_tool` become available as actions

**Test:**
```bash
ls tools/qanalabs-quiz-gen/
cat tools/qanalabs-quiz-gen/flatten_questions.py | head -40
```

**Expected pattern:**
```python
from agent_actions.tools.udf_tool import udf_tool
from typing import TypedDict

class FlattenInput(TypedDict):
    questions: list

class FlattenOutput(TypedDict):
    flattened: list

@udf_tool(
    input_type=FlattenInput,
    output_type=FlattenOutput,
    granularity="file"
)
def flatten_questions(data: FlattenInput) -> FlattenOutput:
    ...
```

**In workflow:**
```yaml
- name: flatten_questions
  kind: tool
  impl: flatten_questions
  granularity: file
```

**Verify:** [ ] @udf_tool decorator works [ ] TypedDict input/output types [ ] granularity parameter (record/file) [ ] impl references function name

---

## Test 7: Granularity (Execution)

**Documentation:** `reference/execution/granularity.md`

**Claim:** `record` processes items individually, `file` processes entire file

**Test in qanalabs_quiz_gen.yml:**
```yaml
# Record granularity (default for LLM actions)
- name: classify_question_type
  granularity: record

# File granularity (for aggregation UDFs)
- name: flatten_questions
  kind: tool
  impl: flatten_questions
  granularity: file
```

**Verify:** [ ] Record-level actions process each item [ ] File-level actions receive all items [ ] Granularity affects data shape passed to action

---

## Test 8: Dependencies (Execution)

**Documentation:** `reference/execution/workflow-dependencies.md`

**Claim:** Actions declare dependencies, engine resolves execution order

**Test in qanalabs_quiz_gen.yml:**
```yaml
- name: extract_raw_qa
  # No dependencies - runs first

- name: flatten_questions
  dependencies: [extract_raw_qa]

- name: classify_question_type
  dependencies: [flatten_questions]

# Later action with multiple dependencies
- name: reconstruct_options
  dependencies: [add_answer_text, generate_distractor_1, generate_distractor_2, generate_distractor_3]
```

**Verify:** [ ] Dependencies respected [ ] Parallel execution of independent actions [ ] No cycles in dependency graph

---

## Test 9: Schemas (Validation)

**Documentation:** `reference/schemas/index.md`, `reference/validation/index.md`

**Claim:** JSON Schema validates action outputs, invalid responses trigger reprompting

**Test:**
```bash
ls schema/
cat schema/extract_raw_qa.yml
```

**In workflow:**
```yaml
- name: extract_raw_qa
  schema: extract_raw_qa
```

**Verify:** [ ] Schema files in schema/ directory [ ] YAML and JSON schemas supported [ ] Schema reference in action config [ ] Invalid outputs rejected

---

## Test 10: Reprompting (Validation)

**Documentation:** `reference/validation/reprompting.md`

**Claim:** Failed schema validation triggers automatic retry with feedback

**Test in workflow:**
```yaml
defaults:
  reprompt: smart  # or basic, thorough
```

**Verify:** [ ] Reprompt presets work (basic, smart, thorough) [ ] Failed validation triggers retry [ ] Retry includes error feedback

---

## Test 11: Prompt Templates (Prompts)

**Documentation:** `reference/prompts/prompt-store.md`

**Claim:** Prompts stored in `prompt_store/` directory, referenced via `$prompts.name`

**Test:**
```bash
ls prompt_store/
head -50 prompt_store/qanalabs_quiz_gen.md
```

**In workflow:**
```yaml
- name: extract_raw_qa
  prompt: $prompts.Extract_Raw_QA
```

**Verify:** [ ] Prompt store directory exists [ ] `$prompts.X` syntax resolves [ ] Markdown files with `# Prompt_Name` headers [ ] Jinja2 templating in prompts

---

## Test 12: Context Scope (Context)

**Documentation:** `reference/context/context-scope.md`

**Claim:** `observe`, `drop`, `passthrough` control data flow

**Test in qanalabs_quiz_gen.yml:**
```yaml
- name: some_action
  context_scope:
    observe:
      - previous_action.specific_field
    passthrough:
      - source.id
    drop:
      - large_content_field
```

**Verify:** [ ] observe limits visible fields [ ] passthrough preserves fields in output [ ] drop excludes fields from context

---

## Test 13: CLI Commands

**Documentation:** `cli-reference/run.md`, `cli-reference/inspect.md`, `cli-reference/batch.md`

### Test 13a: Validate Only
```bash
cd /Users/muizz/Documents/codeshop/qanalabs/qanalabs-actions/qanalabs
agac run -a qanalabs_quiz_gen --validate-only
```

**Verify:** [ ] Pre-flight validation runs [ ] No API calls made [ ] Configuration errors caught

### Test 13b: Schema Inspection
```bash
agac schema -a qanalabs_quiz_gen
agac schema -a qanalabs_quiz_gen --verbose
```

**Verify:** [ ] Shows input/output schemas per action [ ] Field flow visualization works

### Test 13c: UDF Discovery
```bash
agac list-udfs -u tools/qanalabs-quiz-gen/
agac validate-udfs -a qanalabs_quiz_gen -u tools/qanalabs-quiz-gen/
```

**Verify:** [ ] UDFs discovered from directory [ ] References validated against config

### Test 13d: Field Flow Inspection
```bash
agac inspect field-flow -a qanalabs_quiz_gen
agac inspect signatures -a qanalabs_quiz_gen
agac inspect conflicts -a qanalabs_quiz_gen
```

**Verify:** [ ] Field dependencies traced [ ] Conflicts detected if any

---

## Test 14: Run Modes (Execution)

**Documentation:** `reference/execution/run-modes.md`

**Claim:** `online` for real-time, `batch` for async processing

**Test:**
```yaml
defaults:
  run_mode: online  # or batch
```

```bash
# Online mode
agac run -a qanalabs_quiz_gen

# Batch mode
agac batch submit -a qanalabs_quiz_gen
agac batch status -a qanalabs_quiz_gen
```

**Verify:** [ ] Online mode executes immediately [ ] Batch mode submits async job [ ] Status tracking works

---

## Test 15: Artifacts & Tracking (Execution)

**Documentation:** `reference/execution/artifacts.md`

**Claim:** Run history in `artefact/runs.json`, status in `.agent_status.json`

**Test:**
```bash
cat artefact/runs.json | head -50
cat agent_workflow/qanalabs_quiz_gen/agent_io/.agent_status.json
```

**Verify:** [ ] runs.json tracks execution history [ ] .agent_status.json tracks action status [ ] Resumable execution works

---

## Test 16: Error Messages (Troubleshooting)

**Documentation:** `cli-reference/troubleshooting.md`, `reference/troubleshooting.md`

**Test:**
```bash
# Trigger an error intentionally
agac run -a qanalabs_quiz_gen --debug --verbose
```

**Verify:** [ ] Error messages are actionable [ ] Debug mode shows full traceback [ ] Context fields (source_guid, action_name) included

---

## Test Execution Checklist

Run tests in order:

| # | Test | Command | Pass/Fail |
|---|------|---------|-----------|
| 1 | Directory Structure | `ls agent_io/` | [ ] |
| 2 | Configuration | `cat agent_config/*.yml` | [ ] |
| 3 | Field References | Inspect prompts | [ ] |
| 4 | Seed Data | `ls seed_data/` | [ ] |
| 5 | Guards | Run with filtered records | [ ] |
| 6 | UDFs | `agac list-udfs` | [ ] |
| 7 | Granularity | Check record vs file actions | [ ] |
| 8 | Dependencies | `agac inspect signatures` | [ ] |
| 9 | Schemas | `agac schema -a workflow` | [ ] |
| 10 | Reprompting | Trigger schema failure | [ ] |
| 11 | Prompt Templates | Check $prompts resolution | [ ] |
| 12 | Context Scope | Check observe/passthrough | [ ] |
| 13 | CLI Commands | Run each command | [ ] |
| 14 | Run Modes | Test online and batch | [ ] |
| 15 | Artifacts | Check runs.json | [ ] |
| 16 | Error Messages | Trigger error with --debug | [ ] |

---

## Documentation Gaps to Check

After running tests, note any:

1. **Missing features** - Workflow uses something not documented
2. **Incorrect claims** - Documentation says X but tool does Y
3. **Unclear explanations** - Had to guess how feature works
4. **Missing examples** - Feature documented but no usage example

---

## Feature Coverage Matrix

| Documented Feature | Used in qanalabs_quiz_gen | Test # |
|--------------------|---------------------------|--------|
| staging/ as input | Yes | 1 |
| source/ as metadata | Yes | 1 |
| target/ outputs | Yes | 1 |
| defaults block | Yes | 2 |
| field references | Yes | 3 |
| seed_data | Yes | 4 |
| guards (filter) | Yes | 5 |
| guards (skip) | Needs test | 5 |
| @udf_tool | Yes | 6 |
| TypedDict schemas | Yes | 6 |
| granularity: record | Yes | 7 |
| granularity: file | Yes | 7 |
| dependencies | Yes | 8 |
| JSON schemas | Yes | 9 |
| YAML schemas | Yes | 9 |
| reprompt presets | Needs test | 10 |
| prompt_store | Yes | 11 |
| $prompts.X syntax | Yes | 11 |
| context_scope.observe | Needs verify | 12 |
| context_scope.passthrough | Needs verify | 12 |
| context_scope.drop | Needs verify | 12 |
| run_mode: online | Yes | 14 |
| run_mode: batch | Needs test | 14 |
| runs.json | Yes | 15 |
| .agent_status.json | Yes | 15 |









- we need to test in batch vs onlone eg reprompt
- validate non json