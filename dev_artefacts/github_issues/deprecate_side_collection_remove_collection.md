# Deprecate and Remove Legacy Field Names: `side_collection` and `remove_collection`

## Summary
Replace internal legacy field names `side_collection` and `remove_collection` with the user-facing YAML API names `observe` and `drops` throughout the codebase. This will eliminate the confusing dual naming system and make the code easier to understand and maintain.

## Problem Statement

We currently have **two different names for the same concepts**:

| User-Facing (YAML) | Internal (Code) | Purpose |
|-------------------|-----------------|---------|
| `observe` | `side_collection` | Fields to pass through from input to output |
| `drops` | `remove_collection` | Fields to remove from output |

### Current Confusion

**In YAML configs**, users write:
```yaml
actions:
  - name: extractor
    observe: [document_id, author]
    drops: [temp_data]
```

**In Pydantic models**, it's stored as:
```python
class AgentConfig(BaseModel):
    side_collection: List[str] = Field(default_factory=list)  # Not 'observe'!
    remove_collection: List[str] = Field(default_factory=list)  # Not 'drops'!
```

**In code**, both names are used interchangeably:
```python
# ActionExpander uses observe → side_collection
observe = template_replacer(combined_observe)
agent['side_collection'] = observe

# Validators need to check both names
observe = agent_config.get('observe', agent_config.get('side_collection', []))
```

### Impact of This Confusion

1. **Developer Confusion**: New developers see `side_collection` in code and don't know it's the same as `observe`
2. **Maintenance Burden**: Need to check both names in validators and utility functions
3. **Bug Potential**: Easy to forget to check one of the names (exactly what caused the input signature validation bug)
4. **Code Smell**: Having multiple names for the same thing violates DRY principle
5. **Documentation Inconsistency**: Docs use `observe`/`drops`, but code has `side_collection`/`remove_collection`

### Recent Bug Example

The input signature validation bug we just fixed was caused by this dual naming:
- Validator looked for `observe`
- Pydantic model had `side_collection`
- Result: Validation failed incorrectly

**Fix applied**: Made validator check both names as fallback
**Better solution**: Remove the dual naming entirely

## Root Cause: Historical Legacy

These legacy names (`side_collection`, `remove_collection`) come from the original codebase before the YAML API was designed with clearer names (`observe`, `drops`).

**Timeline:**
1. **Original design**: Used `side_collection` and `remove_collection` internally
2. **YAML API evolution**: Introduced clearer names `observe` and `drops` for user configs
3. **Pydantic models**: Kept old internal names, creating dual naming
4. **Current state**: Codebase has both names, causing confusion

**Why we should remove them now:**
- Users never see `side_collection`/`remove_collection` - they're purely internal
- The legacy names don't provide better clarity than `observe`/`drops`
- Modern codebase should use consistent, clear naming
- PR #431 (unified field referencing) makes field names more prominent

## Proposed Solution

### Rename Strategy: Use `observe` and `drops` Everywhere

**Phase 1: Pydantic Models**
```python
# BEFORE
class AgentConfig(BaseModel):
    side_collection: List[str] = Field(default_factory=list)
    remove_collection: List[str] = Field(default_factory=list)

# AFTER
class AgentConfig(BaseModel):
    observe: List[str] = Field(default_factory=list)
    drops: List[str] = Field(default_factory=list)
```

**Phase 2: Constants**
```python
# BEFORE (agent_actions/core/constants.py)
SIDE_COLLECTION_KEY = "side_collection"
REMOVE_COLLECTION_KEY = "remove_collection"  # If it exists

# AFTER
OBSERVE_KEY = "observe"
DROPS_KEY = "drops"
```

**Phase 3: Code References**
- Replace all `agent['side_collection']` → `agent['observe']`
- Replace all `agent_config.get('side_collection')` → `agent_config.get('observe')`
- Replace all `remove_collection` → `drops`
- Update method names: `transform_with_side_collection()` → `transform_with_observe()`
- Update comments and docstrings

**Phase 4: Clean Up Validators**
```python
# BEFORE (with fallback for compatibility)
observe = agent_config.get('observe', agent_config.get('side_collection', []))

# AFTER (single source of truth)
observe = agent_config.get('observe', [])
```

### Migration Path

Since these are **internal names only**, this is **not a breaking change** for users:
- ✅ YAML configs use `observe`/`drops` (unchanged)
- ✅ Runtime behavior unchanged
- ✅ No user-facing API changes
- ⚠️ Only affects internal codebase

