# Agent Actions Feature Roadmap

## Current Features Analysis

### ✅ Already Implemented
1. **Node Conditions** - WHERE clause filtering (secure implementation)
   - Item-level filtering with WHERE clauses
   - Secure AST-based evaluation
   - Production-ready with security tests
   - Location: `common/filters/`

2. **File-level Processing** - External function support
   - `granularity: file` configuration available
   - Tool vendor with file-level processing
   - Location: `target_processor/target_content_processor.py:204`

3. **Batch Processing** - Core functionality implemented
   - Multiple vendor support (OpenAI, Gemini, Anthropic)
   - Batch submission and retrieval
   - Context preservation
   - Location: `services/batch_service.py`, `providers/`

### 🚧 Partially Implemented (Need Enhancement)
1. **Unique ID Generation in Batch**
   - Current: Uses existing GUIDs 
   - Issue: "when we submit batch we are using existing guid which is not right"
   - Status: Patch exists but needs proper implementation

2. **Error Handling for Bad Records**
   - Current: Basic error handling exists
   - Issue: "handling when a single record is bad, output missing from schema"
   - Need: Graceful degradation for malformed outputs

## Feature Requests from Issue #293

### 1. Node Conditions Enhancement
**Request**: "conditions for each node so that we can define what we ant and what we dont"

**Current Status**: ✅ **IMPLEMENTED**
- WHERE clause filtering with secure evaluation
- Supports complex conditions at item level
- Example:
```yaml
where_clause:
  clause: "difficulty > 3 AND topic == 'Azure'"
  scope: "item"
```

**Recommendation**: No action needed - feature is complete and production-ready.

---

### 2. Function Recompilation Issue
**Request**: "Always having to define a function to recompile after breaking apart"

**Analysis**: This appears to be about function caching or module reloading during development.

**Current Status**: 🔍 **NEEDS INVESTIGATION**
- May be related to dynamic function loading in `core/tooling.py`
- Could affect tool vendor operations

**Proposed Solution**:
```python
# Add function cache invalidation
def invalidate_function_cache(module_name):
    if module_name in sys.modules:
        importlib.reload(sys.modules[module_name])
```

---

### 3. External Function Enhancement
**Request**: "external function that wont use normal data from workflow and improved file level application"

**Current Status**: 🚧 **PARTIALLY IMPLEMENTED**
- File-level processing exists (`granularity: file`)
- External functions via tool vendor supported
- Missing: Isolation from workflow data

**Proposed Enhancement**:
```python
# New configuration option
external_function:
  isolated: true  # Don't pass workflow context
  data_source: "direct"  # Use original input only
  granularity: "file"
```

---

### 4. Batch Copy/Paste Issue  
**Request**: "when applying batches i need to copy and paste"

**Current Status**: 🔍 **NEEDS CLARIFICATION**
- May refer to manual configuration copying
- Could be about batch result processing

**Proposed Solutions**:
1. **Batch Templates**: Reusable batch configurations
2. **Batch Inheritance**: Extend existing batch configs
3. **CLI Helper**: `agent batch copy <source> <target>`

---

### 5. Batch GUID Generation Issue
**Request**: "when we submit batch we are using existing guid which is not right"

**Current Status**: 🚧 **NEEDS FIX**
- Confirmed issue in codebase
- Patches exist but incomplete

**Root Cause**: 
```python
# Current problem in batch_service.py
custom_id = row.get("target_id")  # Uses existing ID
if not custom_id:
    custom_id = ProcessorUtils.generate_target_id()  # Only generates if missing
```

**Solution**: Force unique ID generation for batch mode
```python
# Proposed fix
if agent_config.get('run_mode') == 'batch':
    # Always generate fresh batch-specific IDs
    custom_id = f"batch_{ProcessorUtils.generate_target_id()}"
else:
    custom_id = row.get("target_id") or ProcessorUtils.generate_target_id()
```

---

### 6. Bad Record Handling
**Request**: "handling when a single record is bad, for example output is missing item from schema"

**Current Status**: 🚧 **NEEDS IMPLEMENTATION**
- Basic error handling exists but not granular
- Missing: Schema validation with fallbacks

**Proposed Solution**:
```python
class RecordRecoveryStrategy:
    def handle_bad_record(self, record, error, context):
        if error.type == "schema_validation":
            return self.apply_schema_defaults(record, error.missing_fields)
        elif error.type == "parsing_error":
            return self.create_error_placeholder(record, error)
        else:
            return self.skip_record(record, error)
```

## Priority Roadmap

### Sprint 1 (Immediate - 2 weeks)
1. **🔥 Fix Batch GUID Issue** (#5 above)
   - Implement proper unique ID generation for batch mode
   - Update tests to verify unique IDs
   - Estimated: 3 days

2. **📋 Bad Record Handling** (#6 above)  
   - Implement graceful schema validation failures
   - Add record recovery strategies
   - Estimated: 5 days

### Sprint 2 (Short term - 4 weeks)
3. **🔧 Function Recompilation Fix** (#2 above)
   - Investigate and fix caching issues
   - Add development mode with auto-reload
   - Estimated: 4 days

4. **🚀 Batch Experience Improvements** (#4 above)
   - Add batch templates and inheritance
   - Create CLI helpers for batch operations
   - Estimated: 6 days

### Sprint 3 (Medium term - 8 weeks)
5. **🔒 External Function Isolation** (#3 above)
   - Implement isolated execution mode
   - Add direct data source options
   - Enhanced file-level processing
   - Estimated: 8 days

### Future Considerations
- Advanced error recovery with ML-based correction
- Batch processing optimization for large datasets
- Visual batch configuration tools
- Integration with external workflow systems

## Implementation Notes

### Batch GUID Fix (Priority #1)
```python
def prepare_batch_tasks_from_data(self, agent_config, data):
    # ... existing code ...
    for row in data:
        if agent_config.get('run_mode') == 'batch':
            # Force unique batch ID generation
            custom_id = f"batch_{uuid.uuid4().hex}_{len(prepared_data)}"
            row["target_id"] = custom_id  # Update source data too
        else:
            custom_id = row.get("target_id") or ProcessorUtils.generate_target_id()
```

### Bad Record Handling (Priority #2)
```python
def validate_record_output(self, record, schema, recovery_strategy="default"):
    try:
        schema.validate(record)
        return ValidationResult(valid=True, record=record)
    except ValidationError as e:
        if recovery_strategy == "skip":
            return ValidationResult(valid=False, skipped=True)
        elif recovery_strategy == "fill_defaults":
            recovered = self.apply_schema_defaults(record, e.missing_fields)
            return ValidationResult(valid=True, record=recovered, recovered=True)
        else:  # "error_placeholder"
            error_record = {"error": str(e), "original": record}
            return ValidationResult(valid=True, record=error_record, error=True)
```

This roadmap addresses all requested features with clear priorities and implementation paths.