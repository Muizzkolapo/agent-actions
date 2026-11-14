---
title: Troubleshooting
sidebar_position: 10
---

# Troubleshooting

:::note[Storage backend]
Action outputs are in SQLite at `agent_io/store/<workflow>.db`, in the table `target_data`.
:::

This guide helps you debug and correct common errors in your workflow. It gives the error types, their causes and their fixes.

## Error Types

### SchemaValidationError

This error occurs when a tool returns data that the `schema:` of the action does not accept. The framework checks each item that a tool returns against that schema.

```
Output schema validation failed for UDF 'add_answer_text' (item 0) at target_word_counts -> correct_answer_words: 18 is not of type 'string'
```

`(item N)` appears when the tool returns a list. `at root` means that the failure is on the item itself, not on one field.

**Context Fields:**

| Field | Description | Example |
|-------|-------------|---------|
| `error_path` | The path to the field that failed, joined by `->` (`root` for the item itself) | `target_word_counts -> correct_answer_words` |
| `failed_value` | The value that the framework received | `18`, `'some text'`, `['a', 'b']` |
| `schema_constraint` | The expected schema rule | `{'type': 'string'}` |
| `function` | The tool that failed | `add_answer_text` |
| `validation_type` | The side that the framework validated | `output` |
| `item_index` | The position in the returned list, or `None` | `0` |

### RecordContextError (Record Namespace)

This error occurs when a downstream action tries to read fields from the output of an upstream action, but the expected fields are missing. Typically, this means that the upstream action stored corrupted or empty data.

```
[RECORD NAMESPACE] 'generate_optimal_code': declared fields ['explanation'] not found. Available: ['optimal_code']
```

If none of the declared fields exist in the upstream output, the framework logs a warning instead. Then the framework treats the upstream namespace as null for that record. A prompt that reads a field from that namespace then fails. The error names the reason:

```
[OBSERVE NULL-SAFE] 'generate_optimal_code': namespace has zero overlap with declared fields ['optimal_code'] (actual keys: ['additionalProperties', 'properties', 'required', 'title', 'type']) — treating as null
```

**Common causes:**

| Cause | What happened | Fix |
|-------|--------------|-----|
| Schema-echo | The LLM returned the JSON Schema definition, not data. | Add `expect: {repair: auto}`. The validator detects schema-echo payloads, and the repair loop generates the output again. |
| Empty object | The LLM returned `{}`. | Use the same fix. The framework rejects an empty object when the schema declares fields. |
| Existing poison | Bad data from a previous run is already in `target_data`. | Run the upstream action again with a repair policy. Or clean the SQLite row manually. |

**Behavior:** If one record has incomplete namespace data, the framework logs a WARNING (`Record <source_guid> prep failed (context incomplete)`). The framework stores that record as failed, and continues with the remaining records in the file. One bad record does not fail a full file of valid records.

### AgentActionsError

This error is a top-level workflow failure. It wraps other errors to give the full context of the failure.

```
AgentActionsError: Error generating target: <underlying error>
[Context: file_path=/path/to/data.json, agent_name=my_workflow, ...]
```

## Common Errors & Fixes

This section gives the most common errors and their fixes.

### Template Field Reference Error {/* #template-variable-error */}

**Error:**
```
Template rendering failed for agent 'write_question'

  Reference: classify.question_type
  Namespace 'classify' exists: YES
  Field 'question_type' in namespace: NO
  Available in 'classify': question_category, difficulty_level, tags

  Did you mean 'classify.question_category'?

Fix: Check that 'classify' produces the referenced field.
```

**Cause:** The template refers to a field that does not exist in the namespace. The error message shows:
- Whether the namespace (for example, `classify`) exists
- Whether the field exists in that namespace
- The available fields that you can use in its place
- A suggestion, if a similar field name exists (typo detection)

**Fix options:**

1. **Check the field name.** If the field name is a typo, use the suggested alternative.
2. **Verify the dependency.** Make sure that the action that produces this field is in your `dependencies` list.
3. **Check the output of the upstream action.** Make sure that the action produces the expected field.

