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
| **Reprompting** | On validation failure | Automatic retry with feedback |
| **Guards** | After validation | Filter or skip based on semantic conditions |

## Schema Analysis

Use the `schema` command to analyze your workflow's field dependencies before running:

```bash
agac schema -a workflow
```

This shows input/output schemas for each action, helping you catch field reference errors before making API calls.

### What It Shows

| Information | Description |
|-------------|-------------|
| **Input Fields** | Fields the action requires from upstream actions or source data |
| **Output Fields** | Fields the action produces for downstream actions |
| **Dependencies** | Which actions feed into each action |
| **Schema Sources** | Where each schema is defined |

### Dependency Validation

The workflow executor validates dependencies at runtime:

```yaml
# ERROR: Circular dependency
actions:
  - name: action_a
    dependencies: action_b  # Input source
  - name: action_b
    dependencies: [action_a]  # Circular!
```

### Vendor Compatibility

Feature support varies by vendor:

| Vendor | JSON Mode | Batch | Tools | Vision |
|--------|-----------|-------|-------|--------|
| OpenAI | ✅ | ✅ | ✅ | ✅ |
| Anthropic | ✅ | ✅ | ✅ | ✅ |
| Google | ✅ | ✅ | ✅ | ✅ |
| Groq | ✅ | ✅ | ✅ | ❌ |
| Mistral | ✅ | ✅ | ✅ | ❌ |
| Ollama | ✅ | ✅ | ✅ | ✅ |

## Schema Validation

Schema validation catches structural errors but can't verify semantic correctness. A response might match your schema but still contain incorrect information—that's where guards and reprompting come in.

For schema definition details, see [Schemas](../schemas/index.md).

## Validation Errors

### Error Categories

| Category | Examples |
|----------|----------|
| `template` | Missing variables, syntax errors |
| `context` | Missing fields, type mismatches |
| `dependency` | Circular deps, missing actions |
| `vendor` | Unsupported features |
| `path` | Missing files |
| `schema` | Output doesn't match schema |

### Runtime Error Format

Here's what validation output looks like when problems are found at runtime:

```
SchemaValidationError: Input schema validation failed for tool 'add_answer_text'
at target_word_counts -> correct_answer_words: 18 is not of type 'string'
[Context: function=add_answer_text, validation_type=input,
 error_path=target_word_counts -> correct_answer_words,
 failed_value=18, schema_constraint={'type': 'string'}]
```

The error context shows exactly what field failed and why, helping you fix issues quickly.

## Learn More

- **[Output Validation Pipeline](./output-validation.md)** - Multi-layer validation with guards and reprompting
- **[Reprompting](./reprompting.md)** - Automatic retry with presets (basic, smart, thorough)
- **[Troubleshooting](../../guides/troubleshooting.md)** - Debug errors, trace data lineage, common fixes
