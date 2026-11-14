---
title: Tool Actions
sidebar_position: 1
---

# Tool Actions

A tool action runs your own Python function in a workflow, beside the LLM actions. Use a tool for logic that an LLM cannot perform. Examples are to deduplicate records, call an external API or apply deterministic business rules. These tasks need deterministic logic, not prompts.

When you need guaranteed, repeatable behavior, use a tool.

## Quick Example

```python
from agent_actions import udf_tool

@udf_tool()
def process_text(data: dict, **kwargs) -> dict:
    return {"result": data["source"]["text"].upper()}
```

```yaml
- name: process_step
  kind: tool
  impl: process_text
  intent: "Upper-case the text"
  granularity: record
  schema: processed_text
  context_scope:
    observe: [source.*]
```

## @udf_tool Decorator

The `@udf_tool` decorator registers a Python function as a tool action.

### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `granularity` | Granularity | No | The processing mode: `RECORD` (default) or `FILE` |

:::note[Schema Definition]
You define the input and output schemas in the `schema:` field of the workflow YAML, not in the decorator.
:::

### Required Output Fields

The framework checks the output of a tool against its schema, exactly as the function returns it. A required field must be in the value that the tool returns. These two fields do not count:

- An upstream field with the same name. It reaches the tool only as input.
- A `context_scope.passthrough` field. The framework adds it beside the output after the check.

The framework rejects a record that does not have a required field.

Pre-flight (`agac inspect`, `run` and `retry`) reads the source of the tool. It writes a warning for each required field that it can see the tool does not return:

```text
Pre-flight: dag-fit — 1 required output field(s) a tool's code does not return, across 1 action(s)
  ├─ collect: id — not returned by tool 'collect'
  └─ Fix: return the field from the tool on every path, or mark it optional in the tool's output schema ...
```

To correct the warning, do one of these:

- Return the field.
- Make the field optional in the schema (`optional: true` on a `fields:` entry).
- If the check cannot read how the tool returns the field, list the field under `defaults:` on the action.

The check does not examine a tool if it cannot read the output of the tool at all. For example, the check cannot read output that a helper or a loop builds.

For a record tool whose returned dict starts as a literal, the check does more than warn. Pre-flight refuses the workflow in these cases:

- The tool never sets a required field.
- The tool sets a required field only inside a branch.
- An early return omits a required field.