---

### Source Data Structure Mismatch

**Error:**
```
A staged input must be rows; found dict. Wrap it in an array: [ ... ].
```

**Cause:** The top level of the staging file is a wrapper object, not the list of records that staging reads. This occurs when your JSON file has metadata beside the actual records.

**Wrong format:**
```json
{
  "exam_name": "My Exam",
  "items": [
    {"id": "1", "content": "..."},
    {"id": "2", "content": "..."}
  ]
}
```

The prompt expects `{{ source.content }}`, but `source` is the wrapper, not the individual records.

**Correct format:**
```json
[
  {"id": "1", "content": "..."},
  {"id": "2", "content": "..."}
]
```

**Fix options:**

1. **Restructure the input.** Extract the array into the staging file. Usually, you want this
   option: one record for each item, so `{{ source.content }}` resolves.
   ```python
   data = json.load(open("wrapper.json"))
   records = data["items"]
   json.dump(records, open("staging/data.json", "w"))
   ```

2. **Keep the wrapper as one record.** If the document really is one record, put it in an
   array. The document then stages as one record whose fields are `exam_name` and `items`.
   The prompt loops over the array inside that record:
   ```json
   [
     {
       "exam_name": "My Exam",
       "items": [{"id": "1", "content": "..."}]
     }
   ]
   ```
   ```jinja2
   {% for item in source.items %}
     {{ item.content }}
   {% endfor %}
   ```

3. **Add a preprocessing action.** If the file is wrapped as in option 2, a first action can
   expand the one record into many records:
   ```yaml
   - name: extract_items
     kind: tool
     impl: extract_items_from_wrapper   # returns a list: one row per item
   ```

---

### Type Mismatch

**Error:**
```
18 is not of type 'string'
```

**Cause:** The tool returned an integer where the `schema:` of the action declares a string.

**Fix:** Convert the value in your tool:
```python
data['field'] = str(data['field'])
```

Or change the type of the field in the `schema:` of the action.

---

### Array vs String Mismatch

**Error:**
```
'Audit client code...' is not of type 'array'
```

**Cause:** The value is a string where the schema expects an array.

**Fix:** Normalize the value in your tool:
```python
answer_text = data["upstream_action"]["answer_text"]
if isinstance(answer_text, str):
    answer_text = [answer_text]
```

---

### Unexpected Field

**Error:**
```
'new_field' was unexpected
```

The full message is `Additional properties are not allowed ('new_field' was unexpected)`.

**Cause:** The tool returned a field that the `schema:` of the action does not declare.

**Fix:** Declare the field in the `schema:` of the action. Or remove the field from the return value of the tool.

---

### Mixed-Type Dict Values

**Error:**
```
'greater_than' is not of type 'integer'
```

**Cause:** The schema limits the values of an object field to one type (for example `additionalProperties: {type: integer}`), but the tool returned a string value.

**Fix:** Return values of the declared type. Or, in the schema file, change the field to the less strict plain `type: object`.

---

### Missing Required Field

**Error:**
```
'question' is a required property
```

