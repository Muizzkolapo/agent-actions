# Specification: Redesigned Inspect Commands

**Status:** 📝 Proposed
**Created:** 2026-01-16
**Version:** 1.0

---

## Summary

Redesign the `agac inspect` command suite to fully leverage auto-inferred context dependencies and provide a unified, context_scope-aware workflow analysis experience.

---

## The Problem

### Old Design (Removed)

The previous `field-flow` and `conflicts` commands were built before the auto-inferred context dependency model existed. They had several limitations:

1. **No Context_Scope Awareness**
   - Commands didn't understand the relationship between `dependencies` and `context_scope`
   - Field flow analysis couldn't distinguish input sources from context sources
   - Conflict detection missed dependency relationships inferred from context_scope

2. **Redundant Functionality**
   - Multiple overlapping commands with similar analysis goals
   - `field-flow` for data flow, `conflicts` for field naming, `dependencies` for dependency graph
   - No unified view of workflow structure

3. **Incomplete Analysis**
   - Static analyzer only used explicit dependencies
   - Didn't show auto-inferred context dependencies
   - Couldn't visualize the full execution graph

**Example of the gap:**
```yaml
- name: generate_question
  dependencies: classify_type          # Input source
  context_scope:
    observe:
      - classify_type.quiz_type        # Input
      - extract_facts.summary          # Context (auto-inferred!)
```

Old commands would NOT show that `extract_facts` is a dependency!

---

## The Solution

### New Design Principles

| Principle | Description |
|-----------|-------------|
| **Context-Scope First** | All analysis uses `infer_dependencies()` to get complete graph |
| **Unified Interface** | Single inspect command with focused subcommands |
| **Semantic Clarity** | Distinguish input sources vs context sources in output |
| **Complete Analysis** | Show full dependency graph including auto-inferred context |
| **Migration Path** | Help users migrate from `primary_dependency` to new model |

---

## Proposed Command Structure

### Core Inspect Commands

```bash
agac inspect graph -a <workflow>           # Unified workflow visualization
agac inspect action -a <workflow> <action> # Detailed action analysis
agac inspect dependencies -a <workflow>    # Dependency model (already exists)
```

---

## Command 1: `inspect graph`

### Purpose
Unified workflow visualization showing:
- Complete dependency graph (input + context sources)
- Data flow with field lineage
- Execution order and merge patterns
- Configuration summary per action

### Usage
```bash
# Full workflow graph with field flow
agac inspect graph -a qanalabs_quiz_gen

# Focus on specific action's inputs/outputs
agac inspect graph -a qanalabs_quiz_gen --focus generate_question

# Show only dependency DAG (no fields)
agac inspect graph -a qanalabs_quiz_gen --dependencies-only

# JSON output for tooling
agac inspect graph -a qanalabs_quiz_gen --json
```

### Output Format

```
Workflow Dependency Graph: qanalabs_quiz_gen

┌─────────────────────────────────────────────────────────────┐
│ Execution Order: 1 → 2 → 3 → 4 → 5                          │
│ Total Actions: 5 (4 operational)                            │
│ Merge Patterns: 1 (aggregate_votes)                         │
└─────────────────────────────────────────────────────────────┘

Dependency Graph:

[source] ─────────┐
                  ├──> extract_facts (Type: Source)
[source] ─────────┘    ├─> schema: {text, summary, key_facts[]}
                       │
                       ├──> classify_type (Type: Single Input)
                       │    ├─> input: extract_facts
                       │    ├─> schema: {quiz_type, confidence}
                       │    │
                       │    ├──> generate_question (Type: Single Input + Context)
                       │         ├─> input: classify_type
                       │         ├─> context: extract_facts (auto-inferred)
                       │         ├─> schema: {question, answer, distractors[]}
                       │
                       └──> write_summary (Type: Single Input)
                            ├─> input: extract_facts
                            ├─> schema: {summary, word_count}

Legend:
  ──> Input dependency (in dependencies list)
  ··> Context dependency (auto-inferred from context_scope)
```

### Features

1. **Automatic Context Inference**
   - Uses `ContextScopeProcessor.infer_dependencies()` to build complete graph
   - Shows both input sources (solid lines) and context sources (dashed lines)

2. **Field-Level Lineage**
   - Shows schema for each action
   - Traces field references through the workflow
   - Highlights dropped fields and field transformations

3. **Merge Pattern Detection**
   - Identifies actions with multiple input sources
   - Shows `reduce_key` for MapReduce patterns
   - Validates merge compatibility

4. **Execution Model Clarity**
   - Clearly labels action types: Source, Single Input, Merge, Single Input + Context
   - Shows execution count implications
   - Highlights granularity changes (FILE vs RECORD)

---

## Command 2: `inspect action`

