# Validation Deprecation Tracker

This document tracks validators that have been removed from the codebase and explains the rationale behind their removal.

---

## Removed Validators (2026-01-15)

### TemplateVariableValidator

- **Removed:** 2026-01-15
- **File:** `agent_actions/validation/preflight/template_variable_validator.py`
- **Reason:** Redundant with static analyzer compile-time validation
- **Replaced by:** `WorkflowStaticAnalyzer` validates all `{{ action.field }}` template references against dependency output schemas at workflow load time
- **What it did:** Runtime validation that Jinja2 template variables exist in the prompt context
- **Why redundant:** With the context system redesign, context is deterministic from configuration. The static analyzer validates all template references before execution, making runtime checks unnecessary.
- **Migration:** Use `WorkflowStaticAnalyzer` at workflow load instead of runtime validation:
  ```python
  from agent_actions.validation.static_analyzer import WorkflowStaticAnalyzer

  analyzer = WorkflowStaticAnalyzer(workflow_config)
  result = analyzer.analyze()

  if not result.is_valid:
      print(result.format_report())
      raise ValueError("Static validation failed")
  ```

---

### ContextStructureValidator

- **Removed:** 2026-01-15
- **File:** `agent_actions/validation/preflight/context_structure_validator.py`
- **Reason:** Redundant with static analyzer and deterministic context from context_scope
- **Replaced by:** `WorkflowStaticAnalyzer` with `_check_context_scope_fields()` validation
- **What it did:** Runtime validation that context data has expected structure and required fields
- **Why redundant:** With `context_scope` directives (`observe`, `passthrough`, `drop`) and no fallbacks, context structure is deterministic from workflow configuration. The static analyzer validates all `context_scope` references against dependency schemas.
- **Migration:** The static analyzer automatically validates context_scope configuration:
  ```yaml
  actions:
    - name: processor
      depends_on: [extractor]
      context_scope:
        observe: [extractor.facts, extractor.summary]  # Validated at workflow load
  ```
  The analyzer ensures `extractor.facts` and `extractor.summary` exist in the `extractor` action's output schema.

---

### DependencyValidator

- **Removed:** 2026-01-15
- **File:** `agent_actions/validation/preflight/dependency_validator.py`
- **Reason:** Redundant with static analyzer's data flow graph validation
- **Replaced by:** `DataFlowGraph` in `WorkflowStaticAnalyzer`
- **What it did:** Runtime checks for circular dependencies, missing agent references, and self-dependencies
- **Why redundant:** The static analyzer's `DataFlowGraph` class already detects all structural dependency issues at compile-time:
  - Circular dependencies (A → B → C → A)
  - Missing dependency declarations
  - References to non-existent actions
  - Unreachable dependencies
- **Migration:** Use `WorkflowStaticAnalyzer` which builds and validates the dependency graph:
  ```python
  analyzer = WorkflowStaticAnalyzer(workflow_config)
  result = analyzer.analyze()

  # Get data flow summary if needed
  flow_summary = analyzer.get_data_flow_summary()
  print(f"Execution order: {flow_summary['execution_order']}")
  ```

---

### PreFlightValidator (Orchestrator)

- **Removed:** 2026-01-15
- **File:** `agent_actions/validation/preflight/preflight_validator.py`
- **Reason:** All child validators were redundant, making the orchestrator redundant
- **Replaced by:** `WorkflowStaticAnalyzer` provides comprehensive compile-time validation
- **What it did:** Orchestrated runtime validation by coordinating `TemplateVariableValidator`, `ContextStructureValidator`, and `DependencyValidator`
- **Why redundant:** Since all three child validators are redundant, the orchestrator has no remaining validators to coordinate.
- **Migration:** Replace runtime validation calls with static analyzer:

  **Before:**
  ```python
  from agent_actions.validation.preflight import PreFlightValidator

  validator = PreFlightValidator()
  result = validator.validate(
      template=raw_prompt,
      context=prompt_context,
      agent_name=agent_name,
      mode=mode,
  )
  result.raise_if_invalid()
  ```

  **After:**
  ```python
  # No runtime validation needed - static analyzer runs at workflow load
  # Context is deterministic from config, so what passes static analysis will work
  ```