See [Required Output Field Set Only in a Branch](#required-output-field-set-only-in-a-branch).

### Minimal Decorator

```python
from agent_actions import udf_tool

@udf_tool()
def simple_transform(data: dict, **kwargs) -> dict:
    data['processed'] = True
    return data
```

## Granularity

| Granularity | Processing | Use Case |
|-------------|------------|----------|
| `record` | One record at a time | Transformations, filtering |
| `file` | All records at one time | Aggregation, deduplication |

### Record Granularity (Default)

```python
@udf_tool()
def filter_questions_by_score(data: dict, **kwargs) -> dict:
    score = data["upstream_action"]["syllabus_alignment_score"]
    if score >= 85:
        data['question_status'] = "KEEP"
    else:
        data['question_status'] = "FILTER"
    return data
```

The keys of `data` are **action names**, that is, the `name:` values in the workflow. The keys
are never the `impl:` values. For example, an action has `- name: compile_input` and
`impl: m_compile_input`. Read `data["compile_input"]`. `data.get("m_compile_input")` finds
nothing and returns its default with no message.

A tool or guard UDF can read a literal key that is not the name of an action. Before it runs
anything, `agac run` writes a warning for each such key. `agac validate-udfs` does the same:

```
Pre-flight: bus namespaces — 1 warning(s)
  └─ m_verify: reads bus namespace 'm_compile_input' which is not an action name in the workflow. ...
```

### File Granularity

Use file granularity when your logic needs context from more than one record. A FILE tool receives a list with one item for each record. Each item holds the fields that the action observes, as flat keys.

```python
from agent_actions import udf_tool
from agent_actions.config.schema import Granularity

@udf_tool(granularity=Granularity.FILE)
def run_dedup(data: list[dict], **kwargs) -> list[dict]:
    """Dedup — return the items received to preserve lineage."""
    seen = set()
    unique = []
    for record in data:
        fact = record["fact"]
        if fact not in seen:
            seen.add(fact)
            unique.append(record)  # return the item as received
    return unique
```

:::note[File Granularity is Tool-Only]
Only tool actions support file granularity. LLM actions must use record granularity.
:::

### File Granularity Constraints

- **The input is an array with one item for each record.** Each item holds the fields that the action observes, as flat keys.
- **Read business data from `record["field"]`.** A field that you name in `observe` is always under its bare name. A key is `action_name.field` only when two observed names really collide. A collision occurs in these cases:
  - Two named fields have the same name.
  - A field has the name of an observed namespace.
  - A wildcard field has the same name as a named field. The named field keeps the bare key.
  - The action observes several actions by wildcard.

  Neither `content` nor an action name encloses the fields.
- **To pass a record through, return the item that you received** (filter, dedup, sort, transform). The item keeps its identity and lineage.
- **For aggregation, return `FileUDFResult` with `source_index: None`.** This value says that no single input produced the row. The framework gives the row a new identity and fresh lineage. From each upstream namespace, the row carries only the fields whose value is the same on every input of the file. When the file holds one input, the row carries all fields. The row has none of the history of any one input. A field that differs between inputs is not on the row. If a retry writes the row again exactly as it was, it is the same row and keeps its identity. Thus the downstream actions keep their answers for the row. The framework rejects a plain new dict in a list.
- **A position is a non-negative built-in `int`.** `source_index` takes one position, a list of positions for a many-to-one output, or `None`. The framework refuses a negative value, a bool, or a `None` inside the list. A numpy or pandas index is not an `int`. Cast it with `int(idx)`. To say that no single input produced the row, use `None`. Never use an empty list.
- **The parent position must resolve.** The framework accepts an index past the end where the tool declares it. The reason is that a tool cannot always know how many records the guard left it. But the framework drops only a *contributor* in this way. The scalar, or the first element of the list, is the parent of the row. If the parent names no input, every record of its file fails. The framework does not invent a parent for the row. The action ends `completed_with_failures`, or `failed` when no record succeeds. `agac retry` gives the tool the file of those records again, whole (see [When a FILE Tool Fails](../execution/granularity.md#when-a-file-tool-fails)).
- **The output size is flexible.** Return an array of any size (N→M transformation).

For more information, see [Granularity](../execution/granularity.md).

### Record Identity and Lineage

The framework tracks each record through the workflow with `node_id`. The [Apache NiFi FlowFile model](https://nifi.apache.org/docs/nifi-docs/html/nifi-in-depth.html) inspired this design. You never manage `node_id` directly. The framework sets it automatically, from the value that you return:

```python
from agent_actions import FileUDFResult, udf_tool
from agent_actions.config.schema import Granularity

@udf_tool(granularity=Granularity.FILE)
def dedup_tool(data: list[dict], **kwargs) -> list[dict]:
    seen = {}
    outputs = []

    for record in data:
        fact = record["fact"]
        if fact not in seen:
            seen[fact] = True
            outputs.append(record)  # item as received → lineage extended

    return outputs


@udf_tool(granularity=Granularity.FILE)
def aggregate_tool(data: list[dict], **kwargs) -> FileUDFResult:
    total = sum(r["score"] for r in data)
    # source_index: None — no single input produced this row → fresh lineage
    return FileUDFResult(outputs=[
        {"source_index": None, "data": {"summary": f"Total: {total}", "count": len(data)}}
    ])
```

| What you return | Framework behavior |
|---|---|
| An item that you received | The framework extends the parent lineage. A downstream `observe` can load ancestor data. |
| A `FileUDFResult` output whose `source_index` list names all the records of the file that were split from one source, and only those records. No other output names any of these records. | The output takes the `source_guid` of that source, as an unsplit record holds it. Thus a fan-in pairs the output with the records of the source from the other branches. Any other many-to-one output keeps the identity of its first input. |
| A `FileUDFResult` output whose `source_index` list names several inputs, for example `[a, b]` (a fold) | The output keeps the identity of the first input. Thus `b` has no row of its own downstream of the tool. The disposition of `b` there is `success`, with the reason `consumed_into_output`. This does not apply when any output declares `source_index: None`. The row lists `b` under `folded_sources`. If no fan-in is downstream, the downstream actions run on the row alone. Beside another branch, a [fan-in](../context/context-scope.md) does not run `b` with the fields of this branch empty. The fan-in leaves `b` `unprocessed`, with the reason `consumed_into_another_record`. The tombstone of `b` names the row that received it as `consumed_into`. A version merge does the same when one version of a versioned tool folded `b` and another version kept it. |
| A `FileUDFResult` output with `source_index: None` | The framework creates a new root, with fresh lineage and a fresh `source_guid`. `aggregated_by` names the action. This identity matches nothing upstream. Thus the framework stores the row whole, not as a delta against upstream data. From each upstream namespace, the row keeps the fields that are equal on every input of its file. A [fan-in](../context/context-scope.md) pairs the row only where every branch reads it. Beside a branch that does not read it, the fan-in fails. |
| No output names an input | The tool dropped the input. The framework stores the input as a tombstone, `unprocessed` with the reason `tool_missing_record`. The downstream actions skip the input. A fan-in beside another branch also skips it. Exception: if any output declares `source_index: None`, that output may have consumed the input. Then the input gets no row. |

## Tool Discovery

Agent Actions automatically discovers the tools that have the `@udf_tool` decorator in the configured directories.

### Configuration

Set the tool path in `agent_actions.yml`. The default is `["tools"]`:

```yaml
tool_path: ["tools", "custom_tools"]
```

A workflow file can set its own `tool_path`. This value has precedence over the project file. The `TOOLS_PATH` environment variable does not change tool discovery. It only names the folder where the framework searches for a custom `split_method` module.

### Directory Structure

```
project/
├── agent_actions.yml
├── tools/
│   ├── __init__.py          # Optional
│   ├── transformers.py      # Contains @udf_tool functions
│   └── validators.py
└── agent_workflow/
    └── ...
```

### Workflow Reference

Refer to a tool by its function name:

```yaml
- name: flatten_the_facts
  kind: tool
  impl: flatten_quotes  # Function name (case-insensitive)
  granularity: record
```

### Discovery Process

The framework discovers tools in this sequence:

1. The framework scans the directories in `tool_path` recursively.
2. The framework lists the Python files (`*.py`). It skips the files whose names start with `_` or `test_`.
3. The framework imports only the files that declare a tool-registering decorator (`@udf_tool` or `@expectation_check`). It parses the source to find the decorator, and it does not execute the source. It skips helper scripts that have no decorator, so a broken helper cannot block discovery.
4. The framework executes the matching modules to trigger decorator registration.
5. The framework validates the `impl` references in the workflow configuration.

:::note[Thread Safety]
Tool registration is thread-safe. The framework loads a module only one time.
:::

## CLI Commands

```bash
# List all discovered tools
agac list-udfs -u ./tools

# Validate tool references in workflow
agac validate-udfs -a my_workflow -u ./tools
```

## Import Rules

The framework loads each tool file in isolation, with `importlib.util.spec_from_file_location`. The framework does **not** add the tools directory to `sys.path`. Thus a tool cannot import a sibling module with a bare `import` statement.

These imports work:
- **Installed packages**: Any dependency in the virtual environment of your project (for example, `import pandas`, `from agent_actions import udf_tool`).
- **Standard library**: `import json`, `import pathlib` and other standard modules.

These imports do not work:
- **Sibling imports**: `import other_tool` or `from . import utils`, where `other_tool` and `utils` are files in the same tools directory.

If two or more tool files need shared logic, do these steps:

1. Move the shared logic into an installable package.
2. Add the package to the dependencies of your project.

### A tool file that fails to import

If a tool file raises an exception during import, `agac run` skips the file and writes a message.
Thus one broken file does not stop the workflows that use none of its tools:

```
Skipped tool file tools/other/broken.py: it failed to import (boom at import). A workflow using a tool from it fails until it imports.
```

The framework refuses a workflow that names a tool or guard UDF that is not loaded. This rule
includes a tool from a skipped file. The refusal occurs before any action runs. The error names
the action and each skipped file. `agac validate-udfs` and `agac list-udfs` still stop at the
first file that fails to import.

## Best Practices

### Handle Missing Fields

```python
@udf_tool()
def safe_function(data: dict, **kwargs) -> dict:
    score = data["upstream_action"]["score"]
    return {'result': score}
```

### Return Complete Records

```python
@udf_tool()
def augment_data(data: dict, **kwargs) -> dict:
    data['new_field'] = 'computed_value'  # Add to existing, don't replace
    return data
```

### Unique Function Names

Each tool name must be unique across all files. If necessary, use the domain as a prefix of the name:

```python
@udf_tool()
def validate_email(data): ...

@udf_tool()
def validate_phone(data): ...
```

## Error Handling

### Duplicate Function Names

```
Duplicate UDF function name detected: 'process_data'
  Existing: module_a.process_data (in tools/module_a.py)
  New:      module_b.process_data (in tools/module_b.py)

Suggestions:
  1. Rename one of the functions to be unique
  2. Move shared UDFs to a common shared directory
  3. Remove the duplicate if it's unintentional
```

If you get this error, rename one of the functions.

### Required Output Field Set Only in a Branch

The framework checks each record that a tool returns against the output schema of the action.
Thus, if the tool sets a required field only inside an `if`, each record that does not take
that branch fails. Pre-flight reads the tool before anything runs. When pre-flight can see this
problem, it refuses the workflow:

```python
from agent_actions import udf_tool


@udf_tool()
def produce(data: dict, **kwargs) -> dict:
    out: dict = {"label": data["source"]["text"]}
    if data["source"]["text"] == "has items":
        out["items"] = "apple, pear"  # 'items' is required by the schema
    return out
```

```
producer: output schema requires 'items' but the tool 'produce' sets it only at
line 8 of produce.py, inside an `if`, so a record that does not take that path
fails output validation at run time. Make 'items' optional in the schema, or set
it on every path in the tool.
```

To correct the refusal, do one of these:

- Make the field optional in the schema.
- Give the field a value on every path, for example in the dict that the tool starts from.

The check reads a dict that the tool returns, alone or as the one item of a list
(`return [out]`). The check reads the dict only when the dict is bound to a literal, `{...}` or `dict(key=...)`. The dict can
have a type annotation or no type annotation. The check follows each path to that return. It
counts a key only when every path sets the key. A path can set the key in the literal, or with
one of these forms: `out["key"] = ...`, `out |= {...}`, `out.update({...})`,
`out.update(key=...)` or `out.setdefault("key", ...)`.

- These parts must all set the key:
  - The two branches of an `if`.
  - Each case of a `match` with a `case _:`.
  - A `with` body.
  - A `finally`.
  - A `try` body, together with each `except` that does not re-raise.

  A path that raises never returns. Thus an `except` that always re-raises does not count
  against the key.
- A loop body may run zero times. Thus a key that is set only inside a loop does not count.
  The exception is a loop over a literal list of names, for example
  `for field in ("a", "b"): out[field] = ...`. This loop runs one time for each name. A key
  that a loop removes and sets again in the same pass still counts.
- `del out["key"]`, `out.pop("key")` and `out.clear()` remove a key on the paths where they
  run. If a path binds `out` to a new literal, `out` keeps only the keys of that literal.

The check examines each `return`, not only the last one. Each `return` gives back a record to
validate. Pre-flight also examines an early return of a literal, or of `out` before the key is
set. If that early return omits a required field, pre-flight refuses the workflow:

```python
from agent_actions import udf_tool


@udf_tool()
def produce(data: dict, **kwargs) -> dict:
    content = data["source"]["text"]
    if not content:
        return {"label": ""}  # 'items' is required by the schema
    return {"label": content, "items": content.upper()}
```

```
producer: output schema requires 'items' but the tool 'produce' returns without
it at line 8 of produce.py, inside an `if`, so a record that takes that path fails
output validation at run time. Make 'items' optional in the schema, or set it on
every path in the tool.
```

An early return of nothing (`return`, `return None`, `return []`) gives back no record. The
check does not examine it. The check also does not examine a branch that only raises.

The refusal names one of these lines:

- The line that sets the field only in a branch.
- The line that removes the field.
- The early return that omits the field.

If the check cannot read the
output of a return in this way, pre-flight does not refuse the workflow. The framework still
checks the records of that return one by one at run time. The check cannot read these outputs:

- A dict that a helper function builds, or that any path binds to a value other than a
  literal.
- Keys that the tool merges from a value other than a literal, for example
  `out.update(build(data))` or `out |= extra`.
- A key that the tool sets or removes by a name that the check cannot know, for example
  `for field in FIELDS: out[field] = ...`.
- A return inside a loop, other than a return of a literal.
- A return of the input of the tool, of the result of a helper, or of a `{**spread}`.
- A return of a list of more than one item.

### Function Not Found

```
FunctionNotFoundError: Function 'nonexistent_func' not found
```

If you get this error, do these checks:
1. Make sure that the file is in the `tools/` directory.
2. Make sure that the function has the `@udf_tool` decorator.
3. Make sure that the function name matches the `impl` value of the workflow.
