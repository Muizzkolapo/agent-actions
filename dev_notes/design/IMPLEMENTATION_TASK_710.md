# Implementation Task: Issue #710 - Redesign Node Directory Naming

## Overview
Remove index prefix from directory names (`node_13_validate_answer_1/` → `validate_answer_1/`) and introduce manifest file as single source of truth.

**No backward compatibility required.**

---

## Phase 1: Create ManifestManager Infrastructure

### Task 1.1: Create ManifestManager Class
- [ ] Create `agent_actions/orchestration/manifest_manager.py`
- [ ] Implement `ManifestManager` class with:
  - `__init__(agent_io_path: Path)`
  - `initialize_manifest(workflow_name, execution_order, levels, agent_configs)`
  - `get_output_directory(action_name: str) -> Path`
  - `get_dependency_directories(action_name: str) -> List[Path]`
  - `mark_action_started(action_name: str)`
  - `mark_action_completed(action_name: str, record_count: int)`
  - `is_action_completed(action_name: str) -> bool`
  - `load_manifest() -> dict`
  - `save_manifest()`
- [ ] Add schema version and validation
- [ ] Write manifest to `target/.manifest.json`

### Task 1.2: Integrate ManifestManager into AgentWorkflow
- [ ] Update `agent_actions/orchestration/agent_workflow.py`
- [ ] Initialize ManifestManager in `_initialize_services()`
- [ ] Write manifest at workflow start
- [ ] Update manifest after each action completes

---

## Phase 2: Update NodeMappingService

### Task 2.1: Simplify Directory Naming
- [ ] Update `agent_actions/orchestration/node_mapper.py`
- [ ] Change `get_node_directory_name(agent_name, idx)` → `get_node_directory_name(agent_name)`
- [ ] Remove `get_node_prefix(idx)` or update to return empty string
- [ ] Update all callers

---

## Phase 3: Update Path Construction (40+ sites)

### Task 3.1: Update AgentRunner
- [ ] File: `agent_actions/orchestration/agent_runner.py`
- [ ] Lines 180, 187, 208, 227: Remove `node_{idx}_` prefix
- [ ] Replace glob fallback with manifest lookup
- [ ] Update `_resolve_dependency_directories()` to use manifest
- [ ] Update `_resolve_linear_directory()` to use manifest
- [ ] Update `setup_directories()` output path

### Task 3.2: Update OutputManager
- [ ] File: `agent_actions/orchestration/output_manager.py`
- [ ] Lines 163, 207, 429, 436, 487, 530, 545: Remove prefix
- [ ] Update `get_previous_outputs()` to use manifest
- [ ] Update `get_upstream_directories()` to use manifest
- [ ] Remove glob-based fallback logic

### Task 3.3: Update AgentExecutor
- [ ] File: `agent_actions/orchestration/agent_executor.py`
- [ ] Lines 304, 340: Update batch output directory paths

### Task 3.4: Update BatchManager
- [ ] File: `agent_actions/orchestration/batch_manager.py`
- [ ] Line 139: Update node output directory path

### Task 3.5: Update LoopCorrelator
- [ ] File: `agent_actions/orchestration/loop_correlator.py`
- [ ] Lines 94, 134: Update directory paths
- [ ] Lines 152-156: Remove index parsing logic, use manifest

### Task 3.6: Update ArtifactLinker
- [ ] File: `agent_actions/orchestration/artifact_linker.py`
- [ ] Lines 56, 131: Update `startswith("node_")` to use manifest
- [ ] Update `find_latest_node_dir()` to use manifest

---

## Phase 4: Update Data Loading & Lineage

### Task 4.1: Update HistoricalNodeLoader
- [ ] File: `agent_actions/preprocessing/context/historical_node_loader.py`
- [ ] Lines 200-204, 241: Replace index-based lookup with manifest
- [ ] Update `_find_node_in_lineage()` logic
- [ ] Update `_construct_target_path()` to not use index

### Task 4.2: Update IDGenerator
- [ ] File: `agent_actions/utilities/id_generation/id_generator.py`
- [ ] Lines 24-34: Update `generate_node_id()` format

### Task 4.3: Update LineageBuilder
- [ ] File: `agent_actions/utilities/lineage/lineage_builder.py`
- [ ] Lines 24, 40-62: Update lineage filtering logic

