# Bug: File-Level Processing Missing source_content Parameter

## Issue Type
🐛 Bug

## Priority
High

## Affected Version
Current (main branch)

## Summary
File-level processing in `TargetContentProcessor.process_file_level()` fails to pass `source_content` to `create_agent_with_data()`, causing runtime errors when prompts use `{source.field}` references.

## Problem Statement

### User Impact
- Workflows fail at runtime with "Reference 'source' not found" error
- Only affects file-level processing (granularity: file)
- Record-level processing works correctly
- Blocks use of `{source.field}` pattern from Issue #429 in file-level tool actions

### Affected Workflows
- qanalabs-quiz-gen workflow - fact_questionability agent
- Any workflow using file-level granularity with `{source.field}` references in prompts

## Error Details

### Error Message
```
Error: Error during cli execution

Problem: Reference 'source' not found. Available: [flagged_items, cluster_id, should_keep_cluster, reasoning, page_content, bloom_details, exam_name, platform_name, url]

Context:
  agent_name: qanalabs-quiz-gen
  base_directory: .../node_4_create_new_clusters
  output_directory: .../node_5_fact_questionability
```

### Example Prompt That Fails
```markdown
{prompt fact_questionability}
## **Your Role**: MCQ Quality Evaluator

The decision should be based on the Bloom's taxonomy level: `{source.bloom_details}`
...
{end_prompt}
```

## Root Cause Analysis

### Where the Bug Is
**File:** `agent_actions/agents/generators/target_content_processor.py`
**Method:** `process_file_level()`
**Line:** 257

### The Problem
```python
# Current (BROKEN)
def process_file_level(self, data: List[Dict], output_directory: str = None) -> List[Dict]:
    ...
    try:
        contents, source_guid = data[0]['content'], data[0]['source_guid']
        generated_data, _ = self.data_generator.create_agent_with_data(data)  # ❌ Missing source_content
```

### Comparison with Working Code
Record-level processing correctly passes `source_content` (lines 497-500):

```python
# Record-level (WORKING)
def _process_item(self, item: Dict, source_data: List[Dict]) -> Optional[List[Dict]]:
    ...
    contents, source_guid = item['content'], item['source_guid']

    # Get corresponding source content
    source_content = DataTransformer.get_content_by_source_guid(source_data, source_guid)

    # Generate data with source_content
    generated_data, executed = self.data_generator.create_agent_with_data(
        contents, source_content  # ✅ Correctly passed
    )
```

### Why It Fails
1. `process_file_level()` calls `create_agent_with_data(data)` without `source_content` parameter
2. `DataGenerator._format_prompt()` builds `field_context` dict (lines 129-132):
   ```python
   field_context = {}
   if source_content:  # source_content is None!
       field_context['source'] = source_content
   ```
3. `field_context` has no 'source' key
4. `PromptUtils.resolve_field_reference()` tries to resolve `{source.bloom_details}`
5. Raises error: "Reference 'source' not found. Available: [...]"

## Technical Context

### Why This Was Not Caught Earlier
- Issue #429 (unified field referencing) added `{source.field}` pattern support
- Issue #430 (input signature validation) validates references at config load time
- **Validation passes** because `InputSignatureValidator` correctly treats 'source' as a special reference (lines 117-128)
- **Runtime fails** because `source_content` is not actually passed to prompt formatter

### Related Work
- **Issue #429:** Implemented `{source.field}` pattern - works for record-level, broken for file-level
- **Issue #430 / PR #435:** Input signature validation - correctly validates `{source.field}` as special reference
- **Bug introduced:** When file-level processing was implemented, it missed the `source_content` parameter

## Proposed Solution

### The Fix
Update `process_file_level()` to retrieve and pass `source_content`:

```python
def process_file_level(self, data: List[Dict], output_directory: str = None) -> List[Dict]:
    ...
    try:
        contents, source_guid = data[0]['content'], data[0]['source_guid']

        # Get source_data from loader (needed for {source.field} references)
        source_data = self.source_loader.load()
        source_content = DataTransformer.get_content_by_source_guid(source_data, source_guid)

        # Pass source_content to create_agent_with_data
        generated_data, _ = self.data_generator.create_agent_with_data(data, source_content)
        ...
```

### Why This Approach
1. **Consistent with record-level processing** - uses same pattern as `_process_item()` and `_process_item_async()`
2. **Minimal change** - only adds 3 lines of code
3. **No breaking changes** - `source_content` is already an optional parameter
4. **Fixes root cause** - ensures `field_context['source']` is populated

### Files to Change
- `agent_actions/agents/generators/target_content_processor.py` (lines 255-257)

## Testing Requirements

### Unit Tests Needed
Create test for file-level processing with source references:
```python
def test_process_file_level_with_source_reference():
    """Test that file-level processing passes source_content for {source.field} references."""
    agent_config = {
        'prompt': 'Process {source.title}',
        'granularity': 'file',
        'model_vendor': 'tool'
    }
    # Verify source_content is passed and {source.title} is resolved
```

### Integration Test
Verify qanalabs-quiz-gen workflow with `{source.bloom_details}` reference:
1. Run workflow through fact_questionability agent
2. Verify no "Reference 'source' not found" error
3. Verify prompt contains actual bloom_details value

### Regression Tests
- ✅ All existing field referencing tests must still pass
- ✅ Record-level processing with source references
- ✅ File-level processing without source references
- ✅ Input signature validation tests

## Verification Checklist
- [ ] Fix applied to `process_file_level()` method
- [ ] Unit test added for file-level source references
- [ ] All existing tests pass (no regressions)
- [ ] qanalabs-quiz-gen workflow runs successfully
- [ ] Error message no longer appears
- [ ] `{source.bloom_details}` correctly resolved in prompts

## Estimated Effort
- Fix: 5 minutes (3 lines of code)
- Testing: 30 minutes (add unit test, verify workflow)
- Total: ~1 hour

## Related Issues
- #429 - Implement Unified Field Referencing Pattern (dependency)
- #430 - Input Signature Validation (related validation)
- #435 - Fix Input Signature Validation for Pydantic Fields (PR that added validation)

## Dependencies
None - can be fixed immediately

## Notes
- This is a **runtime bug**, not a validation bug
- Validation correctly recognizes `{source.field}` as valid
- Only affects file-level processing; record-level already works
- Simple fix with high impact - unblocks file-level workflows using source references
