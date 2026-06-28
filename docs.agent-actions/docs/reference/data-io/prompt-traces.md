---
title: Prompt Traces
sidebar_position: 4
---

# Prompt Traces

Prompt traces capture the full LLM interaction for every action, enabling cost analysis, debugging, and reproducibility.

## What Gets Captured

| Field | Type | Description |
|-------|------|-------------|
| `action_name` | TEXT | The action that produced this trace |
| `record_id` | TEXT | Record identifier — `target_id` for online actions, `source_guid` for batch actions |
| `attempt` | INTEGER | Attempt number (0 = initial, 1+ = reprompt retries) |
| `compiled_prompt` | TEXT | The fully rendered Jinja template sent to the LLM |
| `llm_context` | TEXT | JSON-serialized context dict (template variables) |
| `response_text` | TEXT | Raw LLM response text |
| `model_name` | TEXT | Model identifier (e.g., `llama3.2:latest`, `gpt-4o-mini`) |
| `model_vendor` | TEXT | Provider name (e.g., `ollama_local`, `openai`) |
| `run_mode` | TEXT | `online` (real-time) or `batch` |
| `prompt_length` | INTEGER | Character count of the compiled prompt |
| `context_length` | INTEGER | Character count of the LLM context sent to the model |
| `response_length` | INTEGER | Character count of the LLM response |
| `created_at` | TEXT | ISO 8601 timestamp |

## Joining Traces to Records

Join `prompt_trace` against the `target_data` table using `action_name` and `record_id`.

For **online actions**, `record_id` equals `target_id`:

```sql
SELECT pt.*, td.record
FROM prompt_trace pt
JOIN target_data td ON pt.action_name = td.action_name
  AND pt.record_id = td.target_id
WHERE pt.action_name = 'extract_facts';
```

For **batch actions**, `record_id` equals `source_guid`:

```sql
SELECT pt.*, td.record
FROM prompt_trace pt
JOIN target_data td ON pt.action_name = td.action_name
  AND pt.record_id = json_extract(td.record, '$.source_guid')
WHERE pt.action_name = 'extract_facts';
```

## Retention

Prompt traces are retained for a configurable number of runs (default: 10). Set `StorageDefaults.PROMPT_TRACE_RETENTION_RUNS` or configure `storage.prompt_trace_retention_runs` in `agent_actions.yml` to adjust.
