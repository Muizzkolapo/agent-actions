# RFC: Simplified Dependency Model with Auto-Inferred Context Dependencies

**Status:** Draft
**Created:** 2026-01-16
**Author:** System Architecture
**Related:** RFC_multiple_dependencies_primary_input.md, #732

---

## Table of Contents

1. [Overview](#overview)
2. [Current Problem](#current-problem)
3. [Proposed Solution](#proposed-solution)
4. [Design Principles](#design-principles)
5. [Configuration Schema](#configuration-schema)
6. [Behavior Specification](#behavior-specification)
7. [Implementation Plan](#implementation-plan)
8. [Migration Strategy](#migration-strategy)
9. [Examples](#examples)
10. [Testing Strategy](#testing-strategy)

---

## Overview

This RFC proposes a simplified dependency model that eliminates redundancy by auto-inferring context dependencies from `context_scope` declarations.

### Key Changes

1. **Eliminate `primary_dependency`** - No longer needed
2. **Unified `dependencies` field** - Represents primary input sources
3. **Auto-infer context dependencies** - Parse `context_scope` to detect additional dependencies
4. **Single source of truth** - `context_scope` declares all data access
5. **Support both patterns:**
   - Single input + context deps
   - Multiple inputs merged by key

---

## Current Problem

### Problem 1: Redundant Declarations

```yaml
# Current design - declares dependencies TWICE
dependencies: [add_answer_text, write_scenario_question, suggest_distractor_counts]
primary_dependency: add_answer_text
context_scope:
  observe:
    - add_answer_text.*               # Duplicate
    - write_scenario_question.*        # Duplicate
    - suggest_distractor_counts.*      # Duplicate
```

**Issues:**
- Same information in 2-3 places
- Easy to get out of sync
- Requires bidirectional validation
- Not DRY

### Problem 2: Unclear Semantics

```yaml
primary_dependency: add_answer_text  # Primary for what?
```

**Issues:**
- "Primary" doesn't clearly communicate intent
- Requires documentation to understand
- Not self-explanatory

### Problem 3: Complex Mental Model

Users must understand:
1. `dependencies` = all upstream actions
2. `primary_dependency` = which one provides input
3. `context_scope` = must match dependencies
4. Bidirectional validation rules

---

## Proposed Solution

### Unified Model

```yaml
dependencies: <primary_input_source(s)>
context_scope: <all_data_access>

# System auto-infers:
# context_deps = actions referenced in context_scope BUT NOT in dependencies
```

### Two Patterns, One Model

**Pattern 1: Single Input + Context Dependencies**
```yaml
dependencies: add_answer_text  # THE input source
context_scope:
  observe:
    - add_answer_text.*                # Input
    - write_scenario_question.*        # Context (auto-inferred)
    - suggest_distractor_counts.*      # Context (auto-inferred)
```

**Pattern 2: Multiple Inputs (Merge by Key)**
```yaml
dependencies: [validate_answer_1, validate_answer_2, validate_answer_3]
reduce_key: parent_target_id  # Merge all 3 by this key
context_scope:
  observe:
    - validate_answer_1.*    # All are inputs
    - validate_answer_2.*
    - validate_answer_3.*
```

---

## Design Principles

### Principle 1: Single Source of Truth

`context_scope` is the authoritative declaration of all data access.

### Principle 2: Semantic Clarity

- `dependencies` = "These provide my primary input data"
- `context_scope` = "Here's all the data I access"
- Context-only deps = Inferred automatically

### Principle 3: DRY (Don't Repeat Yourself)

Declare each dependency relationship once, not twice.

### Principle 4: Backward Compatible Behavior

- Single dependency → Same behavior
- Multiple dependencies → Merge by key (existing behavior)
- Parallel branches → Merge branches (existing behavior)

### Principle 5: Fail Fast

Validation errors at workflow load time, not runtime.

---

## Configuration Schema

### Updated Action Schema

```yaml
actions:
  - name: string                      # Action name (required)
    dependencies: string | array      # NEW: Primary input source(s)
    reduce_key: string                # For multiple deps: merge by this field
    context_scope:                    # ALL data access declarations
      observe: array<string>
      passthrough: array<string>
      drop: array<string>
    # ... other fields
```

### Field Specifications

#### `dependencies`

**Type:** `string` or `array<string>`
**Required:** No
**Semantics:** Primary input source(s) that determine execution count

**Single value:**
```yaml
dependencies: action_A  # action_A provides input dataset
```

**Multiple values:**
```yaml
dependencies: [action_A, action_B, action_C]
reduce_key: parent_id  # Merge all 3 by parent_id
```

**Behavior:**
- Single: Input from this action's output directory
- Multiple: Merge all outputs by `reduce_key` field

#### `context_scope`

**Type:** `object`
**Required:** Yes (if any data access needed)
**Semantics:** Declares ALL data access (input + context)

**Rules:**
1. ALL actions referenced must either be:
   - In `dependencies` (input sources), OR
   - Resolvable as upstream actions (context sources)
2. System auto-infers context dependencies from references NOT in `dependencies`
3. Validation error if referenced action doesn't exist in workflow

---

## Behavior Specification

### Dependency Resolution Algorithm

```python
def resolve_dependencies(action_config, workflow_actions):
    """
    Resolve input sources and context dependencies.

    Returns:
        input_sources: List of actions providing input files
        context_sources: List of actions providing context only
    """
    # Step 1: Parse explicit dependencies (input sources)
    deps = action_config.get("dependencies", [])
    input_sources = [deps] if isinstance(deps, str) else deps

    # Step 2: Parse context_scope to find all referenced actions
    context_scope = action_config.get("context_scope", {})
    all_refs = set()

    for field_ref in context_scope.get("observe", []) + context_scope.get("passthrough", []):
        action_name, _ = parse_field_reference(field_ref)  # e.g., "action_A.field1"
        all_refs.add(action_name)

    # Step 3: Auto-infer context dependencies
    context_sources = all_refs - set(input_sources)

    # Step 4: Validate all referenced actions exist
    for action_name in all_refs:
        if action_name not in workflow_actions:
            raise ConfigurationError(
                f"Action '{action_name}' referenced in context_scope but not found in workflow"
            )

    return input_sources, list(context_sources)
```

### Execution Flow

#### Pattern 1: Single Input + Context

```yaml
dependencies: action_A
context_scope:
  observe:
    - action_A.*
    - action_B.field1
    - action_C.field2
```

**Resolution:**
```python
input_sources = ["action_A"]
context_sources = ["action_B", "action_C"]  # Auto-inferred
```

**Execution:**
1. Load input files from: `target/action_A/`
2. For each input record:
   - Match `action_B` data by lineage (historical loader)
   - Match `action_C` data by lineage (historical loader)
   - Execute action with all 3 contexts

**Execution count:** Number of records in `action_A`

#### Pattern 2: Multiple Inputs (Merge)

```yaml
dependencies: [action_A, action_B, action_C]
reduce_key: parent_id
context_scope:
  observe:
    - action_A.*
    - action_B.*
    - action_C.*
```

**Resolution:**
```python
input_sources = ["action_A", "action_B", "action_C"]
context_sources = []  # All are input sources
```

**Execution:**
1. Load input files from: `target/action_A/`, `target/action_B/`, `target/action_C/`
2. Merge all records by `parent_id` field
3. For each unique `parent_id`:
   - Group all records with matching `parent_id`
   - Execute action with grouped data

**Execution count:** Number of unique `parent_id` values

---

## Implementation Plan

### Phase 1: Core Infrastructure (Week 1)

#### Task 1.1: Update Dependency Parser
**File:** `agent_actions/preprocessing/context/context_scope_processor.py`

**New Method:**
```python
@staticmethod
def infer_context_dependencies(
    dependencies: Union[str, List[str], None],
    context_scope: Optional[Dict],
    workflow_actions: List[str]
) -> Tuple[List[str], List[str]]:
    """
    Infer input sources and context dependencies.

    Args:
        dependencies: Explicit input sources
        context_scope: Context scope configuration
        workflow_actions: All action names in workflow

    Returns:
        (input_sources, context_sources)

    Raises:
        ConfigurationError: If referenced action not in workflow
    """
    # Normalize dependencies to list
    if dependencies is None:
        input_sources = []
    elif isinstance(dependencies, str):
        input_sources = [dependencies]
    else:
        input_sources = list(dependencies)

    # Parse context_scope references
    if not context_scope:
        return input_sources, []

    all_field_refs = []
    all_field_refs.extend(context_scope.get("observe", []))
    all_field_refs.extend(context_scope.get("passthrough", []))

    # Extract unique action references
    referenced_actions = set()
    for field_ref in all_field_refs:
        try:
            action_name, _ = ContextScopeProcessor.parse_field_reference(field_ref)
            referenced_actions.add(action_name)
        except ValueError:
            continue

    # Validate all referenced actions exist in workflow
    for action_name in referenced_actions:
        if action_name not in workflow_actions:
            raise ConfigurationError(
                f"Action '{action_name}' referenced in context_scope "
                f"but not found in workflow actions: {workflow_actions}",
                context={
                    "referenced_action": action_name,
                    "workflow_actions": workflow_actions
                }
            )

    # Infer context dependencies (in context_scope but NOT in dependencies)
    context_sources = list(referenced_actions - set(input_sources))

    return input_sources, context_sources
```

**Tests:**
- `test_infer_context_dependencies_single_input`
- `test_infer_context_dependencies_multiple_inputs`
- `test_infer_context_dependencies_no_context`
- `test_infer_context_dependencies_invalid_action_error`

---

#### Task 1.2: Update Validation Logic
**File:** `agent_actions/validation/static_analyzer/workflow_static_analyzer.py`

**New Method:**
```python
def validate_dependency_consistency(
    self,
    action_config: Dict,
    action_name: str,
    workflow_actions: List[str]
) -> None:
    """
    Validate dependency declarations are consistent.

    Rules:
    1. All actions in context_scope must exist in workflow
    2. If multiple dependencies, reduce_key should be present
    3. Dependencies must come before this action in workflow

    Raises:
        ConfigurationError: If validation fails
    """
    dependencies = action_config.get("dependencies")
    context_scope = action_config.get("context_scope")
    reduce_key = action_config.get("reduce_key")

    # Infer input and context sources
    input_sources, context_sources = ContextScopeProcessor.infer_context_dependencies(
        dependencies,
        context_scope,
        workflow_actions
    )

    # Validate multiple inputs have reduce_key
    if len(input_sources) > 1 and not reduce_key:
        self.warnings.append({
            "action": action_name,
            "type": "missing_reduce_key",
            "message": (
                f"Action '{action_name}' has multiple input sources {input_sources} "
                f"but no 'reduce_key' specified. Merge behavior may be undefined."
            ),
            "suggestion": "Add 'reduce_key: <field_name>' to specify merge key"
        })

    # Validate dependency ordering (DAG)
    action_index = workflow_actions.index(action_name)
    for dep_name in input_sources + context_sources:
        if dep_name not in workflow_actions:
            raise ConfigurationError(
                f"Action '{action_name}' depends on '{dep_name}' "
                f"which is not in the workflow",
                context={
                    "action": action_name,
                    "missing_dependency": dep_name
                }
            )

        dep_index = workflow_actions.index(dep_name)
        if dep_index >= action_index:
            raise ConfigurationError(
                f"Action '{action_name}' depends on '{dep_name}' "
                f"but '{dep_name}' appears after '{action_name}' in workflow order",
                context={
                    "action": action_name,
                    "dependency": dep_name,
                    "action_position": action_index,
                    "dependency_position": dep_index
                }
            )
```

**Tests:**
- `test_validate_multiple_inputs_with_reduce_key`
- `test_validate_multiple_inputs_without_reduce_key_warns`
- `test_validate_dependency_ordering`
- `test_validate_missing_dependency_error`

---

#### Task 1.3: Update Input Directory Resolution
**File:** `agent_actions/orchestration/agent_runner.py`

**Modified Method:**
```python
def _resolve_dependency_directories(
    self,
    agent_folder: Path,
    dependencies: Union[str, List[str], None],
    agent_name: str
) -> List[Path]:
    """
    Resolve input directories from dependencies.

    NEW BEHAVIOR:
    - dependencies = input sources (can be single or multiple)
    - Returns ALL input source directories

    Args:
        agent_folder: Path to agent folder
        dependencies: Input source(s) - string or list
        agent_name: Agent name (for logging/errors)

    Returns:
        List of input directory paths (one per input source)

    Raises:
        DependencyError: If any input directory not found
    """
    target_dir = agent_folder / "target"

    # Normalize to list
    if dependencies is None:
        return []
    elif isinstance(dependencies, str):
        dep_list = [dependencies]
    else:
        dep_list = list(dependencies)

    # Resolve all input source directories
    resolved_dirs = []
    missing_dirs = []

    for dep_name in dep_list:
        dep_path = target_dir / dep_name
        if dep_path.exists():
            resolved_dirs.append(dep_path)
        else:
            missing_dirs.append((dep_name, str(dep_path)))

    # Error if any missing
    if missing_dirs:
        missing_info = [f"{name} ({path})" for name, path in missing_dirs]
        raise DependencyError(
            f"Action '{agent_name}': Input source directories not found: {missing_info}",
            context={
                "action": agent_name,
                "dependencies": dep_list,
                "missing": missing_dirs,
                "expected_parent": str(target_dir)
            }
        )

    # Log resolution
    if len(resolved_dirs) == 1:
        logger.info(
            f"Action '{agent_name}': Using '{dep_list[0]}' as input source"
        )
    else:
        logger.info(
            f"Action '{agent_name}': Merging {len(resolved_dirs)} input sources: {dep_list}"
        )

    return resolved_dirs
```

**Tests:**
- `test_resolve_single_dependency`
- `test_resolve_multiple_dependencies`
- `test_resolve_missing_dependency_error`
- `test_resolve_none_dependencies`

---

### Phase 2: Context Dependency Handling (Week 1-2)

#### Task 2.1: Update Historical Loader Integration
**File:** `agent_actions/preprocessing/context/context_scope_processor.py`

**Modified Method:**
```python
def build_field_context_with_history(
    contents: Dict,
    agent_name: str,
    agent_config: Optional[Dict],
    current_item: Optional[Dict],
    file_path: Optional[str],
    agent_indices: Optional[Dict[str, int]],
    workflow_actions: List[str],
    agent_folder: str,
    historical_node_loader: Optional[Any] = None,
) -> Dict:
    """
    Build field context with explicit namespace structure.

    NEW BEHAVIOR:
    - Auto-infers context dependencies from context_scope
    - Only loads context deps via historical loader (not input deps)
    """
    if not agent_config:
        return contents

    dependencies = agent_config.get("dependencies")
    context_scope = agent_config.get("context_scope", {})

    # Infer input vs context sources
    input_sources, context_sources = ContextScopeProcessor.infer_context_dependencies(
        dependencies,
        context_scope,
        workflow_actions
    )

    # Build field context
    field_context = {}

    # Handle input sources (already in contents)
    for dep_name in input_sources:
        if dep_name in contents:
            field_context[dep_name] = contents[dep_name]

    # Handle context sources (load via historical loader)
    if context_sources and current_item and file_path and historical_node_loader:
        source_guid = current_item.get("source_guid")
        lineage = current_item.get("lineage", [])

        # Extract allowed fields per context dependency
        allowed_fields_map = ContextScopeProcessor._extract_allowed_fields_per_dependency(
            context_sources,
            context_scope,
            agent_name
        )

        # Load each context dependency
        for dep_name in context_sources:
            allowed_fields = allowed_fields_map.get(dep_name)

            try:
                historical_data = historical_node_loader.load(
                    action_name=dep_name,
                    source_guid=source_guid,
                    lineage=lineage,
                    agent_indices=agent_indices,
                    agent_folder=agent_folder,
                    allowed_fields=allowed_fields
                )

                if historical_data:
                    field_context[dep_name] = historical_data
                else:
                    logger.warning(
                        f"Action '{agent_name}': No historical data found for "
                        f"context dependency '{dep_name}' (lineage: {lineage})"
                    )
            except Exception as e:
                logger.error(
                    f"Action '{agent_name}': Failed to load context dependency "
                    f"'{dep_name}': {e}"
                )
                raise

    # Add metadata
    if current_item:
        field_context["source"] = current_item.get("source", {})
        field_context["seed"] = current_item.get("seed", {})

    return field_context
```

**Tests:**
- `test_build_context_with_inferred_deps`
- `test_build_context_single_input_multiple_context`
- `test_build_context_multiple_inputs_no_context`
- `test_build_context_missing_historical_data_warns`

---

#### Task 2.2: Update Field Extraction Logic
**File:** `agent_actions/preprocessing/context/context_scope_processor.py`

**Modified Method:**
```python
@staticmethod
def _extract_allowed_fields_per_dependency(
    dependencies: List[str],
    context_scope: Optional[Dict],
    action_name: str
) -> Dict[str, Optional[List[str]]]:
    """
    Extract which fields are allowed for each dependency from context_scope.

    NEW BEHAVIOR:
    - Works with auto-inferred dependencies
    - No longer requires dependencies to be explicitly in a separate list

    Args:
        dependencies: List of dependency names (input OR context)
        context_scope: Context scope configuration
        action_name: Action name (for error context)

    Returns:
        Dict mapping dependency name to:
        - None: Wildcard (all fields allowed)
        - List[str]: Specific field names allowed

    Raises:
        ConfigurationError: If dependency not declared in context_scope
    """
    if not context_scope:
        raise ConfigurationError(
            f"Action '{action_name}' references dependencies {dependencies} "
            f"but has no context_scope defined",
            context={"action": action_name, "dependencies": dependencies}
        )

    allowed_per_dep: Dict[str, Optional[List[str]]] = {}

    # Collect field references from observe and passthrough
    all_field_refs = []
    all_field_refs.extend(context_scope.get("observe", []))
    all_field_refs.extend(context_scope.get("passthrough", []))

    # Extract which dependencies are declared
    declared_deps = set()
    for field_ref in all_field_refs:
        try:
            dep_name, _ = ContextScopeProcessor.parse_field_reference(field_ref)
            declared_deps.add(dep_name)
        except ValueError:
            continue

    # Validate ALL dependencies are declared
    for dep_name in dependencies:
        if dep_name not in declared_deps:
            raise ConfigurationError(
                f"Dependency '{dep_name}' used but not declared in context_scope. "
                f"Add field declarations (e.g., '{dep_name}.*' or '{dep_name}.field_name').",
                context={
                    "action": action_name,
                    "missing_dependency": dep_name,
                    "all_dependencies": dependencies,
                    "declared_dependencies": list(declared_deps)
                }
            )

        # Extract allowed fields for this dependency
        wildcard_found = False
        specific_fields = []

        for field_ref in all_field_refs:
            try:
                ref_action, ref_field = ContextScopeProcessor.parse_field_reference(field_ref)
                if ref_action != dep_name:
                    continue

                if ref_field == "*":
                    wildcard_found = True
                    break
                else:
                    specific_fields.append(ref_field)
            except ValueError:
                continue

        if wildcard_found:
            allowed_per_dep[dep_name] = None  # All fields
        else:
            allowed_per_dep[dep_name] = list(set(specific_fields))  # Deduplicate

    return allowed_per_dep
```

---

### Phase 3: Deprecation & Migration (Week 2)

#### Task 3.1: Add Deprecation Support
**File:** `agent_actions/validation/static_analyzer/workflow_static_analyzer.py`

**New Method:**
```python
def check_deprecated_fields(
    self,
    action_config: Dict,
    action_name: str
) -> None:
    """
    Check for deprecated field usage and add warnings.

    Deprecated fields:
    - primary_dependency (replaced by simplified dependencies model)
    """
    if "primary_dependency" in action_config:
        primary_dep = action_config["primary_dependency"]
        dependencies = action_config.get("dependencies", [])

        self.warnings.append({
            "action": action_name,
            "type": "deprecated_field",
            "field": "primary_dependency",
            "message": (
                f"Action '{action_name}': 'primary_dependency' is deprecated. "
                f"\n\nOLD STYLE:"
                f"\n  dependencies: {dependencies}"
                f"\n  primary_dependency: {primary_dep}"
                f"\n\nNEW STYLE:"
                f"\n  dependencies: {primary_dep}  # Single input source"
                f"\n  context_scope:"
                f"\n    observe:"
                f"\n      - {primary_dep}.*"
            ),
            "suggestion": f"Use 'dependencies: {primary_dep}' instead"
        })
```

**Tests:**
- `test_deprecated_primary_dependency_warning`
- `test_no_warning_without_deprecated_fields`

---

#### Task 3.2: Create Migration Tool
**File:** `agent_actions/tools/migrate_dependencies.py`

**New Script:**
```python
#!/usr/bin/env python3
"""
Migration tool to convert old dependency model to new simplified model.

OLD MODEL:
  dependencies: [dep_A, dep_B, dep_C]
  primary_dependency: dep_B

NEW MODEL:
  dependencies: dep_B
  context_scope:
    observe:
      - dep_B.*
      - dep_A.*  # Auto-inferred as context
      - dep_C.*  # Auto-inferred as context
"""

import argparse
import yaml
from pathlib import Path
from typing import Dict, Any


def migrate_action_config(action_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Migrate a single action configuration to new model.

    Returns:
        Updated action config
    """
    if "primary_dependency" not in action_config:
        # Already using new model or no dependencies
        return action_config

    primary_dep = action_config.pop("primary_dependency")
    old_dependencies = action_config.get("dependencies", [])

    # Update dependencies to only include primary
    action_config["dependencies"] = primary_dep

    # context_scope already declares all data access
    # No changes needed - context deps will be auto-inferred

    print(f"  ✓ Migrated: primary_dependency '{primary_dep}' → dependencies '{primary_dep}'")
    print(f"    Context deps (auto-inferred): {[d for d in old_dependencies if d != primary_dep]}")

    return action_config


def migrate_workflow_file(file_path: Path, dry_run: bool = False) -> None:
    """
    Migrate a workflow YAML file to new dependency model.

    Args:
        file_path: Path to workflow YAML
        dry_run: If True, only show changes without writing
    """
    print(f"\nMigrating: {file_path}")

    with open(file_path, 'r') as f:
        workflow = yaml.safe_load(f)

    if "actions" not in workflow:
        print("  ⚠ No actions found, skipping")
        return

    actions_migrated = 0
    for action in workflow["actions"]:
        action_name = action.get("name", "<unnamed>")
        if "primary_dependency" in action:
            print(f"\nAction: {action_name}")
            migrate_action_config(action)
            actions_migrated += 1

    if actions_migrated == 0:
        print("  ✓ No migrations needed")
        return

    if dry_run:
        print(f"\n[DRY RUN] Would update {actions_migrated} actions")
        return

    # Write back
    with open(file_path, 'w') as f:
        yaml.dump(workflow, f, default_flow_style=False, sort_keys=False)

    print(f"\n✓ Updated {actions_migrated} actions in {file_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Migrate workflow configs to simplified dependency model"
    )
    parser.add_argument(
        "files",
        nargs="+",
        type=Path,
        help="Workflow YAML files to migrate"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show changes without writing files"
    )

    args = parser.parse_args()

    for file_path in args.files:
        if not file_path.exists():
            print(f"⚠ File not found: {file_path}")
            continue

        migrate_workflow_file(file_path, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
```

**Tests:**
- `test_migrate_single_action`
- `test_migrate_workflow_file`
- `test_dry_run_no_changes`
- `test_skip_already_migrated`

---

### Phase 4: Documentation (Week 2)

#### Task 4.1: Update PRIMARY_DEPENDENCY_GUIDE.md
**File:** `docs/PRIMARY_DEPENDENCY_GUIDE.md`

Replace entire content with new simplified model guide:

```markdown
# Dependency Model Guide

## Overview

The dependency model uses two simple concepts:

1. **`dependencies`** - Actions that provide primary input data
2. **`context_scope`** - All data access (input + context)

Context dependencies are **auto-inferred** from `context_scope`.

## Two Patterns

### Pattern 1: Single Input + Context

When you have ONE primary input source and additional context data:

```yaml
- name: generate_answer
  dependencies: extract_questions  # Primary input
  context_scope:
    observe:
      - extract_questions.*          # Input data
      - classify_type.question_type  # Context (auto-inferred)
      - suggest_counts.guidance      # Context (auto-inferred)
```

**How it works:**
- Input files from: `target/extract_questions/`
- Executions: One per record in `extract_questions`
- `classify_type` and `suggest_counts` loaded as context (via lineage matching)

### Pattern 2: Multiple Inputs (Merge by Key)

When you need to merge multiple inputs:

```yaml
- name: aggregate_votes
  dependencies: [validate_1, validate_2, validate_3]
  reduce_key: parent_id  # Merge by this field
  context_scope:
    observe:
      - validate_1.*
      - validate_2.*
      - validate_3.*
```

**How it works:**
- Input files from: `target/validate_1/`, `target/validate_2/`, `target/validate_3/`
- All records merged by `parent_id` field
- Executions: One per unique `parent_id`

## Auto-Inferred Context Dependencies

The system automatically detects context dependencies:

```yaml
dependencies: action_A              # Input source

context_scope:
  observe:
    - action_A.*                    # In dependencies → INPUT
    - action_B.field1               # NOT in dependencies → CONTEXT
    - action_C.field2               # NOT in dependencies → CONTEXT
```

**Result:**
- Input sources: `[action_A]`
- Context sources: `[action_B, action_C]` (auto-inferred)

## Rules

1. **Single source of truth:** `context_scope` declares all data access
2. **No redundancy:** Don't repeat action names in multiple places
3. **Explicit merge key:** Use `reduce_key` when merging multiple inputs
4. **DAG ordering:** Dependencies must appear before dependent action

## Migration from Old Model

**OLD STYLE:**
```yaml
dependencies: [dep_A, dep_B, dep_C]
primary_dependency: dep_B
context_scope:
  observe:
    - dep_A.*
    - dep_B.*
    - dep_C.*
```

**NEW STYLE:**
```yaml
dependencies: dep_B  # Only the input source
context_scope:
  observe:
    - dep_B.*          # Input
    - dep_A.*          # Context (auto-inferred)
    - dep_C.*          # Context (auto-inferred)
```

Use migration tool:
```bash
python -m agent_actions.tools.migrate_dependencies workflow.yml
```

## Examples

See [Examples](#examples) section below for comprehensive examples.
```

---

#### Task 4.2: Update RFC Documentation
**File:** `docs/specs/RFC_multiple_dependencies_primary_input.md`

Add deprecation notice at top:

```markdown
# RFC: Multiple Dependencies and Primary Input Selection

**Status:** SUPERSEDED
**Superseded by:** RFC_simplified_dependency_model.md
**Created:** 2026-01-15
**Deprecated:** 2026-01-16

> **NOTE:** This RFC describes the `primary_dependency` approach which has been
> superseded by a simplified model that auto-infers context dependencies.
> See [RFC_simplified_dependency_model.md](RFC_simplified_dependency_model.md)
> for the current design.

---

[Original content...]
```

---

#### Task 4.3: Update User Documentation
**Files:**
- `docs/user_guide/dependencies.md`
- `docs/user_guide/context_scope.md`
- `docs/reference/action_schema.md`

Update all references to show new simplified model.

---

### Phase 5: Testing (Week 3)

#### Task 5.1: Unit Tests

**File:** `tests/preprocessing/context/test_infer_context_dependencies.py`

```python
import pytest
from agent_actions.preprocessing.context.context_scope_processor import ContextScopeProcessor
from agent_actions.exceptions import ConfigurationError


class TestInferContextDependencies:
    """Test auto-inference of context dependencies."""

    def test_single_input_with_context_deps(self):
        """Test single input source with context dependencies."""
        dependencies = "action_A"
        context_scope = {
            "observe": [
                "action_A.*",
                "action_B.field1",
                "action_C.field2"
            ]
        }
        workflow_actions = ["action_A", "action_B", "action_C"]

        input_sources, context_sources = ContextScopeProcessor.infer_context_dependencies(
            dependencies, context_scope, workflow_actions
        )

        assert input_sources == ["action_A"]
        assert set(context_sources) == {"action_B", "action_C"}

    def test_multiple_inputs_no_context(self):
        """Test multiple input sources with no context dependencies."""
        dependencies = ["action_A", "action_B", "action_C"]
        context_scope = {
            "observe": [
                "action_A.*",
                "action_B.*",
                "action_C.*"
            ]
        }
        workflow_actions = ["action_A", "action_B", "action_C"]

        input_sources, context_sources = ContextScopeProcessor.infer_context_dependencies(
            dependencies, context_scope, workflow_actions
        )

        assert set(input_sources) == {"action_A", "action_B", "action_C"}
        assert context_sources == []

    def test_no_dependencies_only_context(self):
        """Test no input dependencies, only context references."""
        dependencies = None
        context_scope = {
            "observe": ["action_A.*", "action_B.*"]
        }
        workflow_actions = ["action_A", "action_B"]

        input_sources, context_sources = ContextScopeProcessor.infer_context_dependencies(
            dependencies, context_scope, workflow_actions
        )

        assert input_sources == []
        assert set(context_sources) == {"action_A", "action_B"}

    def test_invalid_action_reference_error(self):
        """Test error when context_scope references non-existent action."""
        dependencies = "action_A"
        context_scope = {
            "observe": [
                "action_A.*",
                "action_B.*",
                "nonexistent_action.field"  # Does not exist
            ]
        }
        workflow_actions = ["action_A", "action_B"]

        with pytest.raises(ConfigurationError) as exc:
            ContextScopeProcessor.infer_context_dependencies(
                dependencies, context_scope, workflow_actions
            )

        assert "nonexistent_action" in str(exc.value)
        assert "not found in workflow" in str(exc.value)

    def test_empty_context_scope(self):
        """Test with no context_scope."""
        dependencies = "action_A"
        context_scope = None
        workflow_actions = ["action_A"]

        input_sources, context_sources = ContextScopeProcessor.infer_context_dependencies(
            dependencies, context_scope, workflow_actions
        )

        assert input_sources == ["action_A"]
        assert context_sources == []
```

---

#### Task 5.2: Integration Tests

**File:** `tests/integration/test_simplified_dependency_model.py`

```python
import pytest
from pathlib import Path
from agent_actions.orchestration.workflow_orchestrator import WorkflowOrchestrator


class TestSimplifiedDependencyModel:
    """Integration tests for simplified dependency model."""

    def test_single_input_with_context_execution(self, tmp_path):
        """Test execution with single input and context dependencies."""
        # Setup workflow with 3 actions
        setup_test_workflow(tmp_path, [
            {
                "name": "extract_data",
                "schema": {"data": "string"}
            },
            {
                "name": "enrich_data",
                "schema": {"enriched": "string"}
            },
            {
                "name": "process_data",
                "dependencies": "extract_data",  # Single input
                "context_scope": {
                    "observe": [
                        "extract_data.*",
                        "enrich_data.enriched"  # Context dep
                    ]
                },
                "schema": {"result": "string"}
            }
        ])

        # Create test data
        create_test_records(tmp_path / "target/extract_data", count=5)
        create_test_records(tmp_path / "target/enrich_data", count=5)

        # Execute
        orchestrator = WorkflowOrchestrator(tmp_path / "workflow.yml")
        orchestrator.run_action("process_data")

        # Verify
        output_dir = tmp_path / "target/process_data"
        assert output_dir.exists()
        output_files = list(output_dir.glob("*.json"))
        assert len(output_files) == 5  # Only 5, not 10

    def test_multiple_inputs_merge_execution(self, tmp_path):
        """Test execution with multiple inputs merged by key."""
        # Setup workflow
        setup_test_workflow(tmp_path, [
            {
                "name": "vote_1",
                "schema": {"vote": "string", "parent_id": "string"}
            },
            {
                "name": "vote_2",
                "schema": {"vote": "string", "parent_id": "string"}
            },
            {
                "name": "vote_3",
                "schema": {"vote": "string", "parent_id": "string"}
            },
            {
                "name": "aggregate_votes",
                "dependencies": ["vote_1", "vote_2", "vote_3"],
                "reduce_key": "parent_id",
                "context_scope": {
                    "observe": [
                        "vote_1.*",
                        "vote_2.*",
                        "vote_3.*"
                    ]
                },
                "schema": {"aggregated": "object"}
            }
        ])

        # Create test data with 3 unique parent_ids
        create_test_records_with_key(
            tmp_path / "target/vote_1",
            parent_ids=["p1", "p2", "p3"]
        )
        create_test_records_with_key(
            tmp_path / "target/vote_2",
            parent_ids=["p1", "p2", "p3"]
        )
        create_test_records_with_key(
            tmp_path / "target/vote_3",
            parent_ids=["p1", "p2", "p3"]
        )

        # Execute
        orchestrator = WorkflowOrchestrator(tmp_path / "workflow.yml")
        orchestrator.run_action("aggregate_votes")

        # Verify
        output_dir = tmp_path / "target/aggregate_votes"
        output_files = list(output_dir.glob("*.json"))
        assert len(output_files) == 3  # One per unique parent_id
```

---

#### Task 5.3: Backward Compatibility Tests

**File:** `tests/integration/test_backward_compatibility.py`

```python
import pytest
from pathlib import Path


class TestBackwardCompatibility:
    """Test that existing workflows still work."""

    def test_old_primary_dependency_style_warns(self, tmp_path):
        """Test old primary_dependency style produces deprecation warning."""
        workflow_content = """
actions:
  - name: action_A
    dependencies: [dep_1, dep_2]
    primary_dependency: dep_1
    context_scope:
      observe:
        - dep_1.*
        - dep_2.*
"""
        workflow_file = tmp_path / "workflow.yml"
        workflow_file.write_text(workflow_content)

        from agent_actions.validation.static_analyzer import WorkflowStaticAnalyzer

        analyzer = WorkflowStaticAnalyzer(str(workflow_file))
        warnings = analyzer.validate()

        # Should have deprecation warning
        assert any("primary_dependency" in w.get("message", "") for w in warnings)
        assert any("deprecated" in w.get("message", "").lower() for w in warnings)

    def test_single_dependency_unchanged(self, tmp_path):
        """Test single dependency behavior unchanged."""
        workflow_content = """
actions:
  - name: action_A
    dependencies: dep_1
    context_scope:
      observe:
        - dep_1.*
"""
        # Should work without any changes or warnings
        workflow_file = tmp_path / "workflow.yml"
        workflow_file.write_text(workflow_content)

        from agent_actions.validation.static_analyzer import WorkflowStaticAnalyzer

        analyzer = WorkflowStaticAnalyzer(str(workflow_file))
        warnings = analyzer.validate()

        # No warnings for new style
        assert len(warnings) == 0
```

---

### Phase 6: Rollout (Week 3-4)

#### Task 6.1: Update Examples Repository

Update all example workflows in:
- `examples/quiz_generation/`
- `examples/data_enrichment/`
- `examples/aggregation/`

#### Task 6.2: Update qanalabs Sample Project

**File:** Update qanalabs-actions workflow configs

Run migration tool:
```bash
python -m agent_actions.tools.migrate_dependencies \
  qanalabs-actions/qanalabs/agent_workflow/*/agent_config/*.yml
```

#### Task 6.3: Create Release Notes

**File:** `CHANGELOG.md`

```markdown
## [v2.0.0] - 2026-01-XX

### 🎉 Major Changes

#### Simplified Dependency Model

We've simplified the dependency model to eliminate redundancy and improve clarity.

**OLD STYLE:**
```yaml
dependencies: [dep_A, dep_B, dep_C]
primary_dependency: dep_B
context_scope:
  observe:
    - dep_A.*
    - dep_B.*
    - dep_C.*
```

**NEW STYLE:**
```yaml
dependencies: dep_B  # Input source only
context_scope:
  observe:
    - dep_B.*          # Input
    - dep_A.*          # Context (auto-inferred)
    - dep_C.*          # Context (auto-inferred)
```

**Key Benefits:**
- ✅ No redundant declarations
- ✅ Auto-infers context dependencies
- ✅ Clearer semantics: `dependencies` = input sources
- ✅ Works for both single input and merge patterns

**Migration:**
```bash
python -m agent_actions.tools.migrate_dependencies workflow.yml
```

See [Migration Guide](docs/migration/v1_to_v2.md) for details.

### ⚠️ Breaking Changes

- `primary_dependency` field is **deprecated** (still works with warning)
- Recommended to migrate to new simplified model

### 🐛 Bug Fixes

- Fixed incorrect execution count when multiple dependencies without primary

### 📚 Documentation

- Updated PRIMARY_DEPENDENCY_GUIDE.md
- Added RFC_simplified_dependency_model.md
- Updated all examples and tutorials
```

---

## Examples

### Example 1: Quiz Generation (Before & After)

**BEFORE:**
```yaml
- name: generate_distractor_1
  dependencies: [add_answer_text, write_scenario_question, suggest_distractor_counts]
  primary_dependency: add_answer_text
  context_scope:
    observe:
      - add_answer_text.*
      - write_scenario_question.*
      - suggest_distractor_counts.*
```

**AFTER:**
```yaml
- name: generate_distractor_1
  dependencies: add_answer_text  # Input source
  context_scope:
    observe:
      - add_answer_text.*
      - write_scenario_question.*        # Auto-inferred context
      - suggest_distractor_counts.*      # Auto-inferred context
```

### Example 2: Vote Aggregation (No Change Needed)

```yaml
- name: aggregate_validation_votes
  dependencies: [validate_answer_1, validate_answer_2, validate_answer_3]
  reduce_key: parent_target_id
  context_scope:
    observe:
      - validate_answer_1.*
      - validate_answer_2.*
      - validate_answer_3.*
```

This already uses the correct pattern! All 3 are input sources merged by key.

### Example 3: Data Enrichment

**BEFORE:**
```yaml
- name: enrich_profile
  dependencies: [fetch_user, fetch_preferences, fetch_activity]
  primary_dependency: fetch_user
  context_scope:
    observe:
      - fetch_user.*
      - fetch_preferences.*
      - fetch_activity.*
```

**AFTER:**
```yaml
- name: enrich_profile
  dependencies: fetch_user  # Primary input
  context_scope:
    observe:
      - fetch_user.*
      - fetch_preferences.*    # Context
      - fetch_activity.*       # Context
```

---

## Testing Strategy

### Test Coverage

- [ ] Unit tests for `infer_context_dependencies()`
- [ ] Unit tests for dependency validation
- [ ] Unit tests for directory resolution
- [ ] Integration tests for single input + context pattern
- [ ] Integration tests for multiple inputs merge pattern
- [ ] Backward compatibility tests for old `primary_dependency`
- [ ] Migration tool tests
- [ ] End-to-end tests with real workflows

### Test Scenarios

1. **Single input + multiple context deps** → 5 records execute 5 times
2. **Multiple inputs merge by key** → 3 actions × 5 records = 5 unique keys
3. **No dependencies** → Unchanged behavior
4. **Single dependency** → Unchanged behavior
5. **Invalid action reference** → ConfigurationError
6. **Missing context_scope** → ConfigurationError
7. **Old primary_dependency style** → Deprecation warning

---

## Migration Strategy

### Phase 1: Soft Deprecation (v1.9.0)
- Support both old and new styles
- Warn when using `primary_dependency`
- Update docs to show new style
- Duration: 1 release cycle (2-4 weeks)

### Phase 2: Hard Deprecation (v2.0.0)
- Change warnings to errors for `primary_dependency`
- Require migration to new style
- Provide migration tool
- Duration: 1 release cycle

### Phase 3: Removal (v2.1.0)
- Remove `primary_dependency` support entirely
- Clean up legacy code paths

### Migration Checklist

- [ ] Add auto-inference logic
- [ ] Add deprecation warnings
- [ ] Create migration tool
- [ ] Update all documentation
- [ ] Update all examples
- [ ] Migrate qanalabs sample project
- [ ] Create migration guide
- [ ] Announce deprecation timeline
- [ ] Run migration tool on internal projects
- [ ] Release v2.0.0
- [ ] Monitor for issues
- [ ] Remove deprecated code in v2.1.0

---

## Success Metrics

- **Code simplicity:** Reduce LOC in config files by ~20%
- **Developer clarity:** Reduce time to understand dependency model
- **Error rate:** Reduce configuration errors related to dependencies
- **Migration success:** 100% of examples migrated without issues
- **Documentation clarity:** User feedback on improved clarity

---

## Risks & Mitigations

### Risk 1: Breaking existing workflows
**Mitigation:**
- Phased rollout with deprecation period
- Migration tool automates conversion
- Comprehensive backward compatibility testing

### Risk 2: Confusion during transition
**Mitigation:**
- Clear deprecation warnings with examples
- Migration guide with before/after examples
- Support both styles during deprecation period

### Risk 3: Hidden bugs in auto-inference
**Mitigation:**
- Extensive unit and integration testing
- Validate against existing workflows
- Monitor error rates post-release

---

## Implementation Checklist

### Week 1: Core Infrastructure
- [ ] Task 1.1: Update dependency parser with `infer_context_dependencies()`
- [ ] Task 1.2: Update validation logic
- [ ] Task 1.3: Update input directory resolution
- [ ] Unit tests for all above

### Week 1-2: Context Handling
- [ ] Task 2.1: Update historical loader integration
- [ ] Task 2.2: Update field extraction logic
- [ ] Integration tests

### Week 2: Deprecation & Migration
- [ ] Task 3.1: Add deprecation support
- [ ] Task 3.2: Create migration tool
- [ ] Backward compatibility tests

### Week 2: Documentation
- [ ] Task 4.1: Update PRIMARY_DEPENDENCY_GUIDE.md
- [ ] Task 4.2: Update RFC documentation
- [ ] Task 4.3: Update user documentation

### Week 3: Testing
- [ ] Task 5.1: Unit tests
- [ ] Task 5.2: Integration tests
- [ ] Task 5.3: Backward compatibility tests

### Week 3-4: Rollout
- [ ] Task 6.1: Update examples repository
- [ ] Task 6.2: Update qanalabs sample project
- [ ] Task 6.3: Create release notes
- [ ] Final QA pass
- [ ] Release v2.0.0

---

## Approval

- [ ] Architecture review complete
- [ ] Implementation plan approved
- [ ] Migration strategy approved
- [ ] Documentation plan approved
- [ ] Testing strategy approved
- [ ] Ready to implement

---

**End of RFC**
