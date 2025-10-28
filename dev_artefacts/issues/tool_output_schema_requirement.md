# Issue #484: Require Output Schema for Tool Actions

**Status:** Proposed
**Priority:** Medium
**Type:** Enhancement / Breaking Change
**Date Created:** 2025-10-28
**GitHub Issue:** https://github.com/Muizzkolapo/agent-actions/issues/484
**Related To:** Context Scope Passthrough Implementation

## Problem Statement

Currently, tool actions (agents with `model_vendor: tool` or `kind: tool`) are not required to define an output schema. This creates several issues:

1. **Implicit Field Discovery**: The system must guess or discover what fields a tool produces by examining actual output
2. **Workaround Complexity**: Special fallback logic loads ALL fields when no schema exists, which is inefficient
3. **Poor Developer Experience**: Users don't know what fields a tool produces without running it
4. **Context Scope Ambiguity**: `context_scope` filtering cannot validate field names at config time
5. **Maintenance Burden**: The fallback logic adds complexity and edge cases

## Current Workaround

In `data_generator.py:357-378`, we implemented a workaround:

```python
if dep_output_fields:
    # Schema exists - only load specified fields
    for field in dep_output_fields:
        if field in contents:
            dep_fields[field] = contents[field]
else:
    # No schema - load all fields from contents (for tools without schemas)
    # ⚠️ WORKAROUND: This allows context_scope to filter them
    dep_fields = contents.copy() if isinstance(contents, dict) else {}
```

This works but is inefficient (loads all fields then filters) and prevents early validation.

## Proposed Solution

**Require all tool actions to define an output schema** that describes the structure of fields in `content` dict.

### Schema Format

Tools should define schemas just like LLM agents:

```yaml
- name: group_by_similarity
  kind: tool
  impl: group_by_similarity
  granularity: file
  schema: group_similarity_output  # String reference
  # OR
  output_schema:  # Inline dict
    properties:
      similarity_group_id:
        type: string
        description: "Unique ID for this similarity group"
      grouped_facts:
        type: array
        description: "Facts grouped by similarity"
      num_similar_facts:
        type: integer
        description: "Count of facts in this group"
```

### What the Schema Describes

The schema describes the **contents of the `content` dict** in the tool's output records:

```json
{
  "source_guid": "...",
  "target_id": "...",
  "node_id": "...",
  "lineage": [],
  "content": {
    // ⬇️ Schema describes these fields
    "similarity_group_id": "SG1",
    "grouped_facts": [...],
    "num_similar_facts": 5
  }
}
```

## Implementation Plan

### Phase 1: Add Warnings (Non-Breaking)

1. Update schema validation to emit warnings when tools lack schemas
2. Add logging: `"Tool '{tool_name}' has no output schema. This will be required in future versions."`
3. Update documentation to strongly recommend schemas for tools
4. Keep existing fallback logic in place

### Phase 2: Documentation & Migration

1. Document schema requirements in tool development guide
2. Add examples for common tool output patterns
3. Provide migration guide for existing tools
4. Create schemas for all built-in tools

### Phase 3: Enforcement (Breaking Change)

1. Update `LLMContextUtils.compute_llm_context()` to raise error if tool has no schema
2. Remove fallback logic from `_build_namespaced_field_context()`
3. Update config validation to reject tool configs without schemas
4. Release with major version bump

## Benefits

### 1. **Explicit Contracts**

Tools declare what they produce:
```yaml
- name: data_enricher
  kind: tool
  schema: enriched_data
  # Clear: This tool produces a field called 'enriched_data'
```

### 2. **Early Validation**

Config validation can check:
```yaml
- name: consumer
  dependencies: [data_enricher]
  context_scope:
    passthrough:
      data_enricher: [invalid_field]  # ❌ Error at config parse time!
```

### 3. **Better Performance**

Only load requested fields:
```python
# With schema: Load only what's needed
for field in dep_output_fields:  # ['similarity_group_id']
    if field in contents:
        dep_fields[field] = contents[field]

# Without schema: Load everything then filter (wasteful)
dep_fields = contents.copy()  # All fields
```

### 4. **Auto-Documentation**

Generate docs from schemas:
```
Tool: group_by_similarity
Outputs:
  - similarity_group_id (string): Unique ID for similarity group
  - grouped_facts (array): Facts grouped by similarity
  - num_similar_facts (integer): Count of facts in group
```

### 5. **Simpler Codebase**

Remove fallback logic, special cases, and workarounds.

## Migration Path

### For Users

**Step 1:** Identify tools without schemas
```bash
grep -A5 "kind: tool" *.yml | grep -L "schema:"
```

**Step 2:** Add schemas based on actual output
```yaml
# Before
- name: my_tool
  kind: tool
  impl: my_tool

# After
- name: my_tool
  kind: tool
  impl: my_tool
  schema: my_tool_output  # Add this
```

**Step 3:** Define schema in schema directory
```yaml
# schemas/my_tool_output.yml
properties:
  field1:
    type: string
  field2:
    type: integer
```

### For Tool Developers

**Include schema in tool metadata:**

