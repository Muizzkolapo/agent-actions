# Primary Dependency Guide

## Overview

When an action depends on multiple upstream actions, the `primary_dependency` field specifies which dependency provides the input dataset that determines execution count.

## The Problem

Without `primary_dependency`, actions with multiple dependencies incorrectly merge all dependency outputs:

```yaml
- name: generate_distractor_1
  dependencies:
    - add_answer_text      # 5 records
    - write_scenario       # 5 records
    - suggest_counts       # 5 records
  # Without primary_dependency: 15 executions (5 + 5 + 5) ❌
```

## The Solution

Use `primary_dependency` to specify the input source:

```yaml
- name: generate_distractor_1
  dependencies:
    - add_answer_text
    - write_scenario
    - suggest_counts
  primary_dependency: suggest_counts  # ✅ Only 5 executions
  context_scope:
    observe:
      - add_answer_text.*
      - write_scenario.*
      - suggest_counts.*
```

## How It Works

1. **Primary dependency** determines execution count (its files = number of executions)
2. **Non-primary dependencies** loaded via historical context using lineage matching
3. **All dependencies** MUST be declared in `context_scope` (explicit field loading)

## Configuration Rules

### 1. Explicit Primary Dependency

```yaml
dependencies: [dep_A, dep_B, dep_C]
primary_dependency: dep_B  # Use dep_B as input source
context_scope:
  observe:
    - dep_A.*
    - dep_B.*  # Primary
    - dep_C.*
```

### 2. Convention (No Primary Specified)

If `primary_dependency` is not specified, the **last dependency in the list** is used:

```yaml
dependencies: [dep_A, dep_B, dep_C]  # dep_C will be primary by convention
context_scope:
  observe:
    - dep_A.*
    - dep_B.*
    - dep_C.*  # Primary by convention
```

### 3. All Dependencies Must Be Declared

**REQUIRED:** All dependencies must have explicit field declarations in `context_scope`:

```yaml
# ❌ ERROR: dep_C not declared
dependencies: [dep_A, dep_B, dep_C]
context_scope:
  observe:
    - dep_A.*
    - dep_B.*
    # Missing dep_C - will cause ConfigurationError
```

```yaml
# ✅ CORRECT: All dependencies declared
dependencies: [dep_A, dep_B, dep_C]
context_scope:
  observe:
    - dep_A.field1
    - dep_B.*
    - dep_C.field2
```

## Validation

The system performs **bidirectional validation** at workflow load time:

### Primary Dependency Validation

1. ✅ **Valid:** Primary dependency exists in dependencies list
2. ❌ **Error:** Primary dependency not in list
3. ❌ **Error:** Primary dependency specified but no dependencies

### Bidirectional Context Scope Validation

**Forward Check (New):** All dependencies in `dependencies` must be in `context_scope`
```yaml
dependencies: [dep_A, dep_B, dep_C]
context_scope:
  observe:
    - dep_A.field1
    - dep_B.field2
    # ❌ ERROR: dep_C not declared in context_scope
```

**Reverse Check (Existing):** All dependencies in `context_scope` must be in `dependencies`
```yaml
dependencies: [dep_A]  # Only declares dep_A
context_scope:
  observe:
    - dep_A.field1
    - dep_B.field2  # ❌ ERROR: dep_B not in dependencies list
```

This ensures complete consistency between your dependency declarations and field access patterns.

## Example Workflow

```yaml
actions:
  - name: extract_questions
    schema:
      question: string
      topic: string

  - name: classify_type
    dependencies: [extract_questions]
    schema:
      question_type: string

  - name: suggest_word_counts
    dependencies: [extract_questions]
    schema:
      word_count_guidance: object

  - name: generate_answer
    dependencies:
      - extract_questions
      - classify_type
      - suggest_word_counts
    primary_dependency: extract_questions  # 5 questions = 5 executions
    context_scope:
      observe:
        - extract_questions.*        # Primary input
        - classify_type.question_type
        - suggest_word_counts.word_count_guidance
```

## Migration Guide

### Before (Incorrect Behavior)

```yaml
- name: my_action
  dependencies: [dep_A, dep_B, dep_C]  # Merges all → wrong count
  # Missing context_scope
```

### After (Correct Behavior)

```yaml
- name: my_action
  dependencies: [dep_A, dep_B, dep_C]
  primary_dependency: dep_C  # Or omit to use last by convention
  context_scope:
    observe:
      - dep_A.field1
      - dep_B.*
      - dep_C.*  # Primary
```

## Best Practices

1. **Always declare all dependencies** in `context_scope` to avoid errors
2. **Use explicit `primary_dependency`** for clarity when order matters
3. **Use wildcard (`.*`)** for primary dependency to load all fields
4. **Use specific fields** for non-primary dependencies to minimize data loading

## Error Messages

### Missing Context Scope Declaration

```
ConfigurationError: Dependency 'dep_C' declared but not referenced in context_scope.
Add field declarations (e.g., 'dep_C.*' or 'dep_C.field_name').
```

**Fix:** Add `dep_C.*` or specific fields to `context_scope.observe`

### Invalid Primary Dependency

```
ConfigurationError: primary_dependency 'dep_X' not found in dependencies list: ['dep_A', 'dep_B']
```

**Fix:** Either remove `primary_dependency` or add `dep_X` to `dependencies` list

## See Also

- [RFC: Multiple Dependencies with Primary Input](specs/RFC_multiple_dependencies_primary_input.md) - Full technical specification
- [Anatomy of an Action](personal_docs/anatomy_action.md) - Context and field loading architecture
