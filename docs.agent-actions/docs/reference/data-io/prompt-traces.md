---
title: Prompt Traces
sidebar_position: 6
---

# Prompt Traces

:::note[Storage backend]
SQLite. Traces are stored in `agent_io/store/<workflow>.db`, table `prompt_trace`.
:::

Every time an action processes a record, Agent Actions captures a **prompt trace**. A prompt trace is the compiled prompt sent to the model and the raw response received. Traces are stored in the `prompt_trace` table of the SQLite database of your workflow. A tool action is also traced. Its `model_vendor` is `tool` and its `model_name` is the tool name.

## What Gets Captured

| Field | Description |
|-------|-------------|
| `compiled_prompt` | The fully rendered Jinja template sent to the LLM |
| `llm_context` | The context dict, serialized to JSON (template variables) |
| `response_text` | The raw response text of the LLM |
| `model_name` | The model identifier (for example, `llama3.2:latest`, `gpt-4o-mini`) |
| `model_vendor` | The provider name (for example, `ollama_local`, `openai`) |
| `run_mode` | `online` (real-time) or `batch` |
| `prompt_length` | The character count of the compiled prompt |
| `context_length` | The character count of the LLM context sent to the model |
| `response_length` | The character count of the LLM response |
| `attempt` | The attempt number (0 = initial, 1+ = repair iterations) |
| `source_guid` | The durable identity of the record that was prompted |
| `run_id` | The workflow run that wrote the row |
| `answered_under` | JSON: the config that the record was answered under. It holds `config_hash` (prompt, schema and guard), `model_name`, `model_vendor`, `context_scope_hash`, `dependencies_hash`, `generation_hash` and `udf_source_hash` |

Traces carry two identifiers. The identifier to join on depends on the question
that you ask.

- `source_guid` is the **durable** identity of the record that was prompted. It
  is the same value that `record_disposition.record_id` holds. Thus it is the key
  for audits across tables ("was this record prompted, and what did it get?"). It
  is stable across runs.
- `record_id` is the **prepare-time** `target_id`. A new value is minted in every
  run. For a record that an action expands into several records, a new value is
  minted again for each child. Join on it to ask
  "which prompt produced this record on this run". The reason is that it cannot reach a row that an earlier run left.
  A record produced by an expansion reaches its prompt through its
  `parent_target_id`. The reason is that its own id did not exist yet when the
  prompt ran.

Both identifiers apply to online and batch alike. Rows written before `source_guid`
and `run_id` existed have `NULL` in these columns.

A [config edit](../cli/run#when-you-edit-the-workflow) re-runs nothing. Thus one action can
hold answers from more than one config. `answered_under` tells which config answered each
record. It holds the same keys as the `answered_under` stamp of the action in
`agent_io/.agent_status.json`. Thus you can compare the two directly.

Rows written before this column existed have `NULL` in it. A row is written when its prompt
is built, before the model is called. Thus a row with no `response_text` was prompted under
that config but not answered. The run stopped before the answer came back.

An action that stopped partway keeps its traces when it resumes, including the rows of
attempts that failed. These rows show what was asked, and under which config. Thus a record
can hold a failed attempt under the old config beside its answer under the new config. The
latest row of each record is the row that its answer came from:

```sql
SELECT source_guid, attempt, json_extract(answered_under, '$.model_name') AS model
FROM prompt_trace
WHERE id IN (
  SELECT MAX(id) FROM prompt_trace WHERE action_name = 'classify' GROUP BY source_guid
);
```

```sql
SELECT source_guid, json_extract(answered_under, '$.model_name') AS model
FROM prompt_trace
WHERE action_name = 'classify';
```

## How Long Traces Are Kept

Traces stay across runs that build on what an action already answered. A
resumed run and `agac retry` keep the traces of the records that they do not ask
again. They keep these traces beside the traces of the records that they ask again.
Traces are cleared when the answers that they describe are replaced:

- `agac run --fresh` clears the traces of every action.
- An action that runs again over every record clears its own traces. It also
  clears the traces of every action that reads it and runs again with it. This
  occurs on `agac run --rerun`, when its stored output is gone, and when its
  limits changed. A config edit or a change to the staged input clears nothing.
  The traces of the answers that stand are kept, and each trace names the config
  that it was answered under. The traces of a record that is no longer staged are
  also kept.
- A failed or skipped action that runs again from the start clears its traces.

In all other cases, storage maintenance keeps the traces of the most recent
`storage.prompt_trace_retention_runs` calendar days on which traces were written
(`0` never prunes).

## Viewing Traces in VS Code

The VS Code extension attaches the trace of each record to the record in the Query Results panel. It matches them by `target_id`. Card view shows these sections, in this order, after the identity header:

1. **Prompt Trace** — collapsible. It shows the compiled prompt, with the model name and run mode as badges.
2. **Input Data** — collapsible. The input namespaces of the record.
3. **Raw Response** — collapsible. The text that the LLM returned.
4. **Action Output**
5. **Metadata** — collapsible, shown last

### JSON View

In JSON view, the trace is a nested `_trace` field on each record:

```json
{
  "source_guid": "2362b687-87c7-5534-83a1...",
  "issue_type": "feature_request",
  "_trace": {
    "compiled_prompt": "You are a support ticket classifier...",
    "response_text": "[{\"issue_type\": \"bug\"}]",
    "model_name": "llama3.2:latest",
    "run_mode": "batch",
    "attempt": 0
  }
}
```

## Reading a Trace

The store keeps the prompt, context and response text in compressed form. Read them with `agac traces`:

```bash
# Every trace of an action, as plain text
agac traces -w <workflow> -a classify_issue

# One record's traces (its target_id, or its parent_target_id if an expansion produced it)
agac traces -w <workflow> -a classify_issue --record <target_id>

# The same traces as a JSON list
agac traces -w <workflow> -a classify_issue --json
```

## Querying Trace Metadata

The other columns are plain values. Thus SQL still answers questions about traces:

```bash
sqlite3 agent_io/store/<workflow>.db
```

```sql
-- List all traced actions
SELECT DISTINCT action_name FROM prompt_trace;

-- Count traces per action
SELECT action_name, COUNT(*) FROM prompt_trace GROUP BY action_name;

-- Audit a record across runs, and against its disposition
SELECT t.run_id, t.attempt, t.record_id, t.prompt_length, t.response_length, d.disposition
FROM prompt_trace t
LEFT JOIN record_disposition d
  ON d.action_name = t.action_name AND d.record_id = t.source_guid
WHERE t.action_name = 'classify_issue'
  AND t.source_guid = '<source_guid>'
ORDER BY t.id DESC;

-- Find records with repair iterations
SELECT action_name, record_id, MAX(attempt) as max_attempts
FROM prompt_trace
GROUP BY action_name, record_id
HAVING max_attempts > 0;
```

`compiled_prompt`, `llm_context` and `response_text` show as blobs in `sqlite3`. `agac traces` reads rows stored as text and also compressed rows.
