---
title: Non-JSON Mode
sidebar_position: 3
---

# Non-JSON Mode

Use `json_mode: false` for models that cannot reliably produce structured JSON. These models include local models through Ollama, small open-source models, and any provider where JSON formatting is unreliable.

## How It Works

In JSON mode (the default), each action uses a **schema** to define its output fields. The framework injects the schema into the prompt, so that the LLM returns structured JSON.

In non-JSON mode, the framework does not inject schemas. Each action uses **`output_field`** to name one field. The LLM returns plain text, and the framework maps the raw response to that field name.

| | JSON Mode (`true`) | Non-JSON Mode (`false`) |
|---|---|---|
| Output definition | `schema: my_schema` | `output_field: field_name` |
| LLM returns | Structured JSON that matches the schema | Plain text |
| Validation | Schema validation + `expect:` repair | None (the framework stores the raw text) |
| Model requirements | The model must support JSON output | Any model works |
| Fields per action | Multiple | One |

## Field-by-Field Construction

The key pattern is to chain several actions, each of which produces **one field**. One action does not produce a complex JSON object with many fields. At the end of the workflow, all fields accumulate into a complete record.

```yaml
defaults:
  json_mode: false
  model_vendor: ollama_local
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

After all three actions, the record contains `{topic, sentiment, summary}`. This structured output is assembled from plain text responses.

## Prompt Style

A non-JSON prompt should ask for **one answer** in the simplest possible format:

```markdown
{prompt Classify}
**Title**: {{ source.title }}
**Body**: {{ source.body }}

Classify this into ONE of: bug, feature_request, question, account_issue.

Answer with the category name only. Nothing else.
{end_prompt}
```

The "answer with X only, nothing else" instruction is important. Without the instruction, smaller models tend to add explanations or formatting that pollute the field value.

## Per-Action Model Override

Non-JSON mode works with per-action model overrides. Use a cheap local model for simple classification. For actions that need better reasoning, override the default with a stronger model:

```yaml
defaults:
  json_mode: false
  model_vendor: ollama_local
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

Guards evaluate upstream field values in the same way in JSON mode and in non-JSON mode:

```yaml
  - name: draft_response
    dependencies: [classify_issue]
    output_field: suggested_response
    guard:
      condition: 'classify_issue.issue_type != "question"'  # Skip for questions → save tokens
      on_false: "skip"
```

## Context Scope Still Works

Progressive context narrowing applies in the same way. Downstream actions can observe specific upstream fields:

```yaml
  - name: draft_response
    dependencies: [classify_issue, summarize_issue]
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
| Small models (fewer than 7B parameters) | Use non-JSON mode |
| Models without JSON support | Use non-JSON mode |
| Workflows where cost is important | Mix: non-JSON for simple actions, JSON for complex actions |
| Prototyping / testing | Non-JSON is faster to configure (no schemas) |
| Production with capable models | JSON mode with schemas for validation |