---

## Removed Error Classes (2026-01-15)

### TemplateVariableError

- **Removed:** 2026-01-15
- **File:** `agent_actions/errors/preflight.py` (lines 97-148)
- **Reason:** Only used by removed `TemplateVariableValidator`
- **Replaced by:** `StaticTypeError` from `agent_actions.validation.static_analyzer.errors`

---

### ContextStructureError

- **Removed:** 2026-01-15
- **File:** `agent_actions/errors/preflight.py` (lines 150-201)
- **Reason:** Only used by removed `ContextStructureValidator`
- **Replaced by:** `StaticTypeError` from `agent_actions.validation.static_analyzer.errors`

---

### DependencyValidationError

- **Removed:** 2026-01-15
- **File:** `agent_actions/errors/preflight.py` (lines 203-246)
- **Reason:** Only used by removed `DependencyValidator`
- **Replaced by:** `StaticTypeError` from `agent_actions.validation.static_analyzer.errors`

---

## Context System Redesign Rationale

The removal of these validators is part of a larger context system redesign based on three key principles:

### 1. No Fallbacks
Eliminated all fallback paths that masked configuration errors. If a field reference is invalid, the system fails fast rather than silently substituting default values.

### 2. Context Decided by context_scope
Introduced `context_scope` directives that explicitly control data exposure:
- `observe`: Fields visible to LLM (extracted to llm_context)
- `passthrough`: Fields copied to output (also visible to LLM)
- `drop`: Fields removed from context (security)

This makes context construction deterministic and traceable.

### 3. Static Analyzer Validation
Added compile-time type checking via `WorkflowStaticAnalyzer` that validates:
- All field references exist in dependency schemas
- Dependencies are declared and reachable
- No circular dependencies
- context_scope references are valid

**Key Insight:** With these three principles, **context is deterministic from configuration**. What passes static analysis at workflow load will always work at runtime, eliminating the need for duplicate runtime validation.

---

## Validators Kept

The following validators remain because they perform runtime checks that cannot be done at compile-time:

### VendorCompatibilityValidator ✅
- **Location:** `agent_actions/validation/preflight/vendor_compatibility_validator.py`
- **Purpose:** Runtime vendor/API configuration validation
- **Why kept:** Vendor capabilities and API compatibility must be checked at runtime

### PathValidator ✅
- **Location:** `agent_actions/validation/preflight/path_validator.py`
- **Purpose:** Runtime file and directory existence checks
- **Why kept:** File existence cannot be validated at compile-time

### PreFlightValidationError ✅
- **Location:** `agent_actions/errors/preflight.py`
- **Purpose:** Base error class for validation errors
- **Why kept:** Used by static analyzer and remaining runtime validators

---

## Production Code Changes

### Files with Removed Validation Calls

1. **`agent_actions/prompt_generation/prompt_preparation_service.py`**
   - Removed: `_run_preflight_validation()` method and PreFlightValidator import
   - Impact: No runtime template validation (static analyzer validates at workflow load)

2. **`agent_actions/preprocessing/staging/staging_loader.py`**
   - Removed: PreFlightValidator instantiation and validation call
   - Impact: No runtime validation for staging mode

3. **`agent_actions/llm_invocation/batch/processing/batch_task_preparator.py`**
   - Removed: PreFlightValidator instantiation and validation call
   - Impact: No runtime validation for batch preparation

---

## Test Coverage

The static analyzer has comprehensive test coverage that replaces the removed validator tests:

- **31 tests** in `tests/validation/static_analyzer/test_workflow_static_analyzer.py`
- **7 tests** specifically for `context_scope` validation in `TestContextScopeValidation`
- Tests cover:
  - Field reference validation
  - Dependency validation
  - Circular dependency detection
  - context_scope validation (new)
  - Schema compatibility
  - Complex workflow patterns

---

## Future Considerations

If runtime validation is ever needed again, consider:

1. **Why is it needed?** If context is deterministic from config, runtime validation shouldn't be necessary.
2. **Can static analyzer cover it?** Most validation belongs at compile-time.
3. **Is it truly runtime-only?** Only things like file existence and API availability belong at runtime.

The goal is to catch all configuration errors at workflow load, not during execution.
