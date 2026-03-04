# Config Module Tech Debt (Deferred from Hardening Review)

## P2-12: PathManager god class (372 lines)
- **File:** `agent_actions/config/paths.py`
- **Issue:** Single class handles project root detection, standard path resolution, path validation, path normalization, file finding, path cleaning, and mirror path creation.
- **Suggestion:** Split into focused classes (e.g., `ProjectRootResolver`, `PathValidator`, `PathCleaner`).
- **Why deferred:** Large refactor, correctness unaffected. No bugs caused by current structure.

## P2-13: ProcessorRegistry 4x duplication
- **File:** `agent_actions/config/di/container.py`
- **Issue:** `register_processor/loader/generator/service` and `get_processor/loader/generator/service` follow identical patterns with only the dict name varying.
- **Suggestion:** Generic `register(category, name)` / `get(category, name)` with category enum.
- **Why deferred:** Cosmetic, stable pattern. Refactoring risks breaking decorator usage at registration sites.

## P2-14: Two ProcessingMode enums
- **Files:** `agent_actions/config/interfaces.py` (SYNC/ASYNC/AUTO), workflow engine (ONLINE/BATCH)
- **Issue:** Both are named `ProcessingMode` but represent semantically distinct concepts.
- **Resolution:** These are intentionally distinct. `interfaces.ProcessingMode` controls sync/async execution strategy per-component. The workflow-level mode controls online vs batch data flow.
- **Action:** Added clarifying docstrings (no rename needed — they live in separate namespaces).

## Circular dependency detection in WorkflowConfigV2
- **File:** `agent_actions/config/schema.py` (`validate_workflow_invariants`)
- **Issue:** The validator checks for duplicate action names and dangling deps but does not detect circular dependencies (A→B→A).
- **Suggestion:** Add a topological sort or DFS cycle check in `validate_workflow_invariants`. The dependency graph is already extracted by `get_dependency_graph()`.
- **Why deferred:** Runtime DAG executor already detects cycles at execution time. Adding it at parse time is a natural enhancement but not a correctness gap.

## P2-16/17: Heavy Dict/Any usage and 81-field TypedDict
- **Files:** Throughout `agent_actions/config/`
- **Issue:** Extensive `Dict[str, Any]` in DI config, and large `AgentConfigDict` TypedDict.
- **Suggestion:** Introduce domain-specific config models (Pydantic or dataclass) to replace Dict[str, Any] at key boundaries.
- **Why deferred:** Project-wide typing pass needed. Current approach works and is tested.