### Purpose
Deep dive into a specific action's configuration, showing:
- Complete dependency analysis (input + context)
- Field-level input/output schema
- Context_scope configuration
- Execution model and cardinality
- Validation errors/warnings

### Usage
```bash
# Detailed action analysis
agac inspect action -a qanalabs_quiz_gen generate_question

# Include field lineage for specific field
agac inspect action -a qanalabs_quiz_gen generate_question --trace-field distractors

# JSON output
agac inspect action -a qanalabs_quiz_gen generate_question --json
```

### Output Format

```
Action Analysis: generate_question

┌─────────────────────────────────────────────────────────────┐
│ Type: LLM Action (Single Input + Context)                   │
│ Model: anthropic/claude-sonnet-3-5                          │
│ Granularity: RECORD                                         │
│ Execution Count: 1 run per classify_type record             │
└─────────────────────────────────────────────────────────────┘

Dependencies (Auto-Inferred):

Input Sources (determines execution):
  • classify_type
    └─> Provides input records (one run per record)

Context Sources (auto-inferred from context_scope):
  • extract_facts
    └─> Loaded via historical lineage (same branch as classify_type)

Context Scope Configuration:

observe:
  • classify_type.quiz_type      (from input source)
  • classify_type.confidence     (from input source)
  • extract_facts.summary        (from context source)
  • extract_facts.key_facts      (from context source)

Output Schema:

fields:
  - name: question
    type: string
    required: true
    description: Generated quiz question

  - name: answer
    type: string
    required: true
    description: Correct answer

  - name: distractors
    type: array
    required: true
    description: Incorrect answer options

Field Lineage:

Inputs:
  classify_type.quiz_type     → Used in prompt context
  classify_type.confidence    → Used for validation
  extract_facts.summary       → Used in prompt context
  extract_facts.key_facts     → Used to generate distractors

Outputs:
  question    → Consumed by: [validate_question, format_quiz]
  answer      → Consumed by: [validate_question, format_quiz]
  distractors → Consumed by: [validate_distractors, format_quiz]

Validation: ✅ All references valid
```

### Features

1. **Complete Dependency View**
   - Shows input sources vs context sources
   - Explains execution model implications
   - Shows historical lineage loading strategy

2. **Context Scope Analysis**
   - Lists all observed/passthrough fields
   - Shows which fields come from input vs context
   - Validates field references against upstream schemas

3. **Field-Level Tracing**
   - Shows field lineage (where fields come from and go to)
   - Identifies dropped fields
   - Highlights field transformations

4. **Configuration Summary**
   - Shows execution model (granularity, cardinality)
   - Lists LLM configuration (model, temperature, etc.)
   - Shows conditional execution (guards, policies)

---

## Command 3: `inspect dependencies` (Already Exists)

### Current Status
✅ Already implemented correctly with auto-inferred dependencies!

### Purpose
Shows the simplified dependency model at a high level:
- Input sources (in `dependencies`)
- Context sources (auto-inferred from `context_scope`)
- Deprecated `primary_dependency` usage

### Keep As-Is
This command already works correctly and serves its purpose well.

---

## Implementation Plan

### Phase 1: Core Infrastructure (Week 1)

1. **Create Unified Graph Builder**
   - Extend `WorkflowStaticAnalyzer` to use `infer_dependencies()` everywhere
   - Build complete dependency graph (input + context)
   - Add semantic labels (input source, context source)

2. **Field Lineage Tracker**
   - Reuse/refactor existing `FieldFlowAnalyzer`
   - Integrate with auto-inferred dependencies
   - Track field provenance (input vs context)

3. **Schema Integration**
   - Integrate `WorkflowSchemaService` with new graph builder
   - Validate field references using complete dependency graph
   - Support field tracing across context boundaries

### Phase 2: Graph Command (Week 2)

1. **Implement `inspect graph`**
   - Build unified workflow visualization
   - Show dependency graph with input/context distinction
   - Integrate field-level lineage
   - Support focus mode for specific actions

2. **Rich Output Rendering**
   - Use Rich library for beautiful terminal output
   - Show execution flow with color coding
   - Add interactive focus mode (filter to subgraph)

### Phase 3: Action Command (Week 2)

1. **Implement `inspect action`**
   - Detailed single-action analysis
   - Show complete dependency breakdown
   - Field-level tracing
   - Validation and error reporting

2. **Context Scope Analysis**
   - Parse and display context_scope configuration
   - Show field mappings (input vs context)
   - Validate field references

### Phase 4: Testing & Documentation (Week 3)

1. **Comprehensive Tests**
   - Unit tests for graph builder
   - Integration tests for all commands
   - Test with complex real-world workflows

2. **Documentation**
   - Update CLI reference docs
   - Add examples to workflow guide
   - Migration guide from old commands

