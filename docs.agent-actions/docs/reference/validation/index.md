---
title: Validation
sidebar_position: 1
---

# Validation

Validation finds errors before they cause cost. An LLM can return malformed JSON. A prompt can refer to a field that does not exist. With no validation, these errors occur deep in your workflow. They often occur after the workflow has already sent expensive API calls.

Agent Actions finds these errors with multiple validation layers. The layers start with schema analysis and end with runtime output validation.

## Validation Types

| Type | When | Purpose |
|------|------|---------|
| **Schema Analysis** | Before execution | Analyze field dependencies and schemas |
| **Schema Validation** | After LLM response | Validate output structure |
| **Guards** | Before a downstream action runs | Filter or skip a record. The guard uses semantic conditions on the upstream output. |
| **AI Expectations** | After schema validation | Deterministic checks and semantic checks that an LLM judges. Agent Actions observes and reports the results. |
| **Expectation Repair** | When an expectation fails | Generate the output again and validate it again until the suite passes. If the attempts are exhausted, the result is a verdict, a tombstone or a halt. |

## Schema Analysis

To analyze the field dependencies of your workflow before you run it, use the `schema` command:

```bash
agac schema -a workflow
```

The command shows the input schema and the output schema of each action. Thus you can find field reference errors before the workflow sends API calls.

### What It Shows

| Information | Description |
|-------------|-------------|
| **Action** and **Type** | Each action and its kind (`llm`, `tool`) |
| **Input** | The fields that the action requires from upstream actions or from the source data |
| **Output** | The fields that the action produces for downstream actions |

To show a data-flow tree, add `--verbose`. The tree lists the fields that each action expects and produces. To show machine-readable output, add `--json`.

### Dependency Validation

When Agent Actions loads the workflow configuration, it validates the dependencies. Thus Agent Actions refuses a cycle before any action runs (`Circular dependency detected: action_a -> action_b -> action_a`):

```yaml
# ERROR: Circular dependency
actions:
  - name: action_a
    dependencies: [action_b]  # Input source
  - name: action_b
    dependencies: [action_a]  # Circular!
```

### Vendor Compatibility

The supported features are different for each vendor:

| Vendor | JSON Mode | Batch | Tools | Vision |
|--------|-----------|-------|-------|--------|
| OpenAI | ✅ | ✅ (not with `base_url`) | ✅ | ✅ |
| Anthropic | ✅ | ✅ | ✅ | ✅ |
| Google | ✅ | ✅ | ✅ | ✅ |
| Groq | ✅ | ✅ | ✅ | ❌ |
| Ollama | ✅ | ✅ | ✅ | ✅ |

## Schema Validation

Schema validation finds structural errors. It cannot verify that the content is semantically correct. A response might match your schema and still contain incorrect information. Guards and expectations find these errors.

For the details of how to define a schema, see [Schemas](../schemas/index.md).

## Validation Errors

### Error Categories

A preflight issue about vendor support or about file paths has a `category` in its error context:

| Category | Examples |
|----------|----------|
| `vendor` | Unsupported features |
| `path` | Missing files |

### Runtime Error Format

This example shows the validation output when Agent Actions finds problems at runtime:

```
SchemaValidationError: Input schema validation failed for UDF 'add_answer_text'
at target_word_counts -> correct_answer_words: 18 is not of type 'string'
```

The message gives the name of the tool, the path to the field that failed and the reason. Thus you can fix the issue quickly. The context of the error also has `function`, `validation_type`, `error_path`, `failed_value` and `schema_constraint`.

## Learn More

- **[Output Validation Pipeline](./output-validation.md)** - Validation in multiple layers, with guards and expectations
- **[AI Expectations](./expectations.md)** - Deterministic checks and LLM-judged semantic checks with `expect:`, and the repair loop that generates the output again when a check fails
- **[Troubleshooting](../../guides/troubleshooting.md)** - Debug errors, trace the data lineage, and find common fixes
