---
title: traces Command
description: Print the prompt, the context and the response that each record of an action used
sidebar_position: 7
---

# traces Command

The `traces` command prints the prompt traces of an action as plain text. For each record, a trace contains the prompt that the action sent, the context of the prompt, and the response that came back.

```bash
agac traces -w <workflow-name> -a <action> [options]
```

The store keeps this text compressed. Thus `sqlite3` shows the `compiled_prompt`, `llm_context` and `response_text` columns as blobs. Read them with this command. The command opens the store read-only.

## Options

| Option | Description |
|--------|-------------|
| `-w, --workflow TEXT` | The name of the workflow configuration file (required) |
| `-a, --action TEXT` | The action whose traces the command prints (required) |
| `--record TEXT` | Only the traces of this record. Give its `target_id`, or its `parent_target_id` if an expansion produced the record |
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

The command prints each trace in this format:

```text
=== classify_issue record <target_id> attempt 0 (openai gpt-4o-mini) ===
--- PROMPT ---
<the prompt the record was sent>
--- CONTEXT ---
<the context it was rendered from, or (none)>
--- RESPONSE ---
<the response, or (none) if it has not arrived>
```

A record that [`expect:`](../validation/expectations.md) repaired has one trace for each attempt, online and in batch. Attempt 0 is the first prompt. Each attempt after it is the prompt that the call sent, next to the response that the call got.

After a failed rule, the prompt depends on the repair setting:

- Under `repair: auto`, the prompt has the previous response and the failed rules added at the end.
- Under `repair: retry`, the prompt is the original prompt again.
- Under a `prompt:` of your own, the prompt is your template.

After a schema failure, the prompt follows `structural:`. By default, `structural:` sends the original prompt again.
The response that was sent on, with its verdict, is on the attempt that got it. That attempt is the last one, or the one before it when a repair call failed.
In a batch run, each repair round writes the prompt that the round sent. The last attempt holds the response that was sent on.

## Errors

| Message | Cause |
|---------|-------|
| `No store for workflow '<name>' at <path>` | The workflow did not run. Thus it has no store. |
| `No prompt traces for action '<action>' in <path>` | The action wrote no traces. The action is a tool action that runs over a whole file (`granularity: File`), or it did not run, or `--fresh` cleared its traces. |
| `No prompt traces for action '<action>' record '<record>' in <path>` | `--record` named a record for which the action has no trace. |

For the contents of a trace and when it is cleared, see [Prompt Traces](../data-io/prompt-traces.md).
