# Fix for Data Nesting Issues in Agent Actions

## Overview

This document explains the fixes applied to resolve data nesting issues where structured data was being double-wrapped with `source_guid` and `content` fields, leading to problematic nested structures.

## The Problem

### Issue 1: Basic Record-Level Nesting
When data already had the correct structure with `source_guid` and `content` fields, the system would wrap it again, causing double nesting:

**Input:**
```json
{
  "source_guid": "74413538-b587-5655-9e0f-7edf00fade5e",
  "content": {
    "question_thinkific_loader": "data"
  }
}
```

**Problematic Output:**
```json
{
  "source_guid": "a1c448b2-5caa-5cb0-98f8-93eb1287fe13",
  "content": {
    "source_guid": "74413538-b587-5655-9e0f-7edf00fade5e",
    "content": {
      "question_thinkific_loader": "data"
    }
  }
}
```

### Issue 2: File-Level Tool Processing Not Bypassing Pipeline
For `model_vendor: "tool"` with `granularity: "file"`, the agent builder correctly bypassed transformation, but `process_file_level` was still running data through the transformation pipeline.

### Issue 3: Extra Array Wrapping
File-level processing was adding unnecessary array layers, resulting in `[[{...}]]` instead of `[{...}]`.

## The Solution

### Fix 1: Enhanced `transform_with_side_collection` (processor_utils.py)

**File:** `agent_actions/common/utils/processor_utils.py`

Added logic to detect already-structured data and prevent double-wrapping:

```python
# Check if data already has the correct structure
# (i.e., list of dicts with 'source_guid' and 'content' keys)
already_structured = (
    len(data) > 0 and
    all(
        isinstance(item, dict) and 
        'source_guid' in item and 
        'content' in item 
        for item in data
    )
)

side_collection = agent_config.get(SIDE_COLLECTION_KEY, [])

if already_structured and not side_collection:
    # Data already has correct structure, just ensure required fields
    output = data
elif side_collection:
    # Apply side_collection logic
    if already_structured:
        # Extract content from structured data for side_collection processing
        contents = [item['content'] for item in data]
        updated = [
            DataTransformer.update_schema_objects(context_data, content, side_collection)
            for content in contents
        ]
    else:
        updated = [
            DataTransformer.update_schema_objects(context_data, item, side_collection)
            for item in data
        ]
    output = DataTransformer.transform_structure([{source_guid: updated}])
else:
    # Apply transform_structure to ensure consistent output format
    output = DataTransformer.transform_structure([{source_guid: data}])
```

**What this does:**
- **Detects structured data**: Checks if all items have `source_guid` and `content` fields
- **Prevents double-wrapping**: If data is already structured and no `side_collection` is needed, returns it as-is
- **Handles side_collection**: When `side_collection` is present, extracts content from structured data
- **Backward compatibility**: Unstructured data still gets properly transformed

### Fix 2: File-Level Tool Bypass (target_content_processor.py)

**Files:** 
- `agent_actions/processors/target_processor/target_content_processor.py`
- `agent_actions/processors/content/target_content_processor.py`

Added bypass logic to `process_file_level` method to match the behavior in `agent_builder.py`:

```python
# For tool vendor with file granularity, return generated_data directly
# to match the bypass behavior in agent_builder.py
model_vendor = self.agent_config.get('model_vendor', '').lower()
granularity = self.agent_config.get('granularity', 'record').lower()

if model_vendor == 'tool' and granularity == 'file':
    # File-level tools should bypass the normal processing pipeline
    # If generated_data is already a list, return it directly
    # If it's a single item, wrap it in a list
    if isinstance(generated_data, list):
        return generated_data
    else:
        return [generated_data]

return self.data_processor.process_item(contents, generated_data, source_guid)
```

**What this does:**
- **Detects file-level tools**: Checks for `model_vendor == 'tool'` and `granularity == 'file'`
- **Bypasses transformation**: Returns tool output directly without running through `process_item`
- **Handles array wrapping**: Only wraps in array if the data isn't already a list
- **Maintains consistency**: Matches the bypass behavior already implemented in `agent_builder.py`

## Architecture Context

### File-Level Tool Processing Flow

1. **Target Generator** → `process_file_level()`
2. **process_file_level()** → `data_generator.create_agent_with_data()`
3. **create_agent_with_data()** → `agent_builder.create_dynamic_agent()`
4. **agent_builder** → Tool handler (bypasses transformation when `granularity == 'file'`)
5. **process_file_level()** → Now also bypasses transformation for file-level tools

### Configuration Rules

For `model_vendor: "tool"` with `granularity: "file"`:
- ❌ Cannot use `side_collection` (validated in config validator)
- ❌ Cannot use `remove_collection` (validated in config validator)  
- ✅ Tool output bypasses normal transformation pipeline
- ✅ Content is processed "wholesale" by the tool

## Testing the Fix

### Expected Behavior

**Input data with existing structure:**
```json
{
  "source_guid": "74413538-b587-5655-9e0f-7edf00fade5e",
  "content": {
    "question_thinkific_loader": "data"
  }
}
```

**Expected output (no double nesting):**
```json
{
  "source_guid": "74413538-b587-5655-9e0f-7edf00fade5e",
  "content": {
    "question_thinkific_loader": "data"
  }
}
```

**File-level tool output:**
```json
[
  {
    "source_guid": "74413538-b587-5655-9e0f-7edf00fade5e",
    "content": {
      "granularity": "file",
      "data": "processed content"
    }
  }
]
```

## Files Modified

1. **`agent_actions/common/utils/processor_utils.py`**
   - Enhanced `transform_with_side_collection()` method
   - Added detection for already-structured data
   - Added proper side_collection handling for structured data

2. **`agent_actions/processors/target_processor/target_content_processor.py`**
   - Modified `process_file_level()` method
   - Added file-level tool bypass logic

3. **`agent_actions/processors/content/target_content_processor.py`**
   - Modified `process_file_level()` method  
   - Added file-level tool bypass logic

## Key Insights

1. **Double transformation was the root cause**: Data was being transformed both in the agent builder and in the processor
2. **File-level tools should bypass the pipeline entirely**: This is the intended behavior but wasn't implemented consistently
3. **Structure detection is more robust than GUID matching**: Checking for the presence of required fields works better than comparing specific GUID values
4. **Side collection needs special handling**: When side_collection is present, we need to extract content from structured data before applying transformations

## Future Considerations

- **Monitoring**: Watch for any regressions in side_collection functionality
- **Testing**: Ensure both record-level and file-level processing work correctly
- **Documentation**: Update API docs to clarify file-level tool behavior
- **Validation**: Consider adding runtime validation for unexpected data structures

## Related Configuration

```yaml
# Example working configuration for file-level tools
model_vendor: "tool"
granularity: "file"
# side_collection: not allowed
# remove_collection: not allowed
```

```yaml
# Example working configuration for record-level processing  
model_vendor: "openai"  
granularity: "record"
side_collection: ["field1", "field2"]  # allowed
remove_collection: ["field3"]  # allowed
```