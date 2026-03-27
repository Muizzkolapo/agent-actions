---
title: Non-JSON Mode
sidebar_position: 3
---

# Non-JSON Mode

Use `json_mode: false` when working with models that cannot produce structured JSON reliably — local models via Ollama, small open-source models, or any provider where JSON formatting is unreliable.

## How It Works

In JSON mode (the default), each action uses a **schema** to define its output fields, and the framework injects the schema into the prompt so the LLM returns structured JSON.

In non-JSON mode, schemas are not injected. Instead, each action uses **`output_field`** to name a single field. The LLM returns plain text, and the framework maps the raw response to that field name.

| | JSON Mode (`true`) | Non-JSON Mode (`false`) |
|---|---|---|
| Output definition | `schema: my_schema` | `output_field: field_name` |
| LLM returns | Structured JSON matching schema | Plain text |
| Validation | Schema validation + reprompt | None (raw text stored) |
| Model requirements | Must support JSON output | Any model works |
| Fields per action | Multiple | One |

## Field-by-Field Construction

The key pattern: instead of one action producing a complex JSON object with many fields, you chain multiple actions where each produces **one field**. By the end of the pipeline, all fields accumulate into a complete record.

```yaml
defaults:
  json_mode: false
  model_vendor: ollama
  model_name: llama3

actions:
  - name: classify_topic
    output_field: topic              # LLM response → stored as "topic"
    prompt: $my_workflow.Classify

  - name: assess_sentiment
    dependencies: [classify_topic]
    output_field: sentiment          # LLM response → stored as "sentiment"
    prompt: $my_workflow.Sentiment

  - name: write_summary
    dependencies: [classify_topic, assess_sentiment]
    output_field: summary            # LLM response → stored as "summary"
    prompt: $my_workflow.Summary
```

After all three actions, the record contains `{topic, sentiment, summary}` — structured output assembled from plain text responses.

## Prompt Style

Non-JSON prompts should ask for **one answer** in the simplest possible format:

```markdown
{prompt Classify}
**Title**: {{ source.title }}
**Body**: {{ source.body }}

Classify this into ONE of: bug, feature_request, question, account_issue.

Answer with the category name only. Nothing else.
{end_prompt}
```

The "answer with X only, nothing else" instruction is important. Without it, smaller models tend to add explanations or formatting that pollute the field value.

## Per-Action Model Override

Non-JSON mode works with per-action model overrides. Use a cheap local model for simple classification, and override to a stronger model for actions that need better reasoning:

```yaml
defaults:
  json_mode: false
  model_vendor: ollama
  model_name: llama3                 # Cheap: local, no API cost

actions:
  - name: classify_issue
    output_field: issue_type
    prompt: $workflow.Classify        # Simple classification → local model is fine

  - name: draft_response
    output_field: suggested_response
    prompt: $workflow.Draft_Response
    model_vendor: openai              # Override: customer-facing text needs quality
    model_name: gpt-4o-mini
    api_key: OPENAI_API_KEY
```

## Guards Still Work

Guards evaluate upstream field values the same way regardless of JSON mode:

```yaml
  - name: draft_response
    output_field: suggested_response
    guard:
      condition: 'severity != "low"'  # Skip for low-severity → save tokens
      on_false: "skip"
```

## Context Scope Still Works

Progressive context narrowing applies identically. Later actions can observe specific upstream fields:

```yaml
  - name: draft_response
    context_scope:
      observe:
        - classify_issue.issue_type    # See the classified type
        - summarize_issue.summary      # See the summary
      drop:
        - source.body                  # Don't pass raw body → smaller prompt
```

## When to Use Non-JSON Mode

| Scenario | Recommendation |
|---|---|
| Ollama / local models | Use non-JSON mode |
| Small models (< 7B params) | Use non-JSON mode |
| Models without JSON support | Use non-JSON mode |
| Cost-sensitive pipelines | Mix: non-JSON for simple steps, JSON for complex |
| Prototyping / testing | Non-JSON is faster to set up (no schemas) |
| Production with capable models | JSON mode with schemas for validation |

