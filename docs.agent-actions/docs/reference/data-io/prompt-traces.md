---
title: Prompt Traces
sidebar_position: 6
---

# Prompt Traces

Every time an LLM action processes a record, Agent Actions captures a **prompt trace** — the compiled prompt sent to the model and the raw response received. Traces are stored in the `prompt_trace` table of your workflow's SQLite database and surfaced automatically in the Data Explorer.

## What Gets Captured

| Field | Description |
|-------|-------------|
| `compiled_prompt` | The fully rendered Jinja template sent to the LLM |
| `llm_context` | JSON-serialized context dict (template variables) |
| `response_text` | Raw LLM response text |
| `model_name` | Model identifier (e.g., `llama3.2:latest`, `gpt-4o-mini`) |
| `model_vendor` | Provider name (e.g., `ollama`, `openai`) |
| `run_mode` | `online` (real-time) or `batch` |
| `prompt_length` | Character count of the compiled prompt |
| `response_length` | Character count of the LLM response |
| `attempt` | Attempt number (0 = initial, 1+ = reprompt retries) |

Traces are linked to records by `action_name` and `record_id` (matching `source_guid`).

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

## Querying Traces Directly

You can query the `prompt_trace` table using SQLite:

```bash
sqlite3 my_workflow/agent_io/outputs.db
```

```sql
-- List all traced actions
SELECT DISTINCT action_name FROM prompt_trace;

-- Count traces per action
SELECT action_name, COUNT(*) FROM prompt_trace GROUP BY action_name;

-- View a specific record's trace
SELECT compiled_prompt, response_text, model_name
FROM prompt_trace
WHERE action_name = 'classify_issue'
  AND record_id = '2362b687-87c7-5534-83a1...'
ORDER BY attempt DESC
LIMIT 1;

-- Find records with reprompt retries
SELECT action_name, record_id, MAX(attempt) as max_attempts
FROM prompt_trace
GROUP BY action_name, record_id
HAVING max_attempts > 0;
```

## CLI Access

The `agac docs` command automatically includes traces in the generated `catalog.json` when the `prompt_trace` table exists. No additional flags are needed.

For workflows run before prompt trace support was added, the Data Explorer gracefully omits the trace accordion — records display exactly as before.

## VS Code Extension

The VS Code extension surfaces traces in the Query Results panel. When you preview data for an action, trace accordions appear in Card view alongside each record. The extension queries traces live from the SQLite database via the storage backend API.
