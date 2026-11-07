---
title: Validation
sidebar_position: 1
---

# Validation

What happens when an LLM returns malformed JSON, or a prompt references a field that doesn't exist? Without validation, these errors surface deep in your agentic workflow—often after expensive API calls have already been made.

Agent Actions catches these problems through multiple validation layers, from schema analysis through runtime output validation.

## Validation Types

| Type | When | Purpose |
|------|------|---------|
| **Schema Analysis** | Before execution | Analyze field dependencies and schemas |
| **Schema Validation** | After LLM response | Validate output structure |
| **Guards** | Before a downstream action runs | Filter or skip a record based on semantic conditions on upstream output |
| **AI Expectations** | After schema validation | Deterministic + LLM-judged semantic checks, observed and reported |
| **Expectation Repair** | On expectation failure | Regenerate and re-validate until the suite passes, or exhaust into a verdict, tombstone, or halt |

## Schema Analysis

Use the `schema` command to analyze your workflow's field dependencies before running:

```bash
agac schema -a workflow
```

This shows input/output schemas for each action, helping you catch field reference errors before making API calls.

### What It Shows

| Information | Description |
|-------------|-------------|
| **Action** and **Type** | Each action and its kind (`llm`, `tool`) |
| **Input** | Fields the action requires from upstream actions or source data |
| **Output** | Fields the action produces for downstream actions |

Add `--verbose` for a data-flow tree that lists what each action expects and produces, or `--json` for machine-readable output.

### Dependency Validation

Loading the workflow config validates dependencies, so a cycle is refused before any action runs (`Circular dependency detected: action_a -> action_b -> action_a`):

```yaml
# ERROR: Circular dependency
actions:
  - name: action_a
    dependencies: [action_b]  # Input source
  - name: action_b
    dependencies: [action_a]  # Circular!
```

### Vendor Compatibility

Feature support varies by vendor:

| Vendor | JSON Mode | Batch | Tools | Vision |
|--------|-----------|-------|-------|--------|
| OpenAI | ✅ | ✅ (not with `base_url`) | ✅ | ✅ |
| Anthropic | ✅ | ✅ | ✅ | ✅ |
| Google | ✅ | ✅ | ✅ | ✅ |
| Groq | ✅ | ✅ | ✅ | ❌ |
| Ollama | ✅ | ✅ | ✅ | ✅ |

## Schema Validation

Schema validation catches structural errors but can't verify semantic correctness. A response might match your schema but still contain incorrect information—that's where guards and expectations come in.

For schema definition details, see [Schemas](../schemas/index.md).

## Validation Errors

### Error Categories

Preflight issues about vendor support and file paths carry a `category` in their error context:

| Category | Examples |
|----------|----------|
| `vendor` | Unsupported features |
| `path` | Missing files |

### Runtime Error Format

Here's what validation output looks like when problems are found at runtime:

```
SchemaValidationError: Input schema validation failed for UDF 'add_answer_text'
at target_word_counts -> correct_answer_words: 18 is not of type 'string'
```

The message names the UDF, the path to the field that failed and the reason, so you can fix the issue quickly. The error also carries `function`, `validation_type`, `error_path`, `failed_value` and `schema_constraint` in its context.

## Learn More

- **[Output Validation Pipeline](./output-validation.md)** - Multi-layer validation with guards and expectations
- **[AI Expectations](./expectations.md)** - Deterministic and LLM-judged semantic checks via `expect:`, and the repair loop that regenerates on failure
- **[Troubleshooting](../../guides/troubleshooting.md)** - Debug errors, trace data lineage, common fixes
