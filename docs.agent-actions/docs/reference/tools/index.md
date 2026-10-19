---
title: Tool Actions
sidebar_position: 1
---

# Tool Actions

What happens when you need logic that an LLM can't perform? Deduplicating records, calling an external API, or applying deterministic business rules—these tasks need deterministic logic, not prompts.

Tool actions let you execute custom Python functions alongside LLM actions in your agentic workflow. When you need guaranteed, repeatable behavior, you use a tool.

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
  granularity: record
```

## @udf_tool Decorator

The `@udf_tool` decorator registers a Python function as a tool action.

### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `granularity` | Granularity | No | `RECORD` (default) or `FILE` processing |

:::info Schema Definition
Input and output schemas are defined in the workflow YAML `schema:` field, not in the decorator.
:::

### Required Output Fields

A tool's output is checked against its schema exactly as the function returns it. A required field must be in what the tool returns: a field of the same name upstream reaches the tool only as input, and a `context_scope.passthrough` field is added beside the output after the check, so neither one counts. A record missing a required field is rejected.

Pre-flight (`agac inspect`, `run` and `retry`) reads the tool's source and warns about each required field it can see the tool does not return:

```text
Pre-flight: dag-fit — 1 required output field(s) a tool's code does not return, across 1 action(s)
  ├─ collect: id — not returned by tool 'collect'
  └─ Fix: return the field from the tool on every path, or mark it optional in the tool's output schema ...
```

Return the field, or make it optional in the schema (`optional: true` on a `fields:` entry). If the tool does return it in a way the check cannot read, list it under `defaults:` on the action. A tool whose output the check cannot read at all, such as one built by a helper or in a loop, is not checked.

A record tool whose returned dict starts as a literal is held to more than a warning: a required field it never sets, sets only inside a branch, or leaves out of an early return, refuses the workflow. See [Required Output Field Set Only in a Branch](#required-output-field-set-only-in-a-branch).

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
| `file` | All records at once | Aggregation, deduplication |

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

### File Granularity

Use when your logic needs cross-record context. FILE tools receive a list with one item per record, each holding the fields the action observes as flat keys.

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

:::tip File Granularity is Tool-Only
File granularity is exclusively supported for tool actions. LLM actions must use record granularity.
:::

### File Granularity Constraints

- **Input is an array with one item per record** — each item holds the fields the action observes as flat keys
- **Read business data from `record["field"]`** — or `record["action_name.field"]` where two observed names could collide, as when the tool observes several actions by wildcard or merges versions. There is no `content` and no action name around the fields
- **Return the item you received for passthrough** (filter, dedup, sort, transform) — preserves its identity and lineage
- **Return `FileUDFResult` with `source_index: None` for aggregation** — says no single input produced the row; the framework mints it an identity and fresh lineage. A plain new dict in a list is rejected
- **A position is a non-negative built-in `int`** — `source_index` takes one position, a list of them for a many-to-one output, or `None`. A negative, a bool, or a `None` inside the list is refused, and a numpy or pandas index is not an `int` — cast it with `int(idx)`. Use `None` to mean no single input produced the row, never an empty list
- **The parent position has to resolve** — an index past the end is accepted where the tool declares it, since a tool cannot always know how many records the guard left it, but only a *contributor* is dropped that way. The scalar, or the list's first element, is the row's parent: one that names no input fails every record of its file rather than inventing a parent for the row. The action ends `completed_with_failures`, or `failed` when no record succeeds, and `agac retry` hands the tool their file again, whole (see [When a FILE Tool Fails](../execution/granularity.md#when-a-file-tool-fails))
- **Output flexibility** — return an array of any size (N→M transformation)

See [Granularity](../execution/granularity.md) for detailed documentation.

### Record Identity and Lineage

The framework tracks each record through the pipeline using `node_id` — inspired by [Apache NiFi's FlowFile model](https://nifi.apache.org/docs/nifi-docs/html/nifi-in-depth.html). You never manage `node_id` directly. The framework handles it automatically based on what you return:

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
| An item you received | Extends parent lineage — downstream `observe` can load ancestor data |
| `FileUDFResult` output whose `source_index` list names every record of the file split from one source, and only those, with no other output naming any of them | Takes that source's `source_guid`, as an unsplit record holds it, so a fan-in pairs it with other branches' records of the source. Any other many-to-one output keeps its first input's identity |
| `FileUDFResult` output whose `source_index` list names several inputs, such as `[a, b]` (a fold) | Keeps the first input's identity, so `b` has no row of its own below the tool: its disposition there is `success` with reason `consumed_into_output` (none when any output declares `source_index: None`), and the row lists it under `folded_sources`. With no fan-in below, the actions below run on the row alone. Beside another branch, a [fan-in](../context/context-scope.md) does not run `b` with this branch's fields empty: it leaves `b` `unprocessed`, reason `consumed_into_another_record`, and its tombstone names the row it went into as `consumed_into`. A version merge does the same when one version of a versioned tool folded `b` and another kept it |
| `FileUDFResult` output with `source_index: None` | Creates new root — fresh lineage and a fresh `source_guid`, and `aggregated_by` names the action. That identity matches nothing upstream, so the row is stored whole rather than as a delta against it, and keeps the namespaces its file carried. A [fan-in](../context/context-scope.md) pairs it only where every branch reads it; beside a branch that does not, the fan-in fails |
| No output naming an input | The input was dropped: it is stored as a tombstone, `unprocessed` with reason `tool_missing_record`, and the actions below skip it, including a fan-in beside another branch. Not when any output declares `source_index: None`, which may have consumed it: then the input gets no row |

## Tool Discovery

Agent Actions automatically discovers tools decorated with `@udf_tool` from configured directories.

### Configuration

Set the tool path in `agent_actions.yml`:

```yaml
tool_path: ["tools", "custom_tools"]
```

Or use the `TOOLS_PATH` environment variable:

```bash
export TOOLS_PATH="tools"
```

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

Reference tools by function name:

```yaml
- name: flatten_the_facts
  kind: tool
  impl: flatten_quotes  # Function name (case-insensitive)
  granularity: record
