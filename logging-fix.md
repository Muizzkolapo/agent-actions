# Logging Improvement Prompt

## Problem
The logging throughout the codebase is inconsistent, unclear, and doesn't provide enough context for debugging. Issues include:

1. **Inconsistent prefixes**: Mix of `[STATIC_DATA]`, `[STATIC_DATA_LOAD]`, `[STATIC_DATA_LOADED]`, etc.
2. **Wrong log levels**: Using `info` where `debug` is more appropriate (or vice versa)
3. **Missing context**: Errors don't include agent names, file paths, or operation context
4. **Poor error messages**: Generic messages like "Failed to load" without specifics
5. **No operation tracking**: Can't trace a request through multiple components

## Logging Standards to Implement

### 1. Log Level Guidelines

**DEBUG** - Detailed internal state (file paths resolved, cache hits, iterations)
```python
logger.debug(f"Resolved static data path: {resolved_path}")
logger.debug(f"Cache hit for field '{field_name}': {cache_key}")
```

**INFO** - Important business events (operations started/completed, counts)
```python
logger.info(f"Loading static data for agent '{agent_name}'")
logger.info(f"Loaded {len(static_data)} static data files: {list(static_data.keys())}")
```

**WARNING** - Degraded functionality, fallbacks used, unexpected but recoverable
```python
logger.warning(f"seed_data/ not found, using fallback: {fallback_path}")
logger.warning(f"Agent config for '{agent_name}' is None, skipping")
```

**ERROR** - Operation failed, but application continues
```python
logger.error(f"Failed to load static data for '{field_name}': {error}")
```

### 2. Structured Logging Format

Use consistent format: `[COMPONENT] Operation: details`

**Component prefixes** (pick ONE per module):
- `[STATIC_DATA]` - Static data loader operations
- `[PROMPT_PREP]` - Prompt preparation service
- `[BATCH]` - Batch processing
- `[CONTEXT]` - Context scope processing
- `[HISTORICAL]` - Historical node loading
- `[TARGET_GEN]` - Target generation

**Example**:
```python
# Good
logger.info("[STATIC_DATA] Loading 3 files for agent 'generate_summary'")
logger.debug("[STATIC_DATA] Resolved path: /path/to/seed_data/exam.json")
logger.error("[STATIC_DATA] File not found: exam.json (agent: generate_summary)")

# Bad
logger.info("Loading static data...")  # No context
logger.info("[STATIC_DATA_LOAD] Starting...")  # Inconsistent prefix
```

### 3. Error Context Pattern

ALWAYS include context in errors:
```python
logger.error(
    f"[STATIC_DATA] Failed to load '{field_name}': {error}",
    extra={
        'agent_name': agent_name,
        'field_name': field_name,
        'file_path': str(file_path),
        'error_type': type(error).__name__
    }
)
```

### 4. Operation Tracking Pattern

For multi-step operations, use start/complete/fail pattern:
```python
logger.info(f"[PROMPT_PREP] Starting prompt preparation for '{agent_name}' ({mode} mode)")
try:
    # ... operation ...
    logger.info(f"[PROMPT_PREP] Completed for '{agent_name}': {len(formatted_prompt)} chars")
except Exception as e:
    logger.error(f"[PROMPT_PREP] Failed for '{agent_name}': {e}")
    raise
```

### 5. Sensitive Data Handling

**NEVER log**:
- API keys
- Credentials
- Full file contents (log length instead)
- User data (PII)

**DO log**:
- File paths
- Counts/lengths
- Configuration keys (not values if sensitive)
- Error types

```python
# Good
logger.debug(f"[BATCH] Processing {len(tasks)} tasks for agent '{agent_name}'")
logger.debug(f"[STATIC_DATA] File size: {file_size} bytes")

# Bad
logger.debug(f"API key: {api_key}")  # NEVER
logger.info(f"Full config: {config}")  # Too much detail
```

## Task Instructions

### Phase 1: Audit Current Logging

1. Search for all `logger.debug()`, `logger.info()`, `logger.warning()`, `logger.error()` calls
2. Categorize by module/component
3. Identify inconsistencies:
   - Mixed log levels for similar operations
   - Inconsistent prefixes
   - Missing context
   - Generic messages

### Phase 2: Fix Priority Areas

**High Priority** (fix first):
- Error logging (ensure all errors have context)
- Static data loading (inconsistent prefixes)
- Batch processing (missing operation tracking)
- Prompt preparation (too verbose at INFO level)

**Medium Priority**:
- Context scope processing
- Historical node loading
- Target generation

**Low Priority**:
- Utility functions
- Helper methods

### Phase 3: Apply Fixes

For each module:

1. **Choose component prefix** (e.g., `[STATIC_DATA]`)
2. **Standardize log levels**:
   - Move detailed path resolutions to DEBUG
   - Keep operation start/complete at INFO
   - Add WARNING for fallbacks
   - Ensure ERROR has full context
3. **Add context** to all error messages:
   - Agent name
   - File path
   - Operation being performed
4. **Use consistent patterns**:
   - Start: `"[COMPONENT] Starting operation for 'entity'"`
   - Complete: `"[COMPONENT] Completed operation: results summary"`
   - Error: `"[COMPONENT] Failed operation for 'entity': error details"`

### Phase 4: Test Logging

Create test scenarios and verify logs are:
- **Clear**: Can understand what's happening without code
- **Traceable**: Can follow a request through components
- **Debuggable**: Enough detail to diagnose issues
- **Concise**: Not overwhelming at INFO level

## Files to Focus On

Priority order:
1. `agent_actions/utilities/static_data_loader.py` - Inconsistent prefixes
2. `agent_actions/prompt_generation/prompt_preparation_service.py` - Too verbose
3. `agent_actions/utilities/context_scope_processor.py` - Missing context
4. `agent_actions/llm_invocation/batch/batch_task_preparator.py` - Poor error tracking
5. `agent_actions/preprocessing/historical_node_loader.py` - Generic messages
6. `agent_actions/orchestration/target_generator.py` - Minimal logging

## Example Before/After

### Before (Bad)
```python
logger.info(f"[STATIC_DATA_LOAD] Starting static data loading...")
logger.info(f"[STATIC_DATA_LOAD] Static data directory: {static_data_dir}")
logger.info(f"[STATIC_DATA_LOAD] Loaded {len(static_data)} static data files: {list(static_data.keys())}")
logger.info(f"[STATIC_DATA_LOAD] Static data keys: {list(static_data.keys())}")  # Duplicate!
```

### After (Good)
```python
logger.info(f"[STATIC_DATA] Loading for agent '{agent_name}' from {static_data_dir.name}/")
logger.debug(f"[STATIC_DATA] Full path: {static_data_dir}")
logger.info(f"[STATIC_DATA] Loaded {len(static_data)} files: {', '.join(static_data.keys())}")
```

### Before (Bad Error)
```python
logger.error(f"Failed to load static data: {e}")
```

### After (Good Error)
```python
logger.error(
    f"[STATIC_DATA] Failed to load '{field_name}' for agent '{agent_name}': {e}",
    extra={
        'agent_name': agent_name,
        'field_name': field_name,
        'file_path': str(file_path),
        'error_type': type(e).__name__
    }
)
```

## Success Criteria

After fixes:
- ✅ All log messages have component prefix
- ✅ All errors include agent name and context
- ✅ INFO level shows operation flow without noise
- ✅ DEBUG level has detailed diagnostics
- ✅ Can trace a request through logs
- ✅ No duplicate or redundant log messages
- ✅ Sensitive data never logged
