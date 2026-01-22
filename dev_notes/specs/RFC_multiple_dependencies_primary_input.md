# RFC: Multiple Dependencies and Primary Input Selection

**Status:** Draft
**Created:** 2026-01-15
**Author:** System Architecture
**Related:** RFC_ancestry_chain.md, anatomy_action.md, PROGRESSIVE_DATA_EXPOSURE.md

---

## Table of Contents

1. [Overview](#overview)
2. [Motivation](#motivation)
3. [Current Problem](#current-problem)
4. [Proposed Solution](#proposed-solution)
5. [Configuration Schema](#configuration-schema)
6. [Behavior Specification](#behavior-specification)
7. [Implementation Details](#implementation-details)
8. [Migration Guide](#migration-guide)
9. [Examples](#examples)
10. [Error Handling](#error-handling)
11. [Testing Strategy](#testing-strategy)
12. [Backward Compatibility](#backward-compatibility)

---

## Overview

This RFC proposes a new mechanism for handling actions with multiple dependencies, introducing the concept of a **primary dependency** that determines the input dataset size and execution count.

### Key Changes

1. **Primary Dependency Selection**: Explicit `primary_dependency` field in action configuration
2. **Input Dataset Resolution**: Only the primary dependency's output files determine execution count
3. **Historical Context Loading**: Non-primary dependencies loaded via historical loader with lineage matching
4. **Explicit Field Declarations**: All dependencies MUST have fields declared in `context_scope` (error, not warning)

---

## Motivation

### Problem Statement

When an action has multiple dependencies, the current system exhibits unexpected behavior:

**Scenario:**
```yaml
dependencies: [dep_A, dep_B, dep_C]  # Each has 5 records
```

**Current Behavior (WRONG):**
- System merges all 3 dependency outputs: 5 + 5 + 5 = **15 records**
- Action executes **15 times** instead of expected **5 times**
- Data from different branches gets mixed incorrectly

**Expected Behavior:**
- ONE dependency determines input size (5 records)
- Action executes **5 times**
- Each execution has access to ALL dependencies from the SAME branch (matched by lineage)

### Goals

1. **Predictable**: Clear, documented rule for input dataset selection
2. **Efficient**: Only load data that's needed (progressive data exposure)
3. **Explicit**: No magic behavior, self-documenting configuration
4. **Correct**: Match dependencies by lineage to ensure same-branch grouping
5. **Public-Tool Ready**: Easy to explain, clear error messages, no surprises

---

## Current Problem

### Problem 1: Incorrect Merging Logic

**Code Location:** `agent_actions/orchestration/agent_runner.py:637-647`

```python
def process_directories(self, params: FileProcessParams) -> None:
    # Use merging approach when there are multiple upstream directories
    if len(params.upstream_data_dirs) > 1:
        files_processed_count = self._process_merged_files(params)
        # ...
```

**Issue:**
- `_resolve_dependency_directories()` returns ALL dependency directories
- System treats this as "parallel branches" and merges their outputs
- But these are DIFFERENT actions, not parallel branches of the SAME action
- Result: Incorrect data multiplication

### Problem 2: Implicit Field Loading

**Code Location:** `agent_actions/preprocessing/context/context_scope_processor.py:363-369`

```python
else:
    # Dependency declared but no fields referenced in context_scope
    # Load all fields (backward compatibility)
    logger.warning(
        f"Dependency '{dep_name}' declared but not referenced in context_scope. "
        f"Loading all fields by default."
    )
    allowed_per_dep[dep_name] = None
```

**Issue:**
- Warning (not error) allows silent fallback to "load all fields"
- Users don't realize they're loading unnecessary data
- Configuration doesn't document what data is actually used

### Problem 3: No Control Over Input Selection

**Issue:**
- Users cannot specify which dependency determines execution count
- System behavior is implicit and hard to predict
- No way to override default behavior when needed

---

## Proposed Solution

### Core Principles

#### 1. Primary Dependency Concept

**Definition:** The dependency whose output files determine the input dataset size and execution count.

**Selection Strategy:**
- **Explicit**: User specifies `primary_dependency: <name>` in config
- **Convention**: If not specified, last dependency in list is primary
- **Validation**: Primary must exist in dependencies list

#### 2. Historical Loader for Non-Primary Dependencies

**For non-primary dependencies:**
- NOT loaded as input files
- Loaded during execution via `historical_node_loader.py`
- Matched by: `source_guid` + `lineage` (ensures same-branch grouping)
- Only loads fields declared in `context_scope` (progressive data exposure)

#### 3. Explicit Field Declarations Required

**All dependencies MUST be referenced in `context_scope`:**
- Error (not warning) if dependency not declared
- Forces explicit documentation of data flow
- Enables progressive data exposure

---

## Configuration Schema

### New Field: `primary_dependency`

```yaml
type: string
required: false
default: dependencies[-1]  # Last dependency in list
validation:
  - Must exist in dependencies list
  - Only valid if dependencies list is not empty
  - If not specified, defaults to last dependency
```

### Updated Action Schema

```yaml
actions:
  - name: string                    # Action name (required)
    dependencies: array<string>     # List of upstream actions (optional)
    primary_dependency: string      # NEW: Which dependency provides input (optional)
    context_scope:                  # Field declarations (required if dependencies exist)
      observe: array<string>        # Fields for LLM context only
      passthrough: array<string>    # Fields for LLM + output
      drop: array<string>           # Fields to exclude
    # ... other fields
```

### Validation Rules

1. **If `primary_dependency` is specified:**
   - MUST exist in `dependencies` list
   - Otherwise: `ConfigurationError`

2. **If `primary_dependency` is NOT specified:**
   - Defaults to `dependencies[-1]` (last in list)
   - Logs info message about convention

3. **If `dependencies` exists:**
   - ALL dependencies MUST be referenced in `context_scope`
   - Otherwise: `ConfigurationError`

4. **If `primary_dependency` exists but NO `dependencies`:**
   - `ConfigurationError` (invalid configuration)

---

## Behavior Specification

### Scenario 1: Single Dependency (No Change)

```yaml
dependencies: [action_A]
context_scope:
  observe:
    - action_A.field1
```

**Behavior:**
- Input from: `target/action_A/`
- Primary: `action_A` (only one)
- Historical loader: Not used
- Execution count: Number of records in action_A

### Scenario 2: Multiple Dependencies - Explicit Primary

```yaml
dependencies: [action_A, action_B, action_C]
primary_dependency: action_B  # EXPLICIT
context_scope:
  observe:
    - action_A.field1
    - action_B.*
    - action_C.field2
```

**Behavior:**
- Input from: `target/action_B/` (only primary)
- Primary: `action_B` (explicit)
- Historical loader: Loads action_A and action_C using lineage matching
- Execution count: Number of records in action_B

**Log Message:**
```
INFO: Action 'my_action': Using explicit primary_dependency 'action_B' from 3 dependencies.
```

### Scenario 3: Multiple Dependencies - Convention

```yaml
dependencies: [action_A, action_B, action_C]
# No primary_dependency specified
context_scope:
  observe:
    - action_A.field1
    - action_B.field2
    - action_C.*  # Last in list
```

**Behavior:**
- Input from: `target/action_C/` (last in list)
- Primary: `action_C` (convention)
- Historical loader: Loads action_A and action_B
- Execution count: Number of records in action_C

**Log Message:**
```
INFO: Action 'my_action': Multiple dependencies [action_A, action_B, action_C].
Using 'action_C' (last in list) as primary input.
To change, set 'primary_dependency: <name>' in config.
```

### Scenario 4: Parallel Branches (No Change)

**When `flatten_raw_questions` splits into 5 branches:**

```yaml
dependencies: [flatten_raw_questions]
```

**Behind the scenes:**
- System detects: Multiple directories with SAME name
- Behavior: Merge branch outputs (existing logic)
- No change to current parallel branch handling

---

## Implementation Details

### Phase 1: Configuration Validation (Static Analyzer)

**File:** `agent_actions/validation/static_analyzer/workflow_static_analyzer.py`

**New Method:**
```python
def validate_primary_dependency(
    self,
    action_config: Dict,
    action_name: str
) -> None:
    """
    Validate primary_dependency configuration.

    Rules:
    1. If primary_dependency specified, must exist in dependencies
    2. If dependencies exist, all must be in context_scope
    3. If no dependencies, primary_dependency is invalid

    Raises:
        ConfigurationError: If validation fails
    """
    pass  # Implementation details below
```

**Validation Logic:**

1. **Check primary_dependency exists in dependencies:**
```python
dependencies = action_config.get("dependencies", [])
primary_dep = action_config.get("primary_dependency")

if primary_dep and primary_dep not in dependencies:
    raise ConfigurationError(
        f"Action '{action_name}': primary_dependency '{primary_dep}' "
        f"not found in dependencies list: {dependencies}",
        context={...}
    )
```

2. **Check all dependencies declared in context_scope:**
```python
context_scope = action_config.get("context_scope", {})
if dependencies and not context_scope:
    raise ConfigurationError(
        f"Action '{action_name}' has dependencies but no context_scope. "
        f"All dependencies must have explicit field declarations.",
        context={...}
    )

# Extract declared dependencies from context_scope
all_field_refs = []
all_field_refs.extend(context_scope.get("observe", []))
all_field_refs.extend(context_scope.get("passthrough", []))

declared_deps = set()
for field_ref in all_field_refs:
    dep_name, _ = parse_field_reference(field_ref)
    declared_deps.add(dep_name)

# Validate all dependencies are declared
for dep in dependencies:
    if dep not in declared_deps:
        raise ConfigurationError(
            f"Action '{action_name}': Dependency '{dep}' declared but not "
            f"referenced in context_scope. Add field declarations "
            f"(e.g., '{dep}.*' or '{dep}.field_name').",
            context={...}
        )
```

### Phase 2: Input Directory Resolution

**File:** `agent_actions/orchestration/agent_runner.py`

**Modified Method:**
```python
def _resolve_dependency_directories(
    self,
    agent_folder: Path,
    dependencies: List[str],
    agent_config: Dict,  # NEW parameter
    agent_name: str      # NEW parameter
) -> List[Path]:
    """
    Resolve upstream directories from dependencies.

    NEW BEHAVIOR:
    - Single dependency → Use it
    - Multiple dependencies → Use primary_dependency (or last if not specified)
    - Returns only PRIMARY dependency directory

    Args:
        agent_folder: Path to agent folder
        dependencies: List of dependency names
        agent_config: Full agent configuration (to get primary_dependency)
        agent_name: Agent name (for logging/errors)

    Returns:
        List containing only the primary dependency directory path

    Raises:
        ConfigurationError: If primary_dependency invalid
        DependencyError: If primary dependency directory not found
    """
    target_dir = agent_folder / "target"

    # Single dependency - straightforward
    if len(dependencies) == 1:
        dep_path = target_dir / dependencies[0]
        if dep_path.exists():
            return [dep_path]
        raise DependencyError(
            f"Dependency directory not found: {dep_path}",
            context={"action": agent_name, "dependency": dependencies[0]}
        )

    # Multiple dependencies - determine primary
    primary_dep = agent_config.get("primary_dependency")

    if primary_dep:
        # Explicit primary_dependency specified
        if primary_dep not in dependencies:
            raise ConfigurationError(
                f"Action '{agent_name}': primary_dependency '{primary_dep}' "
                f"not found in dependencies list: {dependencies}",
                context={...}
            )
        logger.info(
            f"Action '{agent_name}': Using explicit primary_dependency "
            f"'{primary_dep}' from {len(dependencies)} dependencies."
        )
    else:
        # Convention: last dependency is primary
        primary_dep = dependencies[-1]
        logger.info(
            f"Action '{agent_name}': Multiple dependencies {dependencies}. "
            f"Using '{primary_dep}' (last in list) as primary input. "
            f"To change, set 'primary_dependency: <name>' in config."
        )

    # Return primary dependency directory
    dep_path = target_dir / primary_dep
    if not dep_path.exists():
        raise DependencyError(
            f"Primary dependency directory not found: {dep_path}",
            context={
                "action": agent_name,
                "primary_dependency": primary_dep,
                "all_dependencies": dependencies,
                "expected_path": str(dep_path)
            }
        )

    return [dep_path]
```

**Update Caller:**
```python
def _resolve_paths(
    self,
    agent_folder: str,
    agent_config: Dict,
    agent_name: str,  # NEW parameter
    idx: int,
    previous_agent_type: Optional[str] = None,
) -> Tuple[List[str], str]:
    """Resolve input and output paths for agent execution."""
    agent_folder_path = Path(agent_folder)
    agent_type = agent_config["agent_type"]
    dependencies = agent_config.get("dependencies", [])

    # Determine upstream directories based on workflow position
    if idx == 0:
        upstream_data_dirs = self._resolve_start_node_directories(agent_folder_path)
    elif dependencies and hasattr(self, "agent_indices") and self.agent_indices:
        upstream_data_dirs = self._resolve_dependency_directories(
            agent_folder_path,
            dependencies,
            agent_config,  # NEW: Pass full config
            agent_name     # NEW: Pass agent name
        )
    elif previous_agent_type:
        upstream_data_dirs = [
            self._resolve_linear_directory(agent_folder_path, previous_agent_type, idx)
        ]
    else:
        upstream_data_dirs = [agent_folder_path / "staging"]

    output_directory = agent_folder_path / "target" / agent_type
    output_directory.mkdir(parents=True, exist_ok=True)
    return ([str(d) for d in upstream_data_dirs], str(output_directory))
```

### Phase 3: Context Scope Validation

**File:** `agent_actions/preprocessing/context/context_scope_processor.py`

**Modified Method:**
```python
@staticmethod
def _extract_allowed_fields_per_dependency(
    dependencies: List[str],
    context_scope: Optional[Dict],
    action_name: str  # NEW parameter for error messages
) -> Dict[str, Optional[List[str]]]:
    """
    Extract which fields are allowed for each dependency from context_scope.

    NEW BEHAVIOR:
    - All dependencies MUST be referenced in context_scope
    - No implicit "load all fields" fallback
    - Raises ConfigurationError if dependency not declared

    Args:
        dependencies: List of dependency names
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
            f"Action '{action_name}' has dependencies but no context_scope defined. "
            f"All dependencies must have explicit field declarations.",
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
                f"Dependency '{dep_name}' declared but not referenced in context_scope. "
                f"Add field declarations (e.g., '{dep_name}.*' or '{dep_name}.field_name'). "
                f"\n\nDeclared dependencies: {list(declared_deps)}"
                f"\n\nAll dependencies: {dependencies}",
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

**Update Caller:**
```python
def build_field_context_with_history(
    contents: Dict,
    agent_name: str,
    agent_config: Optional[Dict],
    # ... other params
) -> Dict:
    """Build field context with explicit namespace structure."""

    dependencies = agent_config.get("dependencies", []) if agent_config else []

    if dependencies and current_item and file_path and agent_indices:
        # BATCH MODE - Load from historical files with progressive data exposure

        # Extract allowed fields per dependency (now raises error if missing)
        allowed_fields_map = ContextScopeProcessor._extract_allowed_fields_per_dependency(
            dependencies,
            context_scope,
            agent_name  # NEW: Pass action name for error messages
        )

        # ... rest of implementation
```

### Phase 4: Keep Parallel Branch Merging

**File:** `agent_actions/orchestration/agent_runner.py`

**Modified Method:**
```python
def process_directories(self, params: FileProcessParams) -> None:
    """
    Process files from upstream directories.

    NEW BEHAVIOR:
    - Multiple deps → Already resolved to single primary (shouldn't reach len > 1)
    - Parallel branches (same action, split indices) → Merge them
    """
    # Check if we have parallel branches (same action name, multiple outputs)
    if len(params.upstream_data_dirs) > 1:
        upstream_paths = [Path(d) for d in params.upstream_data_dirs]
        dep_names = [p.name for p in upstream_paths]
        unique_names = set(dep_names)

        if len(unique_names) == 1:
            # Parallel branches from same action - merge them
            logger.info(
                f"Detected parallel branches from '{unique_names.pop()}'. "
                f"Merging {len(upstream_paths)} outputs."
            )
            files_processed = self._process_merged_files(params)
            if files_processed == 0:
                self._warn_no_files_found(params)
            return
        else:
            # Multiple different dependencies - shouldn't happen with new design
            logger.error(
                f"Multiple dependency directories detected: {dep_names}. "
                f"This should have been resolved to primary dependency. "
                f"Using first directory only as fallback."
            )
            params.upstream_data_dirs = [params.upstream_data_dirs[0]]

    # Single upstream - standard processing
    files_processed_count = 0
    output_path = Path(params.output_directory)
    processed_relative_paths: set = set()

    for input_directory in params.upstream_data_dirs:
        input_path = Path(input_directory)
        if not input_path.exists():
            logger.warning("Upstream directory not found: %s", input_directory)
            continue

        files_processed_count += self._process_directory_files(
            input_path, output_path, input_directory, params, processed_relative_paths
        )

    if files_processed_count == 0:
        self._warn_no_files_found(params)
```

---

## Migration Guide

### For Existing Workflows

#### Step 1: Identify Actions with Multiple Dependencies

Search for actions with multiple dependencies:
```bash
grep -A 5 "dependencies:.*\[.*,.*\]" agent_config/*.yml
```

#### Step 2: Add `primary_dependency` (Recommended)

For each action found, add explicit primary:
```yaml
# BEFORE
dependencies: [dep_A, dep_B, dep_C]

# AFTER
dependencies: [dep_A, dep_B, dep_C]
primary_dependency: dep_C  # Make it explicit
```

#### Step 3: Declare All Dependency Fields in `context_scope`

Ensure ALL dependencies are referenced:
```yaml
context_scope:
  observe:
    - dep_A.field1
    - dep_B.*
    - dep_C.field2  # All 3 dependencies declared
```

#### Step 4: Validate Configuration

Run static analyzer to catch errors:
```bash
agac validate -a <action_name>
```

### Breaking Changes

1. **Missing `context_scope` declarations now ERROR (was WARNING)**
   - **Before:** Warning logged, all fields loaded
   - **After:** ConfigurationError raised at load time
   - **Migration:** Add field declarations for all dependencies

2. **Multiple dependencies behavior changed**
   - **Before:** All dependency outputs merged into input
   - **After:** Only primary dependency used as input
   - **Migration:** Add `primary_dependency` if default (last) is not desired

3. **Invalid `primary_dependency` now caught at load time**
   - **Before:** No validation (runtime error)
   - **After:** ConfigurationError during workflow load
   - **Migration:** Fix typos/incorrect names in config

---

## Examples

### Example 1: Quiz Generation (User's Use Case)

**Configuration:**
```yaml
- name: generate_distractor_1
  dependencies:
    - add_answer_text
    - write_scenario_question
    - suggest_distractor_counts
  primary_dependency: suggest_distractor_counts  # Explicit
  intent: "Generate first distractor - focus on wrong technology/service"
  schema:
    distractor_1: string
    explanation_why_it_is_incorrect_1: string
    thinking_process_1: string
  context_scope:
    observe:
      - add_answer_text.target_word_counts
      - add_answer_text.answer_text
      - suggest_distractor_counts.*  # Primary dependency fields
    passthrough:
      - write_scenario_question.question
      - write_scenario_question.options
      - write_scenario_question.answer
      - write_scenario_question.answer_explanation
  prompt: $qanalabs_quiz_gen.Generate_Distractor_1
```

**State Before Execution:**
```
target/
├── add_answer_text/combined_scraped.json              [5 records]
├── write_scenario_question/combined_scraped.json      [5 records]
└── suggest_distractor_counts/combined_scraped.json    [5 records]
```

**Execution:**
1. **Input loading:** Reads from `target/suggest_distractor_counts/` (primary)
2. **Iteration:** 5 times (one per record in primary)
3. **For each iteration:**
   ```python
   current_record = primary_dependency_records[i]
   source_guid = "abc-123"
   lineage = ["extract_...", "flatten_..._2", "classify_...", ...]

   # Historical loader finds matching records from other deps
   add_answer_data = historical_loader.load(
       action_name="add_answer_text",
       source_guid="abc-123",
       lineage=lineage,  # Matches branch _2
       fields=["target_word_counts", "answer_text"]
   )

   write_scenario_data = historical_loader.load(
       action_name="write_scenario_question",
       source_guid="abc-123",
       lineage=lineage,  # Matches branch _2
       fields=["question", "options", "answer", "answer_explanation"]
   )

   # All 3 dependencies from SAME branch (_2)
   field_context = {
       "add_answer_text": add_answer_data,
       "write_scenario_question": write_scenario_data,
       "suggest_distractor_counts": current_record["content"],
       "source": {...},
       "seed": {...}
   }
   ```

**Result:**
- ✅ 5 executions (not 15)
- ✅ Each execution has all 3 dependencies from same branch
- ✅ Output: 5 records in `target/generate_distractor_1/`

### Example 2: Data Enrichment Pipeline

**Configuration:**
```yaml
- name: enrich_user_profile
  dependencies:
    - fetch_user_preferences
    - fetch_user_activity
    - fetch_user_demographics
  primary_dependency: fetch_user_demographics  # Override (not last)
  intent: "Enrich user profile with all available data"
  schema:
    enriched_profile: object
  context_scope:
    observe:
      - fetch_user_preferences.preferences
      - fetch_user_activity.last_30_days
      - fetch_user_demographics.*  # Primary
```

**Behavior:**
- Input from: `fetch_user_demographics` (not last in list)
- Executes: Once per user in demographics dataset
- Loads preferences & activity via historical loader

### Example 3: Single Dependency (No Change)

**Configuration:**
```yaml
- name: classify_question
  dependencies: [flatten_questions]
  context_scope:
    observe:
      - flatten_questions.question_text
      - flatten_questions.answer_text
```

**Behavior:**
- Input from: `flatten_questions` (only one)
- Primary: `flatten_questions` (automatic)
- No historical loader needed
- Works exactly as before

### Example 4: Convention (No Explicit Primary)

**Configuration:**
```yaml
- name: generate_summary
  dependencies: [extract_facts, cluster_facts, rank_facts]
  # No primary_dependency specified
  context_scope:
    observe:
      - extract_facts.raw_facts
      - cluster_facts.clusters
      - rank_facts.*  # Last in list = primary by convention
```

**Behavior:**
- Input from: `rank_facts` (last in list, convention)
- Logs: "Using 'rank_facts' (last in list) as primary input"
- Executes: Once per record in rank_facts

---

## Error Handling

### Error 1: Primary Dependency Not in Dependencies List

**Configuration:**
```yaml
dependencies: [dep_A, dep_B]
primary_dependency: dep_C  # Typo
```

**Error:**
```
ConfigurationError: Action 'my_action': primary_dependency 'dep_C' not found in dependencies list: ['dep_A', 'dep_B']

Context:
  action: my_action
  primary_dependency: dep_C
  dependencies: [dep_A, dep_B]

Suggestion: Did you mean 'dep_A' or 'dep_B'?
```

**When Raised:** Workflow load time (static analyzer)

### Error 2: Primary Without Dependencies

**Configuration:**
```yaml
# No dependencies list
primary_dependency: some_action
```

**Error:**
```
ConfigurationError: Action 'my_action' has 'primary_dependency' but no 'dependencies' list.

Context:
  action: my_action
  primary_dependency: some_action

Fix: Remove 'primary_dependency' or add 'dependencies: [...]'
```

**When Raised:** Workflow load time (static analyzer)

### Error 3: Dependency Not Declared in context_scope

**Configuration:**
```yaml
dependencies: [dep_A, dep_B, dep_C]
context_scope:
  observe:
    - dep_A.field1
    - dep_B.field2
    # Missing: dep_C
```

**Error:**
```
ConfigurationError: Dependency 'dep_C' declared but not referenced in context_scope.
Add field declarations (e.g., 'dep_C.*' or 'dep_C.field_name').

Declared dependencies: ['dep_A', 'dep_B']
All dependencies: ['dep_A', 'dep_B', 'dep_C']

Context:
  action: my_action
  missing_dependency: dep_C

Fix: Add to context_scope:
  observe:
    - dep_C.*  # Load all fields
  # OR
    - dep_C.specific_field  # Load specific field
```

**When Raised:** Workflow load time (static analyzer) OR execution time (context building)

### Error 4: Primary Dependency Directory Not Found

**Configuration:**
```yaml
dependencies: [dep_A, dep_B]
primary_dependency: dep_B  # dep_B hasn't run yet
```

**Error:**
```
DependencyError: Primary dependency directory not found: target/dep_B

Context:
  action: my_action
  primary_dependency: dep_B
  all_dependencies: [dep_A, dep_B]
  expected_path: target/dep_B

Cause: 'dep_B' has not completed execution or produced no output.

Fix: Ensure 'dep_B' runs before 'my_action' in the workflow order.
```

**When Raised:** Execution time (directory resolution)

### Error 5: No context_scope with Dependencies

**Configuration:**
```yaml
dependencies: [dep_A, dep_B]
# No context_scope defined
```

**Error:**
```
ConfigurationError: Action 'my_action' has dependencies but no context_scope defined.
All dependencies must have explicit field declarations.

Context:
  action: my_action
  dependencies: [dep_A, dep_B]

Fix: Add context_scope with field declarations:
  context_scope:
    observe:
      - dep_A.*
      - dep_B.*
```

**When Raised:** Execution time (context building)

---

## Testing Strategy

### Unit Tests

#### Test 1: `test_primary_dependency_explicit`
```python
def test_primary_dependency_explicit():
    """Test explicit primary_dependency selection."""
    config = {
        "dependencies": ["dep_A", "dep_B", "dep_C"],
        "primary_dependency": "dep_B",
        "context_scope": {
            "observe": ["dep_A.f1", "dep_B.*", "dep_C.f2"]
        }
    }

    # Should resolve to dep_B directory only
    dirs = resolver.resolve_dependency_directories(config)
    assert len(dirs) == 1
    assert dirs[0].endswith("dep_B")
```

#### Test 2: `test_primary_dependency_convention`
```python
def test_primary_dependency_convention():
    """Test convention (last dependency) when no explicit primary."""
    config = {
        "dependencies": ["dep_A", "dep_B", "dep_C"],
        # No primary_dependency
        "context_scope": {
            "observe": ["dep_A.*", "dep_B.*", "dep_C.*"]
        }
    }

    # Should use last (dep_C) as primary
    dirs = resolver.resolve_dependency_directories(config)
    assert len(dirs) == 1
    assert dirs[0].endswith("dep_C")
```

#### Test 3: `test_primary_dependency_not_in_list_error`
```python
def test_primary_dependency_not_in_list_error():
    """Test error when primary_dependency not in dependencies."""
    config = {
        "dependencies": ["dep_A", "dep_B"],
        "primary_dependency": "dep_C",  # Not in list
        "context_scope": {"observe": ["dep_A.*", "dep_B.*"]}
    }

    with pytest.raises(ConfigurationError) as exc:
        validator.validate_primary_dependency(config, "my_action")

    assert "not found in dependencies list" in str(exc.value)
    assert "dep_C" in str(exc.value)
```

#### Test 4: `test_dependency_not_in_context_scope_error`
```python
def test_dependency_not_in_context_scope_error():
    """Test error when dependency not declared in context_scope."""
    config = {
        "dependencies": ["dep_A", "dep_B", "dep_C"],
        "context_scope": {
            "observe": ["dep_A.f1", "dep_B.f2"]
            # Missing: dep_C
        }
    }

    with pytest.raises(ConfigurationError) as exc:
        processor.extract_allowed_fields(
            config["dependencies"],
            config["context_scope"],
            "my_action"
        )

    assert "dep_C" in str(exc.value)
    assert "not referenced in context_scope" in str(exc.value)
```

#### Test 5: `test_single_dependency_unchanged`
```python
def test_single_dependency_unchanged():
    """Test single dependency behavior unchanged."""
    config = {
        "dependencies": ["dep_A"],
        "context_scope": {"observe": ["dep_A.*"]}
    }

    # Should resolve to dep_A (only one)
    dirs = resolver.resolve_dependency_directories(config)
    assert len(dirs) == 1
    assert dirs[0].endswith("dep_A")
```

### Integration Tests

#### Test 6: `test_multiple_dependencies_execution_count`
```python
def test_multiple_dependencies_execution_count(workflow_env):
    """Test execution count with multiple dependencies."""
    # Setup: 3 dependencies, each with 5 records
    setup_dependency_output("dep_A", records=5)
    setup_dependency_output("dep_B", records=5)
    setup_dependency_output("dep_C", records=5)

    config = {
        "dependencies": ["dep_A", "dep_B", "dep_C"],
        "primary_dependency": "dep_B",  # 5 records
        "context_scope": {
            "observe": ["dep_A.*", "dep_B.*", "dep_C.*"]
        }
    }

    # Execute action
    results = execute_action(config)

    # Should execute 5 times (not 15)
    assert len(results) == 5
```

#### Test 7: `test_lineage_matching_same_branch`
```python
def test_lineage_matching_same_branch(workflow_env):
    """Test that dependencies are matched by lineage (same branch)."""
    # Setup: Split into 3 branches
    setup_split_dependencies(branches=3)

    config = {
        "dependencies": ["dep_A", "dep_B", "dep_C"],
        "primary_dependency": "dep_C",
        "context_scope": {"observe": ["dep_A.*", "dep_B.*", "dep_C.*"]}
    }

    results = execute_action(config)

    # Each result should have dependencies from SAME branch
    for result in results:
        dep_a_lineage = result["field_context"]["dep_A"]["lineage"]
        dep_b_lineage = result["field_context"]["dep_B"]["lineage"]
        dep_c_lineage = result["field_context"]["dep_C"]["lineage"]

        # Extract branch indices
        branch_a = extract_branch_index(dep_a_lineage)
        branch_b = extract_branch_index(dep_b_lineage)
        branch_c = extract_branch_index(dep_c_lineage)

        # All should be same branch
        assert branch_a == branch_b == branch_c
```

#### Test 8: `test_parallel_branch_merging_unchanged`
```python
def test_parallel_branch_merging_unchanged(workflow_env):
    """Test parallel branch merging still works."""
    # Setup: Single action splits into 5 branches
    setup_split_action("flatten_questions", branches=5, records_per_branch=3)

    config = {
        "dependencies": ["flatten_questions"],
        "context_scope": {"observe": ["flatten_questions.*"]}
    }

    results = execute_action(config)

    # Should merge all 5 branches: 5 * 3 = 15 records
    assert len(results) == 15
```

### Static Analyzer Tests

#### Test 9: `test_static_analyzer_validates_primary`
```python
def test_static_analyzer_validates_primary():
    """Test static analyzer catches invalid primary_dependency."""
    workflow = """
actions:
  - name: action_A
    dependencies: [dep_1, dep_2]
    primary_dependency: dep_3  # Not in list
    """

    with pytest.raises(ConfigurationError):
        analyzer.validate_workflow(workflow)
```

#### Test 10: `test_static_analyzer_validates_context_scope`
```python
def test_static_analyzer_validates_context_scope():
    """Test static analyzer catches missing context_scope declarations."""
    workflow = """
actions:
  - name: action_A
    dependencies: [dep_1, dep_2, dep_3]
    context_scope:
      observe:
        - dep_1.field1
        - dep_2.field2
        # Missing: dep_3
    """

    with pytest.raises(ConfigurationError) as exc:
        analyzer.validate_workflow(workflow)

    assert "dep_3" in str(exc.value)
    assert "not referenced in context_scope" in str(exc.value)
```

---

## Backward Compatibility

### Compatible Changes

1. **`primary_dependency` is optional**
   - Existing workflows without it continue to work
   - Default behavior: last dependency is primary
   - No breaking change

2. **Single dependency behavior unchanged**
   - Actions with one dependency work exactly as before
   - No migration needed

3. **Parallel branch merging unchanged**
   - Existing split/merge patterns continue to work
   - No breaking change

### Breaking Changes

1. **Missing `context_scope` declarations now ERROR**
   - **Before:** Warning + load all fields
   - **After:** ConfigurationError at load time
   - **Impact:** Workflows with implicit field loading break
   - **Migration:** Add explicit field declarations
   - **Justification:** Progressive data exposure requires explicit declarations

2. **Multiple dependencies behavior changed**
   - **Before:** All dependency outputs merged (incorrect)
   - **After:** Only primary used as input (correct)
   - **Impact:** Workflows relying on merging break
   - **Migration:** Add `primary_dependency` if needed
   - **Justification:** Previous behavior was a bug (5 → 15 execution multiplication)

### Migration Timeline

**Phase 1: Soft Launch (Warning Mode)**
- Add `primary_dependency` support
- Keep old merging behavior as default
- Add WARNING when multiple deps without explicit primary
- Duration: 1 release cycle

**Phase 2: Transition (Error Mode)**
- Make missing `context_scope` declarations an ERROR
- Keep old merging behavior with WARNING
- Duration: 1 release cycle

**Phase 3: Full Enforcement**
- Switch to new behavior (primary-only input)
- Remove old merging logic for multiple deps
- All warnings become errors

---

## Documentation Updates

### 1. User Guide - Multiple Dependencies Section

**File:** `docs/user_guide/dependencies.md`

Add new section:
```markdown
## Multiple Dependencies

When an action depends on multiple upstream actions, you must specify which one
provides the input dataset using `primary_dependency`:

```yaml
- name: my_action
  dependencies: [action_A, action_B, action_C]
  primary_dependency: action_B  # action_B determines execution count
  context_scope:
    observe:
      - action_A.field1
      - action_B.*        # Primary dependency
      - action_C.field2
```

**Key Points:**
- Primary dependency's output files determine execution count
- Other dependencies loaded via historical context (lineage matching)
- All dependencies MUST be declared in `context_scope`
- If not specified, last dependency is primary by convention
```

### 2. Configuration Schema Reference

**File:** `docs/reference/action_schema.md`

Add field documentation:
```markdown
### primary_dependency

**Type:** `string`
**Required:** No
**Default:** Last dependency in `dependencies` list

Specifies which dependency provides the input dataset when an action has
multiple dependencies.

**Example:**
```yaml
dependencies: [dep_A, dep_B, dep_C]
primary_dependency: dep_B  # Use dep_B as input source
```

**Validation:**
- Must exist in `dependencies` list
- Only valid when `dependencies` is not empty
- Raises `ConfigurationError` if invalid
```

### 3. Error Reference

**File:** `docs/reference/errors.md`

Add error documentation for new errors (see Error Handling section above)

### 4. Migration Guide

**File:** `docs/migration/v2_to_v3.md`

Add migration instructions (see Migration Guide section above)

---

## Future Enhancements

### Enhancement 1: Primary Dependency Auto-Detection

**Idea:** Automatically detect which dependency should be primary based on usage

```python
def auto_detect_primary(dependencies, context_scope):
    """
    Heuristic: Dependency with most fields in passthrough is likely primary
    (since passthrough fields appear in output)
    """
    pass
```

**Status:** Deferred (keep explicit for v1)

### Enhancement 2: Multiple Primary Dependencies (Union)

**Idea:** Support multiple primaries for union semantics

```yaml
primary_dependencies: [dep_A, dep_B]  # Execute for records in EITHER
merge_strategy: union  # or: intersection
```

**Status:** Deferred (not needed yet)

### Enhancement 3: Dependency Aliases

**Idea:** Rename dependencies in context

```yaml
dependencies:
  user_data: fetch_user_profile
  activity: fetch_user_activity
primary_dependency: user_data
context_scope:
  observe:
    - user_data.*  # Clearer than fetch_user_profile.*
```

**Status:** Deferred (nice-to-have)

---

## Summary

### What Changes

1. **New field:** `primary_dependency` (optional, defaults to last in list)
2. **Validation:** All dependencies MUST be in `context_scope` (error, not warning)
3. **Behavior:** Only primary dependency files loaded as input
4. **Matching:** Non-primary deps loaded via historical loader with lineage matching

### Benefits

- ✅ **Predictable:** Clear rule for input selection
- ✅ **Correct:** 5 inputs → 5 executions (not 15)
- ✅ **Explicit:** Self-documenting configuration
- ✅ **Efficient:** Progressive data exposure enforced
- ✅ **Public-tool ready:** Easy to explain, clear errors

### Migration Required

- Add `primary_dependency` (recommended) or rely on convention
- Add all dependencies to `context_scope` (required)
- Update any workflows with multiple dependencies

---

## Approval Checklist

- [ ] Architecture reviewed
- [ ] Static analyzer changes specified
- [ ] Runtime behavior specified
- [ ] Error handling complete
- [ ] Test strategy defined
- [ ] Documentation plan complete
- [ ] Migration guide written
- [ ] Backward compatibility considered
- [ ] Example configurations provided
- [ ] Implementation ready to begin

---

**End of RFC**
