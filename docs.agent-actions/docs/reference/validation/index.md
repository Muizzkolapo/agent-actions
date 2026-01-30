---
title: Validation
sidebar_position: 1
---

# Validation

What happens when an LLM returns malformed JSON, or a prompt references a field that doesn't exist? Without validation, these errors surface deep in your agentic workflow—often after expensive API calls have already been made.

Agent Actions catches these problems early. The validation system works at multiple stages, from configuration time through execution, ensuring you discover issues before they become costly failures.

## Validation Types

| Type | When | Purpose |
|------|------|---------|
| **Pre-flight** | Before execution | Catch configuration errors early |
| **Static Analysis** | Before execution | Type-check field references |
| **Schema Validation** | After LLM response | Validate output structure |
| **Reprompting** | On validation failure | Automatic retry with feedback |

## Pre-flight Validation

Think of pre-flight validation like a compiler for your agentic workflow. Just as a compiler catches syntax errors before your code runs, pre-flight validation catches configuration errors before any API calls are made.

```bash
agac run -a workflow --validate-only
```

This single command validates your entire configuration without spending a single API token.

### Checks Performed

| Validator | What It Checks |
|-----------|----------------|
| **Template Variables** | Jinja2 variables exist in context |
| **Context Structure** | Required fields present, correct types |
| **Dependencies** | No circular dependencies, all refs exist |
| **Vendor Compatibility** | Model supports requested features |
| **Paths** | Schema files, prompt files exist |

### Template Variable Validation

Consider what happens when a prompt references `{{ extract.facts }}` but the `extract` action hasn't been declared as a dependency. Agent Actions catches this mismatch before execution:

```yaml
# This prompt references {{ source.content }} and {{ extract.facts }}
prompt: |
  Analyze: {{ source.content }}
  Facts: {{ extract.facts }}
```

Errors if:
- `source.content` doesn't exist in input
- `extract` is not a declared dependency

### Dependency Validation

Detects circular dependencies and missing references:

```yaml
# ERROR: Circular dependency
actions:
  - name: action_a
    dependencies: action_b  # Input source
  - name: action_b
    dependencies: [action_a]  # Circular!
```

### Vendor Compatibility

Validates feature support per vendor:

| Vendor | JSON Mode | Batch | Tools | Vision |
|--------|-----------|-------|-------|--------|
| OpenAI | ✅ | ✅ | ✅ | ✅ |
| Anthropic | ✅ | ✅ | ✅ | ✅ |
| Google | ✅ | ✅ | ✅ | ✅ |
| Groq | ✅ | ✅ | ✅ | ❌ |
| Mistral | ✅ | ✅ | ✅ | ❌ |
| Ollama | ✅ | ❌ | ✅ | ✅ |

## Static Type Checking

Let's explore how Agent Actions provides TypeScript-like compile-time validation for your data flow:

```bash
agac run -a workflow --validate-only --static-typing
```

### What It Validates

1. **Agent exists** - Referenced agents are defined
2. **Dependency declared** - Referenced agents in `dependencies`
3. **Field exists** - Referenced fields in upstream output schema
4. **Type compatibility** - Field types match expectations

### Example Errors

When static typing catches a problem, it tells you exactly what went wrong and how to fix it:

```
[static] Action 'validate_facts' references field 'extract.nonexistent'
         but 'extract' output schema does not contain 'nonexistent'
         Available fields: facts, count, metadata

[static] Action 'process' references 'upstream_action.field'
         but 'upstream_action' is not in dependencies
```

This means you discover typos and wiring errors immediately—not after processing thousands of records.

### Disable Static Typing

Static type checking is powerful, but it requires schemas for all referenced actions. If you're iterating quickly or working with dynamic outputs, you can disable it:

```bash
agac run -a workflow --validate-only --no-static-typing
```

## Schema Validation

Schema validation catches structural errors but can't verify semantic correctness. A response might match your schema but still contain incorrect information—that's where guards and reprompting come in.

For schema definition details, see [Schemas](../schemas/index.md).

## Validation Errors

### Error Categories

| Category | Examples |
|----------|----------|
| `template` | Missing variables, syntax errors |
| `context` | Missing fields, type mismatches |
| `dependency` | Circular deps, missing agents |
| `vendor` | Unsupported features |
| `path` | Missing files |
| `static` | Field reference errors |

### Error Output Format

Here's what validation output looks like when problems are found. Notice how each error includes context to help you fix it quickly:

```
VALIDATION FAILED

2 error(s) found:

  ERROR: [validate_facts] Field 'extract.missing' not found
         Available fields: facts, count
         Hint: Check the 'extract' action output schema

  ERROR: [dependency] Circular dependency: a -> b -> a

1 warning(s):

  WARNING: [static] Unused dependency 'helper' in action 'process'
```

The "Available fields" hint is particularly useful—it shows you exactly what fields exist, so you can spot typos immediately.

## Learn More

- **[Reprompting](./reprompting.md)** - Automatic retry with presets (basic, smart, thorough)
- **[Troubleshooting](../../guides/troubleshooting.md)** - Debug errors, trace data lineage, common fixes