```python
# tools/my_tool.py

def my_tool_metadata():
    """Return tool metadata including output schema."""
    return {
        "name": "my_tool",
        "output_schema": {
            "properties": {
                "result": {"type": "string"},
                "confidence": {"type": "number"}
            }
        }
    }

def my_tool(data):
    """Execute tool."""
    return {
        "result": "...",
        "confidence": 0.95
    }
```

## Backward Compatibility

### Option A: Hard Requirement (Breaking)

- **Version:** 2.0.0
- **Change:** Tools without schemas fail validation
- **Timeline:** 6 months notice via warnings

### Option B: Soft Requirement (Gradual)

- **Version:** 1.x
- **Change:** Warnings only, keep fallback
- **Version:** 2.0.0
- **Change:** Hard requirement

**Recommendation:** Option B (gradual)

## Code Changes Required

### 1. Config Validation

**File:** `agent_actions/response_processing/config_schema.py`

```python
@model_validator(mode='after')
def validate_tool_schema(self) -> 'AgentConfig':
    """Validate that tools have output schemas."""
    model_vendor = (self.model_vendor or '').lower()
    kind = (self.kind or '').lower()

    is_tool = model_vendor == 'tool' or kind == 'tool'
    has_schema = bool(self.schema or self.schema_name or self.output_schema)

    if is_tool and not has_schema:
        # Phase 1: Warning
        logger.warning(
            f"Tool '{self.name}' has no output schema. "
            "This will be required in future versions. "
            "Add 'schema' or 'output_schema' to the config."
        )

        # Phase 3: Error (uncomment after migration period)
        # raise ValueError(
        #     f"Tool '{self.name}' must define an output schema. "
        #     f"Add 'schema: schema_name' or 'output_schema: {{properties: ...}}'"
        # )

    return self
```

### 2. Remove Fallback Logic

**File:** `agent_actions/prompt_generation/data_generator.py`

After migration period, remove lines 363-366 and 376-378:

```python
# Remove these after Phase 3:
else:
    # No schema - load all fields from contents (for tools without schemas)
    # This allows context_scope to filter them
    dep_fields = contents.copy() if isinstance(contents, dict) else {}
```

### 3. Update Documentation

**Files to update:**
- `docs/tool_development.md` - Add schema requirements
- `docs/context_scope.md` - Update examples to include tool schemas
- `docs/migration_guide.md` - Add tool schema migration section
- `README.md` - Update tool examples

## Testing Requirements

### 1. Validation Tests

```python
def test_tool_without_schema_emits_warning():
    """Tool without schema should emit warning (Phase 1)."""
    config = {
        "name": "test_tool",
        "kind": "tool",
        "impl": "test_tool"
        # No schema
    }

    with pytest.warns(UserWarning, match="has no output schema"):
        AgentConfig(**config)

def test_tool_without_schema_raises_error():
    """Tool without schema should raise error (Phase 3)."""
    config = {
        "name": "test_tool",
        "kind": "tool",
        "impl": "test_tool"
        # No schema
    }

    with pytest.raises(ValueError, match="must define an output schema"):
        AgentConfig(**config)
```

### 2. Integration Tests

```python
def test_tool_with_schema_loads_only_declared_fields():
    """Tool with schema should only load declared fields."""
    # Tool declares: schema with [field1, field2]
    # Contents has: {field1, field2, field3}
    # Should load: {field1, field2} only

def test_context_scope_validates_against_schema():
    """Context scope should validate field names against schema."""
    # Tool schema: {similarity_group_id}
    # Context scope: passthrough: [invalid_field]
    # Should: Raise validation error at config time
```

## Risks & Mitigations

### Risk 1: Breaking Existing Workflows

**Impact:** Users with schema-less tools will see errors
**Mitigation:**
- Long warning period (6 months)
- Clear error messages with examples
- Migration scripts to auto-generate basic schemas
- Backward compatibility mode via feature flag

### Risk 2: Schema Maintenance Burden

**Impact:** Tool developers must maintain schemas
**Mitigation:**
- Tools can auto-generate schemas from output inspection
- Schema validation optional in dev mode
- Simple schema format (just field names + types)

### Risk 3: Schema Drift

**Impact:** Tool output changes but schema not updated
**Mitigation:**
- Runtime validation warns on extra fields
- Test utilities to compare schema vs actual output
- Schema versioning support

## Success Metrics

1. **Coverage:** 100% of tools have schemas after migration
2. **Performance:** 20-30% reduction in field loading overhead
3. **Errors:** 80% reduction in "field not found" runtime errors
4. **DX:** User surveys show improved tool discoverability

## Related Issues

- Context Scope Passthrough Implementation (current)
- Field Discovery & Validation (#TBD)
- Tool Development Guidelines (#TBD)

## References

- `agent_actions/prompt_generation/data_generator.py:357-378` - Current workaround
- `agent_actions/validation/llm_context_utils.py:20-71` - Schema computation
- `dev_artefacts/implementations/context_scope_passthrough_consolidation/` - Context scope docs

## Decision

- [ ] Approved for implementation
- [ ] Needs discussion
- [ ] Postponed
- [ ] Rejected

**Next Steps:**
1. Review with team
2. Decide on migration timeline (Option A vs B)
3. Create Phase 1 implementation ticket
4. Document tool schema format
5. Audit existing tools for schema compliance
