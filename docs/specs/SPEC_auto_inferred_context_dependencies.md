# Specification: Auto-Inferred Context Dependencies

**Status:** ✅ Implemented
**Created:** 2026-01-16
**Version:** 1.0

---

## Summary

Simplify the dependency model by auto-inferring context dependencies from `context_scope` declarations, eliminating redundancy and the need for `primary_dependency`.

---

## The Problem

### Current Design (Redundant)

```yaml
- name: generate_distractor_1
  dependencies: [add_answer_text, suggest_distractor_counts, write_scenario_question]
  primary_dependency: add_answer_text
  context_scope:
    observe:
      - add_answer_text.*
      - suggest_distractor_counts.*
      - write_scenario_question.*
```

**Issues:**
- Dependencies declared **twice** (in `dependencies` AND `context_scope`)
- `primary_dependency` is confusing ("primary for what?")
- Easy to make mistakes (list all as dependencies when only one is input)
- Requires bidirectional validation

---

## The Solution

### New Design (Auto-Inferred)

```yaml
- name: generate_distractor_1
  dependencies: add_answer_text           # Input source only
  context_scope:
    observe:
      - add_answer_text.*                  # ← Input (in dependencies)
      - suggest_distractor_counts.*        # ← Context (auto-inferred)
      - write_scenario_question.*          # ← Context (auto-inferred)
```

**Rule:**
```
input_sources   = dependencies
context_sources = actions_in_context_scope - dependencies
```

---

## Design Principles

| Principle | Description |
|-----------|-------------|
| **Single Source of Truth** | `context_scope` declares ALL data access |
| **DRY** | No redundant declarations |
| **Semantic Clarity** | `dependencies` = input sources only |
| **Auto-Inference** | Context dependencies detected automatically |
| **Backward Compatible** | Existing behaviors preserved |

---

## Two Supported Patterns

### Pattern 1: Single Input + Context Dependencies

**Use case:** One action provides input records, others provide contextual data.

```yaml
- name: generate_distractor_1
  dependencies: add_answer_text           # Single input source
  context_scope:
    observe:
      - add_answer_text.*                  # Input
      - suggest_distractor_counts.*        # Context (auto-inferred)
      - write_scenario_question.*          # Context (auto-inferred)
```

**Behavior:**
- Input files from: `target/add_answer_text/`
- Execution count: Number of records in `add_answer_text`
- Context loaded via: Historical loader (lineage matching)

### Pattern 2: Multiple Inputs (Merge by Key)

**Use case:** Aggregate/merge records from multiple actions.

```yaml
- name: aggregate_votes
  dependencies: [validate_1, validate_2, validate_3]
  reduce_key: parent_target_id            # Merge key
  context_scope:
    observe:
      - validate_1.*
      - validate_2.*
      - validate_3.*
```

**Behavior:**
- Input files from: All 3 directories merged
- Merge by: `parent_target_id` field
- Execution count: Number of unique `parent_target_id` values
- No context dependencies (all are inputs)

---

## Auto-Inference Algorithm

```python
def infer_dependencies(action_config: Dict, workflow_actions: List[str]) -> Tuple[List[str], List[str]]:
    """
    Infer input sources and context sources from config.

    Returns:
        (input_sources, context_sources)
    """
    # 1. Get explicit dependencies (input sources)
    deps = action_config.get("dependencies", [])
    input_sources = [deps] if isinstance(deps, str) else list(deps)

    # 2. Parse context_scope to find all referenced actions
    context_scope = action_config.get("context_scope", {})
    referenced_actions = set()

    for field_ref in context_scope.get("observe", []) + context_scope.get("passthrough", []):
        action_name = field_ref.split(".")[0]  # "action.field" → "action"
        referenced_actions.add(action_name)

    # 3. Auto-infer context sources
    context_sources = referenced_actions - set(input_sources)

    # 4. Validate all referenced actions exist
    for action in referenced_actions:
        if action not in workflow_actions:
            raise ConfigurationError(f"Action '{action}' not found in workflow")

    return input_sources, list(context_sources)
```

---

## Execution Flow

### Example: `generate_distractor_1`

**Config:**
```yaml
dependencies: add_answer_text
context_scope:
  observe:
    - add_answer_text.*
    - suggest_distractor_counts.*
    - write_scenario_question.*
```

**Inferred:**
```python
input_sources = ["add_answer_text"]
context_sources = ["suggest_distractor_counts", "write_scenario_question"]
```

**Execution (5 records in add_answer_text):**

```
┌─────────────────────────────────────────────────────────────────┐
│ FOR each record in target/add_answer_text/ (5 iterations)       │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. Load input record                                           │
│     ├── source_guid: "abc-123"                                  │
│     └── lineage: ["extract_raw_qa", "flatten_2", "classify_2"]  │
│                                                                 │
│  2. Load context via historical loader (same lineage)           │
│     ├── suggest_distractor_counts (lineage match) ✓             │
│     └── write_scenario_question (lineage match) ✓               │
│                                                                 │
│  3. Build field_context                                         │
│     {                                                           │
│       "add_answer_text": { input record data },                 │
│       "suggest_distractor_counts": { historical data },         │
│       "write_scenario_question": { historical data }            │
│     }                                                           │
│                                                                 │
│  4. Render prompt template with field_context                   │
│                                                                 │
│  5. Execute LLM                                                 │
│                                                                 │
│  6. Write output to target/generate_distractor_1/               │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## What Gets Eliminated

| Old Field | Status | Replacement |
|-----------|--------|-------------|
| `primary_dependency` | **REMOVED** | Use single `dependencies` value |
| Redundant deps in list | **REMOVED** | Auto-inferred from `context_scope` |
| Bidirectional validation | **SIMPLIFIED** | One-way: context_scope → infer |

---

## Implementation Tasks

### Phase 1: Core Logic

#### Task 1.1: Add `infer_dependencies()` Method
**File:** `agent_actions/preprocessing/context/context_scope_processor.py`

```python
@staticmethod
def infer_dependencies(
    action_config: Dict,
    workflow_actions: List[str]
) -> Tuple[List[str], List[str]]:
    """
    Infer input sources and context sources.

    Args:
        action_config: Action configuration dict
        workflow_actions: List of all action names in workflow

    Returns:
        (input_sources, context_sources)
    """
    # Implementation as shown above