```

### Discovery Process

1. Scans directories in `tool_path` recursively
2. Lists Python files (`*.py`), skipping files starting with `_` or `test_`
3. Imports only files that declare a tool-registering decorator (`@udf_tool` or `@expectation_check`), detected by parsing the source without executing it — helper scripts without a decorator are skipped, so a broken helper cannot block discovery
4. Executes matching modules to trigger decorator registration
5. Validates `impl` references in agentic workflow config

:::info Thread Safety
Tool discovery is thread-safe and cached. Concurrent discovery calls are properly synchronized, and modules are loaded only once.
:::

## CLI Commands

```bash
# List all discovered tools
agac list-udfs -u ./tools

# Validate tool references in workflow
agac validate-udfs -a my_workflow -u ./tools
```

## Import Rules

Tool files are loaded in isolation using `importlib.util.spec_from_file_location`. The tools directory is **not** added to `sys.path`, so tools cannot import sibling modules with bare `import` statements.

What works:
- **Installed packages** — any dependency in your project's virtual environment (e.g., `import pandas`, `from agent_actions import udf_tool`)
- **Standard library** — `import json`, `import pathlib`, etc.

What does not work:
- **Sibling imports** — `import other_tool` or `from . import utils` where `other_tool` and `utils` are files in the same tools directory

If you need shared logic across multiple tool files, extract it into an installable package and add it to your project dependencies.

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

Tool names must be unique across all files. Prefix with domain if needed:

```python
@udf_tool()
def validate_email(data): ...

@udf_tool()
def validate_phone(data): ...
```

## Error Handling

### Duplicate Function Names

```
DuplicateFunctionError: Function 'process_data' already registered
  Existing: module_a.process_data (tools/module_a.py)
  New: module_b.process_data (tools/module_b.py)
```

Rename one of the functions.

### Required Output Field Set Only in a Branch

Each record a tool returns is checked against the action's output schema, so a
required field the tool sets only inside an `if` fails every record that does
not take that branch. Pre-flight reads the tool before anything runs and refuses
the workflow when it can see this:

```python
@udf_tool()
def produce(data: dict, **kwargs) -> dict:
    out: dict = {"label": data["source"]["text"]}
    if data["source"]["text"] == "has items":
        out["items"] = "apple, pear"  # 'items' is required by the schema
    return out
```

```
producer: output schema requires 'items' but the tool 'produce' sets it only at
line 5 of produce.py, inside an `if`, so a record that does not take that path
fails output validation at run time. Make 'items' optional in the schema, or set
it on every path in the tool.
```

Either make the field optional in the schema, or give it a value on every path,
for example in the dict the tool starts from. The check reads a dict the tool
returns, alone or as the one item of a list (`return [out]`), that is bound to a
literal, `{...}` or `dict(key=...)`, with or without a type annotation. It
follows each path to that return and counts a key only when every path sets it:
in the literal, or with `out["key"] = ...`, `out |= {...}`,
`out.update({...})`, `out.update(key=...)` or `out.setdefault("key", ...)`.

- Both branches of an `if`, every case of a `match` with a `case _:`, a `with`
  body, a `finally`, and a `try` body together with each `except` that does not
  re-raise must all set the key. A path that raises never returns, so an
  `except` that always re-raises does not count against it.
- A loop body may run no times, so a key set only inside a loop does not count,
  except in a loop over a literal list of names, such as
  `for field in ("a", "b"): out[field] = ...`, which runs once per name. A key a
  loop removes and sets again in the same pass still counts.
- `del out["key"]`, `out.pop("key")` and `out.clear()` remove a key on the paths
  they run on, and binding `out` to a new literal keeps only that literal's
  keys.

Every `return` is checked, not only the last: each one hands back a record to
validate. An early return of a literal, or of `out` before the key is set,
refuses the workflow when it leaves out a required field:

```python
@udf_tool()
def produce(data: dict, **kwargs) -> dict:
    content = data["source"]["text"]
    if not content:
        return {"label": ""}  # 'items' is required by the schema
    return {"label": content, "items": content.upper()}
```

```
producer: output schema requires 'items' but the tool 'produce' returns without
it at line 5 of produce.py, inside an `if`, so a record that takes that path fails
output validation at run time. Make 'items' optional in the schema, or set it on
every path in the tool.
```

An early return of nothing (`return`, `return None`, `return []`) hands back no
record and is not checked, and neither is a branch that only raises.

The refusal names the line that sets the field only in a branch, the line that
removes it, or the early return that leaves it out. A return whose output it
cannot read this way is not refused, and its records are still checked one by
one at run time. That covers:

- a dict a helper function builds, or that any path binds to something other
  than a literal;
- keys merged in from something other than a literal, as in
  `out.update(build(data))` or `out |= extra`;
- a key set or removed by a name the check cannot know, as in
  `for field in FIELDS: out[field] = ...`;
- a return inside a loop, other than of a literal;
- a return of the tool's input, of a helper's result, of a `{**spread}`, or of a
  list of more than one item.

### Function Not Found

```
FunctionNotFoundError: Function 'nonexistent_func' not found
```

Check that:
1. File is in `tools/` directory
2. Function has `@udf_tool` decorator
3. Function name matches workflow `impl`