**No deprecation period needed** - this is purely internal refactoring.

## Implementation Plan

### Step 1: Update Pydantic Models
**Files:**
- `agent_actions/core/parser/config_schema.py`
- `agent_actions/core/parser/config_types.py`
- `agent_actions/core/parser/processor_config.py`

**Changes:**
```python
# Rename fields in Pydantic models
side_collection → observe
remove_collection → drops
```

### Step 2: Update Constants
**File:** `agent_actions/core/constants.py`

**Changes:**
```python
# Add new constants
OBSERVE_KEY = "observe"
DROPS_KEY = "drops"

# Keep old ones temporarily with deprecation comment
# TODO: Remove in next major version
SIDE_COLLECTION_KEY = "side_collection"  # Deprecated: Use OBSERVE_KEY
```

### Step 3: Update ActionExpander
**File:** `agent_actions/core/parser/action_expander.py`

**Changes:**
```python
# Line 293: Change mapping
agent['observe'] = observe  # Was: agent['side_collection']
agent['drops'] = drops      # Was: agent['remove_collection']
```

### Step 4: Update All Code References
**Files affected (28 files, ~190 occurrences):**

**Core generators:**
- `agent_actions/agents/generators/data_generator.py`
- `agent_actions/agents/generators/target_data_generator.py`
- `agent_actions/agents/generators/target_data_processor.py`

**Transformers:**
- `agent_actions/agents/transformers/context_preprocessor.py`
- `agent_actions/agents/transformers/data_processor.py`
- `agent_actions/agents/transformers/response_transformer.py`
- `agent_actions/agents/transformers/pp_context_preprocessor.py`
- `agent_actions/agents/transformers/pp_response_transformer.py`

**Utilities:**
- `agent_actions/_internal/utils/processor_utils.py`
- `agent_actions/_internal/utils/processor_helpers.py`
- `agent_actions/core/utils/processor_utils.py`
- `agent_actions/core/utils/processor_helpers.py`

**Services:**
- `agent_actions/tasks/services/batch_service.py`

**Validators:**
- `agent_actions/agents/validators/config_validator.py`
- `agent_actions/agents/validators/llm_context_utils.py`

**Migration:**
- `agent_actions/core/migration/format_migrator.py`

**Changes:**
```python
# Replace all occurrences:
SIDE_COLLECTION_KEY → OBSERVE_KEY
"side_collection" → "observe"
side_collection → observe

REMOVE_COLLECTION_KEY → DROPS_KEY
"remove_collection" → "drops"
remove_collection → drops

# Update method names:
transform_with_side_collection() → transform_with_observe()
apply_remove_collection() → apply_drops()
```

### Step 5: Update Tests
**Files affected (7 test files):**
- `tests/agents/validators/test_input_signature_validator.py`
- `tests/core/parser/test_action_expander_defaults.py`
- `tests/core/parser/test_action_expander_template_vars.py`
- `tests/core/utils/test_processor_helpers.py`
- `tests/integration/test_sequential_loop_integration.py`
- `tests/tasks/test_batch_service_filtering.py`
- `tests/tasks/test_batch_service_integration.py`

**Changes:**
```python
# Update test assertions
assert agent['observe'] == [...]  # Was: assert agent['side_collection']
assert result.get('drops') == []  # Was: assert result.get('remove_collection')
```

### Step 6: Remove Fallback Logic in Validators
**File:** `agent_actions/agents/validators/llm_context_utils.py`

**Changes:**
```python
# BEFORE (current bugfix with fallback)
observe = set(agent_config.get('observe', agent_config.get('side_collection', [])))
drops = set(agent_config.get('drops', agent_config.get('remove_collection', [])))

# AFTER (clean, single source of truth)
observe = set(agent_config.get('observe', []))
drops = set(agent_config.get('drops', []))
```

### Step 7: Update Documentation
**Update any internal docs/comments that reference:**
- `side_collection` → `observe`
- `remove_collection` → `drops`

## Testing Strategy

### Automated Testing
```bash
# Run full test suite
pytest tests/

# Specifically test validation
pytest tests/agents/validators/

# Test action expansion
pytest tests/core/parser/

# Integration tests
pytest tests/integration/
```