### Task 4.4: Update PathManager
- [ ] File: `agent_actions/state_management/path_manager.py`
- [ ] Line 76: Update `PathType.TARGET` template

### Task 4.5: Update SourceDataLoader
- [ ] File: `agent_actions/input_loading/loaders.source_data.py`
- [ ] Lines 65-89: Update path parsing logic

### Task 4.6: Update BatchSourceHandler
- [ ] File: `agent_actions/llm_invocation/batch/infrastructure/batch_source_handler.py`
- [ ] Lines 38-57: Update workflow root navigation

---

## Phase 5: Update Analysis Scripts

### Task 5.1: Update Field Flow Analyzer
- [ ] File: `agent_actions/skills/agent-actions-workflow/scripts/analyze_field_flow.py`
- [ ] Lines 63-65, 79-87, 94: Update `parse_node_name()` and analysis

---

## Phase 6: Update Tests

### Task 6.1: Update Loop Correlator Tests
- [ ] File: `tests/core/graph/test_loop_correlator.py`
- [ ] Update all `node_X_` directory creation

### Task 6.2: Update Context Scope Tests
- [ ] File: `tests/integration/test_context_scope_split_records.py`
- [ ] Update indexed test directories

### Task 6.3: Update Ancestry Chain Tests
- [ ] File: `tests/preprocessing/context/test_ancestry_chain_matching.py`
- [ ] Update lineage patterns

### Task 6.4: Update Passthrough Tests
- [ ] File: `tests/core/graph/test_agent_workflow_passthrough_cleanup.py`
- [ ] Update marker cleanup tests

### Task 6.5: Update Lineage Tests
- [ ] File: `tests/unit/prompt_generation/test_file_level_lineage.py`
- [ ] Update `node_X` pattern verification

### Task 6.6: Update Dependency Resolution Tests
- [ ] File: `tests/verify_dependency_resolution.py`
- [ ] Update path assertions

---

## Phase 7: Cleanup

### Task 7.1: Remove Deprecated Code
- [ ] Remove `agent_indices` usage for path construction
- [ ] Remove glob fallback logic throughout
- [ ] Remove index parsing from directory names
- [ ] Clean up unused imports

### Task 7.2: Update Documentation
- [ ] Update any inline documentation
- [ ] Update docstrings for changed functions

---

## Files Summary

### New Files
- `agent_actions/orchestration/manifest_manager.py`

### Modified Files (Priority Order)
1. `agent_actions/orchestration/manifest_manager.py` (NEW)
2. `agent_actions/orchestration/node_mapper.py`
3. `agent_actions/orchestration/agent_workflow.py`
4. `agent_actions/orchestration/agent_runner.py`
5. `agent_actions/orchestration/output_manager.py`
6. `agent_actions/orchestration/agent_executor.py`
7. `agent_actions/orchestration/batch_manager.py`
8. `agent_actions/orchestration/loop_correlator.py`
9. `agent_actions/orchestration/artifact_linker.py`
10. `agent_actions/preprocessing/context/historical_node_loader.py`
11. `agent_actions/utilities/id_generation/id_generator.py`
12. `agent_actions/utilities/lineage/lineage_builder.py`
13. `agent_actions/state_management/path_manager.py`
14. `agent_actions/input_loading/loaders.source_data.py`
15. `agent_actions/llm_invocation/batch/infrastructure/batch_source_handler.py`
16. `agent_actions/skills/agent-actions-workflow/scripts/analyze_field_flow.py`

### Test Files
1. `tests/core/graph/test_loop_correlator.py`
2. `tests/integration/test_context_scope_split_records.py`
3. `tests/preprocessing/context/test_ancestry_chain_matching.py`
4. `tests/core/graph/test_agent_workflow_passthrough_cleanup.py`
5. `tests/unit/prompt_generation/test_file_level_lineage.py`
6. `tests/verify_dependency_resolution.py`

---

## Success Criteria
- [ ] All tests pass
- [ ] Directories created as `{action_name}/` not `node_{idx}_{action_name}/`
- [ ] Manifest file written to `target/.manifest.json`
- [ ] Dependency resolution uses manifest
- [ ] No index mismatch errors possible
- [ ] Incremental runs work correctly
