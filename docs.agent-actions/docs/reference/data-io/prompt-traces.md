---
title: Prompt Traces
sidebar_position: 6
---

# Prompt Traces

> **Storage backend:** SQLite as of v0.2.6. Traces are stored in `agent_io/store/<workflow>.db`, table `prompt_trace`.

Every time an LLM action processes a record, Agent Actions captures a **prompt trace** — the compiled prompt sent to the model and the raw response received. Traces are stored in the `prompt_trace` table of your workflow's SQLite database and surfaced automatically in the Data Explorer.

## What Gets Captured

| Field | Description |
|-------|-------------|
| `compiled_prompt` | The fully rendered Jinja template sent to the LLM |
| `llm_context` | JSON-serialized context dict (template variables) |
| `response_text` | Raw LLM response text |
| `model_name` | Model identifier (e.g., `llama3.2:latest`, `gpt-4o-mini`) |
| `model_vendor` | Provider name (e.g., `ollama_local`, `openai`) |
| `run_mode` | `online` (real-time) or `batch` |
| `prompt_length` | Character count of the compiled prompt |
| `context_length` | Character count of the LLM context sent to the model |
| `response_length` | Character count of the LLM response |
| `attempt` | Attempt number (0 = initial, 1+ = repair iterations) |
| `source_guid` | Durable identity of the record that was prompted |
| `run_id` | The workflow run that wrote the row |
| `answered_under` | JSON: the config the record was answered under. Holds `config_hash` (prompt, schema and guard), `model_name`, `model_vendor`, `context_scope_hash` and `dependencies_hash` |

Traces carry two identifiers, and which one to join on depends on the question
you are asking.

- `source_guid` is the **durable** identity of the record that was prompted. It
  is the same value `record_disposition.record_id` holds, so it is the key for
  auditing across tables — "was this record prompted, and what did it get?" —
  and it is stable across runs.
- `record_id` is the **prepare-time** `target_id`, which is minted afresh every
  run (and, for a record an action expands into several, again per child). Join
  on it to ask "which prompt produced this record on this run", since it cannot
  reach a row an earlier run left behind. A record produced by an expansion
  reaches its prompt through its `parent_target_id`, because its own id did not
  exist yet when the prompt ran.

Both apply to online and batch alike. Rows written before `source_guid` and
`run_id` existed leave them `NULL`.

A [config edit](../cli/run#when-you-edit-the-workflow) re-runs nothing, so one action can
hold answers from more than one config. `answered_under` says which config answered each
record. It holds the same keys as the `answered_under` stamp of the action in
`agent_io/.agent_status.json`, so the two compare directly. Rows written before this column
existed leave it `NULL`.

```sql
SELECT source_guid, json_extract(answered_under, '$.model_name') AS model
FROM prompt_trace
WHERE action_name = 'classify';
```

## How Long Traces Are Kept

Traces stay across runs that build on what an action already answered: a
resumed run, and `agac retry`, keep the traces of the records they do not ask
again beside those of the records they do. They are cleared when the answers
they describe are replaced:

- `agac run --fresh` clears every action's traces.
- An action that runs again over every record clears its own traces, and those
  of every action reading it that runs again with it. That happens on
  `agac run --rerun`, when its stored output is gone, and when its limits or its
  staged input changed. A config edit alone clears nothing: the traces of the
  answers that stand are kept, each naming the config it was answered under.
- A failed or skipped action that runs again from the start clears its traces.

Otherwise, storage maintenance keeps the traces of the most recent
`storage.prompt_trace_retention_runs` calendar days on which traces were written
(`0` never prunes).

## Viewing Traces in the Data Explorer

Run `agac docs` to generate the documentation catalog, then open the Data Explorer in your browser.

### Card View

Cards display record sections in this order:

1. **Identity header** — record number, source GUID, file path
2. **Prompt Trace** — collapsible, shows the input sent to the LLM
3. **Action Output** — scalar fields first, then structured fields (arrays of objects rendered as sub-cards)
4. **Metadata** — collapsible, shown last

The Prompt Trace accordion displays the model name and run mode as badges. Click to expand and see two panels:

- **Compiled Prompt** (indigo header) — The exact prompt the LLM received, scrollable for long prompts
- **LLM Response** (teal header) — The raw text the LLM returned

Arrays of objects in the output section are rendered as **structured sub-cards** with labeled fields per item, rather than raw JSON. Long arrays show a "Show more" toggle.

### JSON View

In JSON view, traces appear as a nested `_trace` field on each record:

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

### Table View

Traces are excluded from Table view by design — prompt text is unreadable in table cells. Use Card view or JSON view to inspect traces.

## Reading a Trace

The store keeps the prompt, context and response text compressed. Read them with `agac traces`:

```bash
# Every trace of an action, as plain text
agac traces -w <workflow> -a classify_issue

# One record's traces (its target_id, or its parent_target_id if an expansion produced it)
agac traces -w <workflow> -a classify_issue --record <target_id>

# The same traces as a JSON list
agac traces -w <workflow> -a classify_issue --json
```

## Querying Trace Metadata

The other columns are plain values, so SQL still answers questions about traces:

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

`compiled_prompt`, `llm_context` and `response_text` read as blobs in `sqlite3`. A store written before compression keeps its older rows as text, and `agac traces` reads both.

## CLI Access

The `agac docs` command automatically includes traces in the generated `catalog.json` when the `prompt_trace` table exists. No additional flags are needed.

For workflows run before prompt trace support was added, the Data Explorer gracefully omits the trace accordion — records display exactly as before.

## VS Code Extension

The VS Code extension surfaces traces in the Query Results panel. When you preview data for an action, trace accordions appear in Card view alongside each record. The extension queries traces live from the SQLite database via the storage backend API.