### Manual Verification
1. **Test workflow startup**: Verify configs load correctly
2. **Test field passthrough**: Verify `observe` fields pass through correctly
3. **Test field dropping**: Verify `drops` removes fields correctly
4. **Test validation**: Verify input signature validation still works
5. **Test batch mode**: Verify batch service handles fields correctly

### Regression Checklist
- [ ] All existing workflows load without errors
- [ ] Field passthrough works (observe functionality)
- [ ] Field removal works (drops functionality)
- [ ] Input signature validation works
- [ ] Output signature validation works (when implemented)
- [ ] Batch service processes observe/drops correctly
- [ ] Tool actions respect observe/drops
- [ ] LLM actions respect observe/drops

## Benefits

### 1. Consistency
- ✅ Same names in YAML, Pydantic models, and code
- ✅ No confusion about dual naming
- ✅ Easier to grep/search codebase

### 2. Maintainability
- ✅ Fewer edge cases to handle
- ✅ No fallback logic needed in validators
- ✅ Clearer code for new contributors

### 3. Fewer Bugs
- ✅ No risk of forgetting to check both names
- ✅ Validation logic is simpler
- ✅ Less error-prone

### 4. Better Documentation
- ✅ Docs can reference code directly
- ✅ No need to explain name mapping
- ✅ Clearer for developers

### 5. Code Quality
- ✅ Follows principle of least surprise
- ✅ Removes code smell
- ✅ Aligns with modern best practices

## Risk Assessment

### Low Risk Because:
1. **Internal only**: No user-facing API changes
2. **Comprehensive tests**: Full test suite will catch issues
3. **Automated**: Can use find/replace with high confidence
4. **Type-safe**: Pydantic models will catch any mismatches

### Potential Issues:
1. **Forgot to update a reference**: Test suite will catch this
2. **Third-party code**: None - this is internal to agent-actions
3. **Serialization issues**: Minimal - Pydantic handles field names transparently

### Mitigation:
- Run full test suite before merging
- Test with real workflows (qanalabs-quiz-gen, etc.)
- Review all changed files carefully
- Consider running in staging environment first

## Implementation Effort

**Estimated Time:** 4-6 hours

**Breakdown:**
- Search & replace: 1 hour
- Pydantic model updates: 30 minutes
- Constant updates: 15 minutes
- Method renames: 1 hour
- Test updates: 1 hour
- Validation & cleanup: 1-2 hours
- Testing & verification: 1 hour

**Complexity:** Medium
- Mostly mechanical find/replace
- Need to be careful with method names
- Test updates might reveal edge cases

## Related Work

- **Bugfix: Input signature validation** (current branch: `input-signature-fix`)
  - Added fallback logic to handle both names
  - This issue will remove the need for fallback logic

- **PR #430**: Input signature validation
  - Would be simpler with consistent naming

- **Issue #432**: Output signature validation
  - Will benefit from having consistent field names

- **PR #431**: Unified field referencing
  - Makes field names more prominent in user configs
  - Highlights the importance of consistent naming

## Migration Checklist

- [ ] Update Pydantic models (`side_collection`→`observe`, `remove_collection`→`drops`)
- [ ] Update constants (`SIDE_COLLECTION_KEY`→`OBSERVE_KEY`, etc.)
- [ ] Update ActionExpander field mapping
- [ ] Update all code references (28 files, ~190 occurrences)
- [ ] Rename methods (`transform_with_side_collection`→`transform_with_observe`)
- [ ] Update tests (7 test files)
- [ ] Remove fallback logic in validators
- [ ] Update docstrings and comments
- [ ] Run full test suite
- [ ] Test with real workflows
- [ ] Update any migration guides if they reference old names
- [ ] Remove deprecated constants in follow-up PR

## Success Criteria

✅ **Complete when:**
1. Zero occurrences of `side_collection` in codebase (except deprecation comments)
2. Zero occurrences of `remove_collection` in codebase (except deprecation comments)
3. All tests passing
4. Real workflows run successfully
5. Code is clearer and easier to understand

## Priority

**Medium**

This is a code quality improvement that:
- Reduces technical debt
- Makes future development easier
- Reduces bug potential
- Aligns with modern codebase standards

**Timing suggestion:**
- Do this **after** the input signature validation bugfix merges
- Do this **before** output signature validation (#432) implementation
- This will make #432 implementation cleaner

## Labels

- `refactor`
- `technical-debt`
- `good-first-issue` (mostly mechanical changes, clear requirements)