```

#### Task 1.2: Update Directory Resolution
**File:** `agent_actions/orchestration/agent_runner.py`

Modify `_resolve_dependency_directories()`:
- Only return directories for `input_sources`
- Do NOT return directories for `context_sources`

#### Task 1.3: Update Context Building
**File:** `agent_actions/preprocessing/context/context_scope_processor.py`

Modify `build_field_context_with_history()`:
- Use `infer_dependencies()` to determine context sources
- Load context sources via historical loader
- Load input sources from current record

### Phase 2: Validation

#### Task 2.1: Validate Referenced Actions Exist
**File:** `agent_actions/validation/static_analyzer/workflow_static_analyzer.py`

Add validation:
- All actions in `context_scope` must exist in workflow
- Warn if `primary_dependency` is used (deprecated)

### Phase 3: Deprecation

#### Task 3.1: Deprecate `primary_dependency`
- Add deprecation warning when `primary_dependency` is present
- Log migration suggestion

### Phase 4: Documentation

#### Task 4.1: Update Documentation
- Update `PRIMARY_DEPENDENCY_GUIDE.md`
- Add migration examples
- Update user guide

---

## Validation Rules

### Rule 1: All Referenced Actions Must Exist

```yaml
# ❌ ERROR: nonexistent_action not in workflow
context_scope:
  observe:
    - nonexistent_action.field
```

### Rule 2: Multiple Inputs Should Have reduce_key

```yaml
# ⚠️ WARNING: Multiple inputs without reduce_key
dependencies: [action_A, action_B]
# Missing: reduce_key
```

### Rule 3: Deprecated primary_dependency

```yaml
# ⚠️ WARNING: primary_dependency is deprecated
dependencies: [action_A, action_B]
primary_dependency: action_A  # Use: dependencies: action_A
```

---

## Migration Guide

### Before (Old Style)

```yaml
- name: my_action
  dependencies: [dep_A, dep_B, dep_C]
  primary_dependency: dep_A
  context_scope:
    observe:
      - dep_A.*
      - dep_B.*
      - dep_C.*
```

### After (New Style)

```yaml
- name: my_action
  dependencies: dep_A              # Only the input source
  context_scope:
    observe:
      - dep_A.*                    # Input
      - dep_B.*                    # Context (auto-inferred)
      - dep_C.*                    # Context (auto-inferred)
```

---

## Real-World Example

### Quiz Generation Workflow

**Action: `write_scenario_question`**

```yaml
- name: write_scenario_question
  dependencies: get_authoring_prompt        # Input source
  context_scope:
    observe:
      - flatten_raw_questions.question_text     # Context
      - flatten_raw_questions.answer_text       # Context
      - flatten_raw_questions.source_quote      # Context
      - flatten_raw_questions.difficulty_reason # Context
      - classify_question_type.quiz_type        # Context
      - get_authoring_prompt.authoring_prompt   # Input
      - get_authoring_prompt.suggested_opener   # Input
  prompt: $qanalabs_quiz_gen.Write_Scenario_Question
```

**Inferred:**
- **Input:** `get_authoring_prompt`
- **Context:** `flatten_raw_questions`, `classify_question_type`

**Action: `generate_distractor_1`**

```yaml
- name: generate_distractor_1
  dependencies: add_answer_text             # Input source
  context_scope:
    observe:
      - add_answer_text.*                   # Input
      - suggest_distractor_counts.*         # Context
      - write_scenario_question.question    # Context
      - write_scenario_question.options     # Context
      - write_scenario_question.answer      # Context
      - write_scenario_question.answer_explanation  # Context
  prompt: $qanalabs_quiz_gen.Generate_Distractor_1
```

**Inferred:**
- **Input:** `add_answer_text`
- **Context:** `suggest_distractor_counts`, `write_scenario_question`

---

## Success Criteria

- [x] Auto-inference correctly identifies input vs context sources
- [x] Single input + context pattern works correctly
- [x] Multiple inputs merge pattern works correctly
- [x] Historical loader loads context with lineage matching
- [x] Validation catches invalid action references (runtime in `infer_dependencies()`)
- [x] Deprecation warning for `primary_dependency`
- [x] All existing tests pass
- [x] Documentation updated

---

## File Changes Summary

| File | Change | Status |
|------|--------|--------|
| `context_scope_processor.py` | Add `infer_dependencies()` method | ✅ Done |
| `context_scope_processor.py` | Add `extract_action_names_from_context_scope()` | ✅ Done |
| `context_scope_processor.py` | Update `build_field_context_with_history()` | ✅ Done |
| `context_scope_processor.py` | Remove REALTIME fallback, require `agent_indices` | ✅ Done |
| `agent_runner.py` | Update `_resolve_dependency_directories()` | ✅ Done |
| `agent_runner.py` | Add deprecation warning for `primary_dependency` | ✅ Done |
| `workflow_static_analyzer.py` | Remove `_check_primary_dependency()` (dead code) | ✅ Done |
| `test_infer_dependencies.py` | Add 20 tests for dependency inference | ✅ Done |
| `test_agent_runner_dependency_resolution.py` | Add 8 tests for directory resolution | ✅ Done |

---

**End of Specification**
