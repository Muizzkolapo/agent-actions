# Context System Redesign - No Fallbacks Architecture

## Problem Statement

Current `build_field_context_with_history()` has multiple fallback paths that make context building unpredictable:
1. Source content unwrapping fallbacks
2. Historical file loading with fallback to contents
3. Schema-based field inference
4. Silent failures that mask configuration errors

**User Requirement**: "no FALL backs its important we do not fall back we need a full design"

## Design Principles

1. **Single Source of Truth**: Context determined ONLY by dependencies and context_scope
2. **Explicit Mode Handling**: Batch and realtime are separate code paths, no fallbacks between them
3. **Fail Fast**: Missing dependencies or fields cause immediate, clear errors
4. **No Schema Inference**: Context built from actual runtime data only
5. **Matches anatomy.md**: Exactly 5 namespaces as documented

## Architecture

### Field Context Structure (Batch Mode)

```python
field_context = {
    "source": {           # Original input data
        "text": "...",
        "url": "...",
    },
    "add_answer_text": {  # Dependency action output
        "question": "...",
        "answer_text": [...],
    },
    "suggest_distractor_counts": {  # Another dependency
        "target_word_counts": {...},
    },
    "seed": {             # Static reference data
        "exam_syllabus": {...},
    },
    "loop": {             # Loop metadata
        "index": 0,
        "count": 5,
    },
    "workflow": {         # Workflow metadata
        "id": "...",
        "name": "...",
    },
}
```

### Data Flow

```
1. BUILD CONTEXT
   ↓
   For each namespace:
   - source: Extract from input record content
   - {dep_name}: Load from historical file (batch) or contents (realtime)
   - seed: Load from static_data parameter
   - loop: From loop_context parameter
   - workflow: From workflow_metadata parameter
   ↓
2. APPLY CONTEXT_SCOPE
   ↓
   - observe: Extract fields to llm_context (flat dict)
   - passthrough: Extract fields to passthrough_fields
   - drop: Remove fields from prompt_context
   ↓
3. RENDER & EXECUTE
```

### Batch Mode Implementation

```python
def build_field_context_for_batch(
    agent_config: Dict,
    current_item: Dict,
    file_path: str,
    agent_indices: Dict[str, int],
    source_content: Optional[Any] = None,
    static_data: Optional[Dict] = None,
    loop_context: Optional[Dict] = None,
    workflow_metadata: Optional[Dict] = None,
) -> Dict:
    """
    Build field context for batch mode with explicit dependency loading.

    No fallbacks - if dependency declared but not found, raise error.
    """
    field_context = {}
    agent_name = agent_config["name"]

    # 1. SOURCE namespace
    if source_content:
        field_context["source"] = _extract_content_data(source_content)

    # 2. DEPENDENCY namespaces - load from historical files ONLY
    dependencies = agent_config.get("dependencies", [])
    lineage = current_item.get("lineage", [])
    source_guid = current_item.get("source_guid")

    if not dependencies:
        logger.debug(f"Action '{agent_name}' has no dependencies")

    for dep_name in dependencies:
        logger.debug(f"Loading historical data for dependency: {dep_name}")

        historical_data = _load_historical_node(
            action_name=dep_name,
            lineage=lineage,
            source_guid=source_guid,
            file_path=file_path,
            agent_indices=agent_indices,
            parent_target_id=current_item.get("parent_target_id"),
            root_target_id=current_item.get("root_target_id"),
        )

        if historical_data is None:
            # FAIL FAST - no fallback to contents or schema
            raise MissingDependencyError(
                f"Action '{agent_name}' declares dependency '{dep_name}' but "
                f"historical data not found. Lineage: {lineage}, "
                f"source_guid: {source_guid}, file_path: {file_path}"
            )

        logger.debug(f"Loaded {len(historical_data)} fields for '{dep_name}'")
        field_context[dep_name] = historical_data

    # 3. SEED namespace
    if static_data:
        field_context["seed"] = static_data
        logger.debug(f"Added {len(static_data)} seed data fields")

    # 4. LOOP namespace
    if loop_context:
        field_context["loop"] = loop_context

    # 5. WORKFLOW namespace
    if workflow_metadata:
        field_context["workflow"] = workflow_metadata

    logger.debug(
        f"Built field_context with namespaces: {list(field_context.keys())}"
    )

    return field_context


def _extract_content_data(source_content: Any) -> Dict:
    """
    Extract content portion from record structure.

    Handles both:
    - {source_guid, content: {...}} wrapper → extract content
    - Flat dict → return as-is (excluding metadata keys)
    """
    if not isinstance(source_content, dict):
        return {}

    # Wrapped format: {source_guid, content: {...}}
    if "content" in source_content and isinstance(source_content["content"], dict):
        return source_content["content"]

    # Flat format: {...} but exclude metadata
    return {
        k: v for k, v in source_content.items()
        if k not in ["source_guid", "lineage", "node_id", "metadata", "target_id", "parent_target_id", "root_target_id"]
    }


def _load_historical_node(
    action_name: str,
    lineage: List[str],
    source_guid: str,
    file_path: str,
    agent_indices: Dict[str, int],
    parent_target_id: Optional[str] = None,
    root_target_id: Optional[str] = None,
) -> Optional[Dict]:
    """
    Load historical node data from saved files.

    Uses existing HistoricalNodeDataLoader with HistoricalDataRequest.
    Returns content dict or None if not found.
    """
    from agent_actions.preprocessing.context.historical_node_loader import (
        HistoricalNodeDataLoader,
        HistoricalDataRequest,
    )

    request = HistoricalDataRequest(
        action_name=action_name,
        lineage=lineage,
        source_guid=source_guid,
        file_path=file_path,
        agent_indices=agent_indices,
        caller_lineage=lineage,
        parent_target_id=parent_target_id,
        root_target_id=root_target_id,
    )

    return HistoricalNodeDataLoader.load_historical_node_data(request)
```

## Migration Strategy

### Phase 1: Replace batch mode logic
1. Keep existing function signature for compatibility
2. Detect batch mode (has file_path + current_item + agent_indices)
3. Route to new `build_field_context_for_batch()`
4. Remove fallback code (lines 365-384)

### Phase 2: Cleanup
1. Remove source unwrapping fallbacks (lines 295-313) - fold into _extract_content_data()
2. Simplify historical loading (lines 316-363) - use new _load_historical_node()
3. Remove contents parameter dependency

### Phase 3: Realtime mode
1. Design realtime context building (separate from batch)
2. Implement clean realtime path
3. Remove mode detection, require explicit mode parameter

## Benefits

1. **Predictable**: Context always built the same way
2. **Debuggable**: Clear error messages when dependencies missing
3. **Maintainable**: Single code path per mode
4. **Correct**: Matches anatomy.md architecture
5. **Safe**: Fails fast on misconfiguration

## Breaking Changes

1. **Missing dependencies now fail**: Previously silently fell back to contents
2. **No schema inference**: Context uses only actual data
3. **Explicit mode required**: No automatic fallback between batch/realtime

These are GOOD breaking changes - they expose configuration errors that were previously hidden.
