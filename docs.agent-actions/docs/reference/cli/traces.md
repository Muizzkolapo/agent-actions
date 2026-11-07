---
title: traces Command
description: Print the prompt, context and response an action's records were run with
sidebar_position: 7
---

# traces Command

The `traces` command prints the prompt traces of an action as plain text: the prompt each record was sent, the context it was rendered from, and the response that came back.

```bash
agac traces -w <workflow-name> -a <action> [options]
```

The store keeps this text compressed, so `sqlite3` shows the `compiled_prompt`, `llm_context` and `response_text` columns as blobs. Read them with this command. It opens the store read-only.

## Options

| Option | Description |
|--------|-------------|
| `-w, --workflow TEXT` | Workflow configuration file name (required) |
| `-a, --action TEXT` | Action whose traces to print (required) |
| `--record TEXT` | Only this record's traces: its `target_id`, or its `parent_target_id` if an expansion produced it |
| `--json` | Print the traces as a JSON list |

## Examples

```bash
# Every trace of an action
agac traces -w my_workflow -a classify_issue

# One record's traces, all attempts
agac traces -w my_workflow -a classify_issue --record <target_id>

# A JSON list, for a script
agac traces -w my_workflow -a classify_issue --json
```

Each trace prints as:

```text
=== classify_issue record <target_id> attempt 0 (openai gpt-4o-mini) ===
--- PROMPT ---
<the prompt the record was sent>
--- CONTEXT ---
<the context it was rendered from, or (none)>
--- RESPONSE ---
<the response, or (none) if it has not arrived>
```

A record that [`expect:`](../validation/expectations.md) repaired online has one trace per attempt: attempt 0 is the first prompt, and each attempt after it is the prompt that call was sent, beside the response it drew. After a failed rule, under `repair: auto` that prompt has the previous response and the failed rules appended; under `repair: retry` it is the original prompt again; under a `prompt:` of your own it is your template. After a schema failure it follows `structural:`, which by default re-sends the original prompt. The response that shipped, with its verdict, is on the attempt that drew it: the last one, or the one before it when a repair call failed.

## Errors

| Message | Cause |
|---------|-------|
| `No store for workflow '<name>' at <path>` | The workflow has not run, so it has no store. |
| `No prompt traces for action '<action>' in <path>` | The action wrote no traces: it is a tool action that runs over a whole file (`granularity: File`), it has not run, or `--fresh` cleared it. |
| `No prompt traces for action '<action>' record '<record>' in <path>` | `--record` named a record the action has no trace for. |

See [Prompt Traces](../data-io/prompt-traces.md) for what a trace holds and when it is cleared.