**Cause:** The `schema:` of the action requires the field, but the tool did not return it. If the tool sets the field only inside a branch, pre-flight usually refuses the workflow before it runs. Pre-flight then names the line. See [Required Output Field Set Only in a Branch](../reference/tools/index.md#required-output-field-set-only-in-a-branch).

**Fix:** Make sure that the tool returns all required fields:
```python
@udf_tool()
def my_function(data: dict) -> dict:
    return {
        'question': data["upstream_action"]["question"],
        'processed': True
    }
```

Or, for LLM actions, enable repair:
```yaml
expect:
  repair: auto
  max_iterations: 4
  on_exhausted: return_last
```

## Declared Endpoints

This table gives the messages that occur most often for the `endpoints:` block of `agent_actions.yml`, and for an action that selects an endpoint with `model_vendor`. The [Endpoints](../reference/configuration/endpoints.md) page gives all the load rules.

| Message | Stage | What to do |
|---------|-------|------------|
| `endpoints.<name>: unknown key 'format'` | load | Remove the key. An endpoint has only `url`, `auth`, `headers` and `timeout_seconds`. |
| `endpoints.<name>: '<name>' is a built-in vendor; choose another endpoint name` | load | Rename the endpoint. The built-in names (`openai`, `llamafile`, ...) are already in use. |
| `endpoints.<name>: auth is required; write 'auth: none' for an endpoint that takes no credential` | load | Add `auth: none`, `auth: { env: NAME }` or `auth: { command: [...] }`. |
| `endpoints.<name>.url: give the base URL, for example http://gpu-box:8000/v1; agac adds /chat/completions` | load | Remove `/chat/completions` from the url. |
| `endpoints.<name>.headers.<H>: write a credential as ${ENV_VAR}, not as a literal value` | load | Put the value in an environment variable. Then write `${NAME}`. |
| `Action '<a>': endpoint '<name>' runs with structured output only; set json_mode: true and add a schema` | preflight | Endpoints run with structured output only. Give the action a schema. |
| `Action '<a>': endpoint '<name>' reads NAME, which is not set` | preflight | Export the variable that the endpoint reads for its credential, url or header. |
| `Action '<a>': endpoint '<name>' auth command 'x' is not on PATH` | preflight | Install the command, or add its directory to PATH. |
| `Action '<a>': endpoint '<name>' takes its credential from endpoints.<name>.auth; remove api_key from the action` | load | Remove `api_key` (or `base_url`) from the action. The endpoint carries these values. |
| `Action '<a>': vendor '<name>' does not support run_mode: batch.` | preflight | Set `run_mode: online`. Endpoints run online only. |
| `endpoint '<name>' refused the credential (HTTP 401)` | `--verify-keys` | Check the credential in `endpoints.<name>.auth`. At record time, a 401 shows as the error text of the vendor. With `command` auth, the framework runs the command one more time before the record fails. |
| `endpoint '<name>' could not be reached: ...` | `--verify-keys` | Check `endpoints.<name>.url`. Make sure that the server is running. |
| `endpoint '<name>' answered HTTP 404: ...` | `--verify-keys` | The server answered, but not with a completion. Check the url, the model name and the log of the server. |
| `endpoint '<name>' does not honour response_format json_schema; agac supports only endpoints with OpenAI structured output` (with ` (HTTP 400: ...)` if the server rejected the request) | `--verify-keys` | Use a server that honours `json_schema`. Or put such a server (vLLM, TGI, a LiteLLM proxy) in front of this server. A 400 can also mean a wrong model name or parameter. Read the text of the server. |
| `endpoint '<name>' auth command 'x' exited with 3` (or `printed nothing`, `did not finish in 30s`, `could not be run: ...`) | `--verify-keys`, record | The auth command failed. Run the command manually from the project root. Then correct `endpoints.<name>.auth`. The framework never shows the stderr of the command, because the stderr can hold the secret. |
| `[<a>] endpoint '<name>' returned JSON that does not match schema '<s>': ...` | record | The reply did not match the schema. The framework gives the record the disposition `parse_error`. Check the model and the schema. |

## Debugging with Prompt Traces

If an LLM action produces unexpected output, examine the compiled prompt and the raw response. This is the fastest way to find the cause. Agent Actions captures the two automatically.

:::warning[CAUTION]
Prompt traces exist only for **LLM actions**. Tool actions do not generate prompt traces. If a tool action produces empty or wrong output, debug the tool code directly. Check the input data that the tool receives, not prompt_trace.
:::

### Using the Data Explorer

1. Run `agac docs` to generate the documentation catalog.
2. Open the Data Explorer in your browser.
3. Go to the output of the action in the Data tab.
4. Find the record with unexpected output.
5. Click the **Prompt Trace** accordion below the record. The accordion shows:
   - **Compiled Prompt**: The exact text that the LLM received, with all field references resolved.
   - **LLM Response**: The raw text that the LLM returned, before parsing.

### What to Look For

- **Missing context**: Field references resolved to empty strings or wrong values. Check your `context_scope` and the dependency chain.
- **Ambiguous instructions**: The prompt does not clearly constrain the output format. Make the prompt template more strict.
- **Schema mismatch**: The LLM response does not match the expected JSON structure. Consider an `expect:` block with a repair policy.
- **Model badge**: Check if the model name matches the model that you expected. A misconfigured provider can route to the wrong model.

### Reading Traces From the Command Line

To read the traces of many records at one time, print them with `agac traces`. Add `--record <target_id>` for one record, or `--json` for a list:

```bash
agac traces -w my_workflow -a classify_issue
```

For the full table schema and query examples, see [Prompt Traces reference](../reference/data-io/prompt-traces.md).

### Inspecting Failed Record Input Snapshots

When records fail or exhaust retries, the framework captures the input record at the moment of failure. The store keeps these snapshots compressed. Thus, to print them, use [`agac records --snapshots`](../reference/cli/records), not a query on the table:

```bash
# Every failed or exhausted record, with the input it was processed with
agac records -w <workflow> --snapshots

# One action's, or one record's
agac records -w <workflow> -a <action> --snapshots
agac records -w <workflow> --snapshots --source-guid <source_guid>
```

---

## Debugging Workflows {/* #debugging-agentic-workflows */}

If an error occurs, do not change the code immediately. First, do the steps below to find the cause of the error. Then correct it.

### Step 1: Parse the Error

Get the key information from the error message. Agent Actions gives structured error context. Use this context:

1. **Type**: Find the error type, for example `SchemaValidationError` or `AgentActionsError`.
2. **Field**: Read the path after `at` in the message (`error_path`).
3. **Value and expected value**: Read the end of the message (`failed_value`, `schema_constraint`).
4. **Action**: Read the action name at the start of the error, or `function` and `agent_name`.

### Step 2: Find the Source Record

Use `source_guid` to trace the record. Each action stores its output as a JSON array, compressed in the `data` column of the `target_data` table, with `action_name` as the key. `agac records --source-guid` finds the record in each action that holds it:

```bash
# Find every action that produced a record with this source_guid
agac records -w <workflow> --source-guid 37812c37-80a2-596b-8747-8f93e7a34e7f --field _action
```

### Step 3: Check Action Outputs {/* #step-3-check-node-outputs */}

Compare the data at each action. Select the same record at each action by its `source_guid`. The store keeps records compressed, so use [`agac records`](../reference/cli/records) to read them, not sqlite3:

```bash
# Input to failing action — fetch the matching record
agac records -w <workflow> -a <failing_action> --source-guid 37812c37-80a2-596b-8747-8f93e7a34e7f

# Previous action's output for the same record
agac records -w <workflow> -a <previous_action> --source-guid 37812c37-80a2-596b-8747-8f93e7a34e7f
```

### Step 4: Enable Debug Mode

To get detailed tracebacks, run this command:

```bash
AGENT_ACTIONS_LOG_LEVEL=DEBUG agac run -a my_workflow
```

### Step 5: Enable Prompt Debug

To see the rendered prompts of LLM actions, use this configuration:

```yaml
- name: my_action
  prompt: $workflow.My_Prompt
  prompt_debug: true  # Logs full prompt
```

## Data Lineage

Each record in Agent Actions has tracking fields. You can use these fields to trace the path of the record through the workflow. This lineage data is very useful for debugging.

### source_guid

The UUID of the original content. It **never changes** in the workflow.

```json
"source_guid": "37812c37-80a2-596b-8747-8f93e7a34e7f"
```

Use `source_guid` to trace any record to its source. The number of actions that the record went through does not matter.

### lineage

An array of all the node_ids that the record visited. The array grows at each node.

```json
"lineage": [
  "extract_raw_qa_693094fb-53d1-48d6-bdc9-781a4989d35c",
  "flatten_questions_361c54c6-7080-4527-9a00-aaeccfd0e6ba_0",
  "classify_type_e546c260-de10-4f20-8950-e09f01ea468f"
]
```

The `_0` suffix shows that this record was the first record from an action that returned several records for one input.

### node_id

The node_id identifies the specific processing node:

```
classify_ticket_693094fb-...       # Single output
seed_rows_361c54c6-..._0           # Expansion, index 0
seed_rows_361c54c6-..._1           # Expansion, index 1
```

### Action Output Storage

The framework stores action outputs as JSON arrays in the `target_data` table of `agent_io/store/<workflow>.db`, keyed by `(action_name, relative_path)`. To list what each action produced, run this command:

```bash
sqlite3 agent_io/store/<workflow>.db "
  SELECT action_name, relative_path, record_count
  FROM target_data
  ORDER BY action_name, relative_path
"
```

This is a typical layout for a workflow with many actions:

```
target_data
├── action_name='extract_raw_qa'      relative_path='input.json'  record_count=42
├── action_name='flatten_questions'   relative_path='input.json'  record_count=128
└── action_name='classify_type'       relative_path='input.json'  record_count=128
```

## Reading Namespaced Fields in a Tool

A tool receives the fields that it observes, nested under each action name:

```python
@udf_tool()
def safe_function(data: dict) -> dict:
    value = data["upstream_action"]["field"]
    items = data["upstream_action"]["items"]
    return {'result': value}
```

## The repair loop

An LLM can return invalid JSON, or output that breaks a rule that you declared. Then Agent
Actions can generate the output again with feedback about the failure, and not fail
immediately. This mechanism is the repair loop. The `expect:` block of an action controls the
repair loop.

### Configuration

Repair requires explicit configuration:

```yaml
expect:
  repair: auto              # how a rule failure is regenerated
  structural: retry         # how a schema failure is regenerated
  max_iterations: 3         # total generations, counting the first
  on_exhausted: return_last # return_last | fail | raise
```

To disable repair, omit the `expect:` block.

### Configuration Options

| Option | Description |
|--------|-------------|
| `repair` | `none` (observe only), `retry` (send the original prompt again), or `auto` (send the failure detail and the hint) |
| `structural` | The same choices, for a response that the schema rejects (default: `retry`) |
| `max_iterations` | The total number of generations, with the first generation counted (1-10, default: 3) |
| `on_exhausted` | The behavior when no iterations remain: `return_last`, `fail`, `raise` |

### When to Use

Consider what your workflow needs:

- **Simple schemas**: A low `max_iterations` (2-3)
- **Complex schemas**: A higher `max_iterations` (4-5)
- **Critical outputs**: More iterations, and `on_exhausted: raise`

:::danger[WARNING]
Repair adds latency and token cost. For a high-volume workflow, consider a fix of the schema problems at the source, not a dependence on regeneration.
:::

## Log Analysis

### Log Location

```
agent_io/logs/events.json      # current run
agent_io/logs/events.1.json    # previous run (up to events.5.json)
```

### Search Patterns

The events are in JSON Lines format. The structured fields are under the `.data` object
(for example, `.data.action_name`). `message` and `level` are top-level fields.

```bash
# Find all schema validation errors
jq -c 'select(.message | test("schema validation failed"))' agent_io/logs/events.json

# Find events for a specific action
jq -c 'select(.data.action_name == "add_answer_text")' agent_io/logs/events.json

# Find events that mention a specific field
jq -c 'select(.message | test("answer_text"))' agent_io/logs/events.json
```

### Execution History

For execution metrics, read `artefact/runs.json`:

```bash
# Count failed runs
grep '"status": "FAILED"' artefact/runs.json | wc -l

# Find recent failures
grep -A5 '"status": "FAILED"' artefact/runs.json | tail -20
```

## Quick Reference

This section gives the commands and the patterns for debugging.

### Debug Commands

```bash
# Debug mode (full tracebacks)
AGENT_ACTIONS_LOG_LEVEL=DEBUG agac run -a workflow
```

### Common Fixes Cheatsheet

| Error Pattern | Quick Fix |
|---------------|-----------|
| `X is not of type 'string'` | `str(value)`, or change the type in the `schema:` of the action |
| `X is not of type 'array'` | `[value] if isinstance(value, str) else value` |
| `X was unexpected` | Declare the field in the `schema:` of the action, or do not return the field |
| `X is a required property` | Return the field from the tool, or use `expect: {repair: auto}` |
| `X is not of type 'integer'` in an object field | Return values of the declared type, or change the field to the less strict `type: object` |

### Debug Checklist

To debug a workflow error, do the steps in this checklist:

1. [ ] Read the full error message. Note `error_path` and `failed_value`.
2. [ ] Find the record by `source_guid` in the action outputs.
3. [ ] Compare the data upstream and downstream of the failing action.
4. [ ] Make sure that the fields that the tool returns match the `schema:` of the action.
5. [ ] For LLM actions, enable `prompt_debug: true`.
6. [ ] To get tracebacks, run with `AGENT_ACTIONS_LOG_LEVEL=DEBUG`.
7. [ ] For LLM schema failures, consider `expect: {repair: auto, max_iterations: 3}`.

Most errors are in one of two categories. In a schema mismatch, the data structure does not match the expectations. In a missing field, the required data was not provided. The checklist above helps you find the category of your error.

## Dependency Patterns

### Understanding Fan-in vs Parallel

If an action has more than one dependency, it is important to know how the framework detects the pattern:

```yaml
# Pattern 1: Parallel Branches (MERGE)
dependencies: [classify_1, classify_2, classify_3]
# Same base name "classify" → outputs are merged
# Execution count: N (from merged outputs)

# Pattern 2: Fan-in (MERGE BY SOURCE RECORD)
dependencies: [extract, enrich, validate]
# Different actions → every one is an input; outputs for the same source record are merged
# Execution count: one per source record that reaches the action (order of the list changes nothing)
```

To aggregate several records into one record, give the consuming action `granularity: File`.
Examples of aggregation are a roll-up, a deduplication and a count across the file. A
`kind: tool` action at File granularity receives all the records of a file in one call. Thus
the action can group the records by any field, and return as many records as the grouping
produces. `examples/map_reduce_fanin_check` shows the shape.

### Fan-in Dependency Not in context_scope

**Symptom:** Preflight refuses the workflow with `dependency 'enrich' declared but not referenced in context_scope`.

**Cause:** Each dependency of a fan-in is an input. Each dependency needs at least one field declared in `context_scope`:

```yaml
# REFUSED - enrich and validate are dependencies with no fields declared
- name: generate_report
  dependencies: [extract, enrich, validate]
  context_scope:
    observe:
      - extract.*

# CORRECT - every dependency in context_scope
- name: generate_report
  dependencies: [extract, enrich, validate]
  context_scope:
    observe:
      - extract.*
      - enrich.*
      - validate.*
```

### Unexpected Execution Count

**Symptom:** The action runs more times or fewer times than expected.

**Debug:**
1. Check if the dependencies are parallel branches (same base name) or different actions.
2. For fan-in, the action runs one time for each source record after the branches merge. These rules apply:
   - If a guard filtered out a record in any branch, the framework drops the record.
   - If a guard skipped a record, the record arrives with the fields of that branch set to null.
   - A branch that returns several records for each input runs one time for each record. Each record is paired with the record of the other branches for its source.
   - If two branches both split one source, the action fails. This occurs even when a guard downstream of one of the branches keeps a single record of its split.
   - The `granularity: File` tool of one branch can fold a record into the row of another record. The action does not run that record. The record is `unprocessed`, with the reason `consumed_into_another_record`.

   [Context Scope](../reference/context/context-scope.md) lists the shapes.
3. For parallel branches, the merged outputs set the execution count.
4. For `granularity: File`, the action runs one time for each input file, for any record count of the file.