---

## Key Technical Details

### Using Auto-Inferred Dependencies

All commands must use the same dependency inference logic as runtime:

```python
from agent_actions.preprocessing.context.context_scope_processor import (
    ContextScopeProcessor,
)

# Get complete dependency set
workflow_actions = list(workflow.agent_configs.keys())
input_sources, context_sources = ContextScopeProcessor.infer_dependencies(
    action_config, workflow_actions, action_name
)

# Build complete graph
all_dependencies = input_sources + context_sources
```

### Backward Compatibility

1. **Support Legacy Workflows**
   - Handle workflows with `primary_dependency`
   - Show migration suggestions
   - Don't break on old patterns

2. **Gradual Deprecation**
   - Warn about deprecated patterns
   - Show recommended replacements
   - Provide migration commands

### Output Formats

1. **Rich Terminal Output** (default)
   - Beautiful terminal visualizations
   - Color-coded dependency types
   - Interactive filtering

2. **JSON Output** (--json flag)
   - Machine-readable format
   - For CI/CD integration
   - For custom tooling

3. **Markdown Output** (--markdown flag)
   - For documentation generation
   - For sharing in docs/reports
   - For PR descriptions

---

## Examples

### Example 1: Basic Workflow Graph

```bash
agac inspect graph -a simple_workflow
```

Shows:
- Complete dependency DAG
- Input sources (solid lines)
- Context sources (dashed lines)
- Execution order
- Action types

### Example 2: Complex Workflow with Merge

```bash
agac inspect graph -a qanalabs_quiz_gen --focus aggregate_votes
```

Shows:
- Focused view on `aggregate_votes` action
- Multiple input sources (merge pattern)
- Reduce key for merging
- Upstream and downstream dependencies

### Example 3: Detailed Action Analysis

```bash
agac inspect action -a qanalabs_quiz_gen generate_question
```

Shows:
- Complete dependency breakdown
- Field-level lineage
- Context_scope configuration
- Validation results
- Execution model

### Example 4: Field Tracing

```bash
agac inspect action -a qanalabs_quiz_gen generate_question --trace-field distractors
```

Shows:
- Where `distractors` field is produced
- What fields it depends on (lineage)
- Where it's consumed downstream
- Field transformations

---

## Migration from Old Commands

### Old: `agac inspect field-flow`
**Replacement:** `agac inspect graph` or `agac inspect action`

```bash
# Old
agac inspect field-flow -a workflow --verbose

# New (equivalent)
agac inspect graph -a workflow
agac inspect action -a workflow <action>  # For detailed view
```

### Old: `agac inspect conflicts`
**Replacement:** `agac inspect graph` with conflict detection

```bash
# Old
agac inspect conflicts -a workflow

# New (integrated)
agac inspect graph -a workflow
# Conflicts shown inline in graph view
```

---

## Success Criteria

1. **Complete Context Awareness**
   - ✅ All commands use `infer_dependencies()`
   - ✅ Show input sources vs context sources
   - ✅ Validate against complete dependency graph

2. **Unified Experience**
   - ✅ Single `inspect graph` command for workflow view
   - ✅ Single `inspect action` command for action detail
   - ✅ Consistent output format and terminology

3. **Field-Level Insight**
   - ✅ Show field lineage through workflow
   - ✅ Trace specific fields across actions
   - ✅ Validate field references

4. **Migration Support**
   - ✅ Identify deprecated `primary_dependency` usage
   - ✅ Provide migration suggestions
   - ✅ Support legacy workflows

5. **Developer Experience**
   - ✅ Beautiful terminal output
   - ✅ JSON output for tooling
   - ✅ Clear error messages and hints

---

## Open Questions

1. **Conflict Detection Integration**
   - Should conflict detection be integrated into `inspect graph`?
   - Or separate `inspect conflicts` subcommand?
   - Recommendation: Integrate into graph view with warnings

2. **Interactive Mode**
   - Should we add interactive mode for exploring large workflows?
   - Click on actions to drill down?
   - Recommendation: Future enhancement (v2)

3. **Diff Mode**
   - Should we support comparing two workflow versions?
   - Show dependency changes, field changes?
   - Recommendation: Future enhancement (v2)

4. **Schema Inference**
   - Should we auto-infer schemas for actions without explicit schemas?
   - Use historical data or static analysis?
   - Recommendation: Out of scope for this spec

---

## Related Documents

- [RFC: Simplified Dependency Model](./RFC_simplified_dependency_model.md)
- [SPEC: Auto-Inferred Context Dependencies](./SPEC_auto_inferred_context_dependencies.md)
- [Primary Dependency Migration Guide](../PRIMARY_DEPENDENCY_GUIDE.md)

---

## Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-01-16 | Claude | Initial specification |
