# Specification: Remove Input Validation from UDF Tools

**Status:** 📝 Proposed
**Created:** 2026-01-16
**Version:** 1.0

---

## Summary

Remove `input_type` requirement from UDF tools and eliminate runtime input validation. Make UDF actions work like LLM actions: `context_scope` defines input (guaranteed by progressive data exposure), `schema` defines output (validated at runtime).

---

## Motivation

### Current State: Triple Definition Problem

```yaml
# 1. Workflow defines data flow
- name: validate_question
  dependencies: [generate_question]
  context_scope:
    observe:
      - generate_question.question
      - generate_question.options
```

```python
# 2. Type annotation defines structure
class QuestionInput(TypedDict):
    question: str
    options: List[str]

# 3. Decorator requires input_type
@udf_tool(input_type=QuestionInput, output_type=ValidationResult)
def validate_question(data: QuestionInput):
    ...
```

**Problem**: Three places defining the same input structure.

### Desired State: Single Source of Truth

```yaml
# ONLY place defining input
- name: validate_question
  dependencies: [generate_question]
  context_scope:
    observe:
      - generate_question.question
      - generate_question.options
  schema_name: ValidationResult  # Output only
```

```python
# Only output schema needed
@udf_tool(output_schema="ValidationResult")
def validate_question(data: dict):
    # Input structure guaranteed by context_scope
    q = data["generate_question"]["question"]
    return {"valid": True}
```

---

## Key Insight: Context_Scope Already Validates Input

**Progressive data exposure guarantees:**

1. ✅ **Declared fields exist** - Runtime loads fields or fails
2. ✅ **Correct types** - Dependency schemas define field types
3. ✅ **No undeclared fields** - Only declared fields enter memory (security)
4. ✅ **Static validation** - Schema extractor validates context_scope refs

**Example:**
```yaml
context_scope:
  observe:
    - generate_question.question  # Must exist in generate_question schema
    - generate_question.options   # Type known from schema
```

If `generate_question` doesn't have `options` field → **static analysis error**.
If `generate_question` hasn't run yet → **runtime error** (dependency not satisfied).
If field exists → **guaranteed to be available** to UDF.

**Input validation is redundant.**

---

## Benefits

| Benefit | Description |
|---------|-------------|
| **Consistency** | UDF actions work exactly like LLM actions |
| **Single Source of Truth** | context_scope defines input for both action types |
| **Less Code** | No need to define input types/schemas |
| **Less Duplication** | Don't specify input structure twice |
| **Unified Schemas** | Both use `schema_name` pointing to external files |
| **Clearer Data Flow** | Look at workflow YAML to see what action receives |
| **Simpler Registration** | Only output schema required |

---

## Trade-offs

| Trade-off | Mitigation |
|-----------|-----------|
| **Loss of IDE type hints for input** | 1. Add type hints as comments<br>2. Use local type annotations<br>3. Generate stub files (future) |
| **No compile-time input validation** | Static analysis validates context_scope refs against schemas |
| **Manual namespace extraction** | Can add auto-flattening (future enhancement) |

---

## Implementation Steps

### Phase 1: Make input_type Optional (Backward Compatible)

#### 1.1 Update `udf_registry.py`

**Changes:**
- Make `input_type` parameter optional
- Add `output_schema` parameter (loads external schema file)
- Keep `output_type` as alternative
- Skip input schema derivation if `input_type` not provided

**File:** `/Users/muizz/Documents/codeshop/agent-actions/agent_actions/utilities/udf_management/udf_registry.py`

**Before (lines 87-93):**
```python
def udf_tool(
    func: Optional[Callable] = None,
    *,
    input_type: type,  # REQUIRED
    output_type: Optional[type] = None,
    granularity: Granularity = Granularity.RECORD,
) -> Callable:
```

**After:**
```python
def udf_tool(
    func: Optional[Callable] = None,
    *,
    input_type: Optional[type] = None,  # NOW OPTIONAL
    output_type: Optional[type] = None,
    output_schema: Optional[str] = None,  # NEW: Load from schema file
    granularity: Granularity = Granularity.RECORD,
) -> Callable:
    """
    Register a UDF with type-based or file-based schema.

    Args:
        func: The function to register
        input_type: Python type for input validation (OPTIONAL, deprecated)
        output_type: Python type for output validation
        output_schema: Schema file name for output validation (e.g., "ValidationResult")
        granularity: RECORD (default) or FILE processing

    At least one of output_type or output_schema must be provided.
    input_type is deprecated - use context_scope to define input.

    Examples:
        # New style: no input_type
        @udf_tool(output_schema="ValidationResult")
        def validate(data: dict):
            return {"valid": True}

        # Backward compatible: with input_type
        @udf_tool(input_type=QuestionInput, output_type=ValidationResult)
        def validate(data: QuestionInput):
            return {"valid": True}
    """
```

**Decorator logic changes (lines 127-191):**
```python
def decorator(f: Callable) -> Callable:
    # Derive input schema from type (if provided)
    resolved_schema = None
    if input_type is not None:
        resolved_schema = derive_schema_from_type(input_type)

    # Derive output schema
    resolved_output_schema = None
    if output_schema:
        # NEW: Load from schema file
        from agent_actions.response_processing.schema_loader import SchemaLoader
        # TODO: Get schema_dir from config or context
        schema_dir = Path.cwd() / "schema"
        try:
            loaded = SchemaLoader.load_schema(output_schema, schema_dir)
            resolved_output_schema = loaded
        except FileNotFoundError:
            raise ConfigurationError(
                f"Output schema file not found: {output_schema}",
                context={"schema_name": output_schema, "schema_dir": str(schema_dir)}
            )
    elif output_type is not None:
        resolved_output_schema = derive_schema_from_type(output_type)
    else:
        # No output validation - allowed but not recommended
        pass

    # Convert schemas to JSON Schema for validation
    json_schema = None
    if resolved_schema is not None:
        json_schema = unified_to_json_schema(resolved_schema)

    json_output_schema = None
    if resolved_output_schema is not None:
        json_output_schema = unified_to_json_schema(resolved_output_schema)

    # Store in registry
    with _registry_lock:
        func_name_lower = f.__name__.lower()

        # Check for duplicates (existing code)
        if func_name_lower in UDF_REGISTRY:
            # ... existing duplicate handling

        # Store with optional input schema
        UDF_REGISTRY[func_name_lower] = {
            "function": f,
            "module": f.__module__,
            "name": f.__name__,
            "file": inspect.getfile(f),
            "docstring": f.__doc__,
            "signature": inspect.signature(f),
            "input_type": input_type,  # May be None
            "output_type": output_type,  # May be None
            "output_schema_name": output_schema,  # NEW
            "schema": resolved_schema,  # May be None
            "output_schema": resolved_output_schema,
            "granularity": granularity,
            "json_schema": json_schema,  # May be None
            "json_output_schema": json_output_schema,
        }

    return f

# Remove the error that requires input_type (lines 185-190)
if func is not None:
    # Allow @udf_tool without arguments now
    return decorator(func)
return decorator
```

**Testing:**
- ✅ Old UDFs with `input_type` still work
- ✅ New UDFs without `input_type` work
- ✅ UDFs with `output_schema` load external files
- ✅ Error if both `output_type` and `output_schema` provided (ambiguous)

---

#### 1.2 Update `tooling.py` - Make Input Validation Optional

**Changes:**
- Skip input validation if no `json_schema` in registry
- Keep output validation
- Add warning log if skipping input validation

**File:** `/Users/muizz/Documents/codeshop/agent-actions/agent_actions/utilities/udf_management/tooling.py`

**Before (lines 122-124):**
```python
# Validate input if enabled
if validate_input:
    _validate_udf_input(udf_name, input_data, granularity, json_schema)
```

**After:**
```python
# Validate input if enabled AND schema exists
if validate_input and json_schema is not None:
    _validate_udf_input(udf_name, input_data, granularity, json_schema)
elif validate_input and json_schema is None:
    # Log info: input validation skipped (relying on context_scope)
    import logging
    logger = logging.getLogger(__name__)
    logger.debug(
        f"Skipping input validation for UDF '{udf_name}' "
        f"(no input_type defined, relying on context_scope)"
    )
```

**Testing:**
- ✅ UDFs without `input_type` execute without input validation
- ✅ UDFs with `input_type` still validate input
- ✅ Invalid input caught only if `input_type` defined

---

#### 1.3 Update `schema_extractor.py` - Infer from context_scope

**Changes:**
- For tool actions WITHOUT input schema in registry, infer from context_scope
- Parse `context_scope.observe` declarations
- Look up field types from dependency schemas
- Build input schema for static analysis

**File:** `/Users/muizz/Documents/codeshop/agent-actions/agent_actions/validation/static_analyzer/schema_extractor.py`

**New method (add after line 237):**
```python
def _infer_tool_input_from_context_scope(
    self,
    config: Dict[str, Any],
    input_schema: InputSchema,
) -> None:
    """
    Infer input schema from context_scope + dependency schemas.

    For UDFs without explicit input_type, the input structure is defined by
    context_scope.observe declarations. We can validate these references and
    extract field information from dependency schemas.

    Args:
        config: Action configuration with context_scope
        input_schema: InputSchema to populate
    """
    context_scope = config.get("context_scope", {})
    observe = context_scope.get("observe", [])

    if not observe:
        # No context_scope.observe - truly dynamic input
        input_schema.is_dynamic = True
        return

    # Parse field references
    for field_ref in observe:
        if not isinstance(field_ref, str):
            continue

        # Parse "dep_name.field_name" or "dep_name.*"
        if "." not in field_ref:
            # Invalid reference - log warning
            continue

        parts = field_ref.split(".", 1)
        dep_name = parts[0]
        field_path = parts[1] if len(parts) > 1 else "*"

        # Look up dependency schema
        if dep_name in self.schemas:
            dep_schema = self.schemas[dep_name]

            if field_path == "*":
                # Wildcard - all fields from dependency
                for field_name in dep_schema.schema_fields:
                    # Mark as required (guaranteed by context_scope)
                    input_schema.required_fields.add(f"{dep_name}.{field_name}")
            else:
                # Specific field
                if field_path in dep_schema.schema_fields:
                    input_schema.required_fields.add(field_ref)
                else:
                    # Field not in schema - validation error
                    # Static analysis should catch this
                    pass

    # If we extracted fields, mark as context-derived
    if input_schema.required_fields:
        input_schema.is_dynamic = False
        input_schema.derived_from_context_scope = True  # NEW flag
```

**Update `_extract_tool_input_schema` (lines 198-237):**
```python
def _extract_tool_input_schema(
    self,
    config: Dict[str, Any],
    input_schema: InputSchema,
) -> None:
    """Extract input schema from tool/UDF agent using impl field."""
    impl = config.get("impl") or config.get("model_name") or ""

    # Try to get schema from Python files via scanner
    if impl:
        tool_schemas = self._get_tool_schemas()
        if impl in tool_schemas:
            tool_info = tool_schemas[impl]
            tool_input_schema = tool_info.get("input_schema")
            if tool_input_schema and tool_input_schema.get("fields"):
                json_schema = self._convert_fields_to_json_schema(tool_input_schema["fields"])
                input_schema.json_schema = json_schema
                self._extract_input_fields_from_json_schema(json_schema, input_schema)
                return

    # Try UDF registry (for backward compatibility with input_type)
    impl_key = impl.lower() if impl else ""
    if impl_key and impl_key in self.udf_registry:
        udf_info = self.udf_registry[impl_key]
        json_schema = udf_info.get("json_schema")
        if json_schema:  # May be None now
            input_schema.json_schema = json_schema
            self._extract_input_fields_from_json_schema(json_schema, input_schema)
            return

    # Check for inline input_schema
    schema_def = config.get("input_schema")
    if schema_def and isinstance(schema_def, dict):
        input_schema.json_schema = schema_def
        self._extract_input_fields_from_json_schema(schema_def, input_schema)
        return

    # NEW: Infer from context_scope if no explicit schema
    self._infer_tool_input_from_context_scope(config, input_schema)
```

**Add field to InputSchema class:**
```python
@dataclass
class InputSchema:
    """Schema information for action input."""
    required_fields: Set[str] = field(default_factory=set)
    optional_fields: Set[str] = field(default_factory=set)
    json_schema: Optional[Dict[str, Any]] = None
    is_dynamic: bool = False
    derived_from_context_scope: bool = False  # NEW
```

**Testing:**
- ✅ Static analysis extracts fields from context_scope
- ✅ Field references validated against dependency schemas
- ✅ Warnings for invalid field references
- ✅ Field flow analysis works with context-derived schemas

---

### Phase 2: Deprecation Warnings (Prepare for Removal)

#### 2.1 Add Deprecation Warning for input_type

**File:** `udf_registry.py`

```python
def decorator(f: Callable) -> Callable:
    if input_type is not None:
        import warnings
        warnings.warn(
            f"input_type parameter in @udf_tool is deprecated for '{f.__name__}'. "
            f"Use context_scope to define input instead. "
            f"input_type will be removed in v2.0.0.",
            DeprecationWarning,
            stacklevel=2
        )
    # ... rest of decorator
```

#### 2.2 Update Documentation

**Files to update:**
- `/Users/muizz/Documents/codeshop/agent-actions/docs/guides/udf_tools.md`
- `/Users/muizz/Documents/codeshop/agent-actions/README.md`
- Example workflows in `tests/` and sample projects

**Changes:**
- Show new decorator signature without `input_type`
- Explain context_scope as input definition
- Add migration guide from old to new style
- Document when to use optional type hints (complex UDFs)

**Example documentation:**

```markdown
## Defining UDF Tools

### New Style (Recommended)

```yaml
# workflow.yml
- name: validate_question
  kind: tool
  impl: validate_question_func
  dependencies: [generate_question]
  context_scope:
    observe:
      - generate_question.question
      - generate_question.options
  schema_name: ValidationResult
```

```python
# tools/validate.py
@udf_tool(output_schema="ValidationResult")
def validate_question_func(data: dict) -> dict:
    """
    Validate a generated question.

    Input (from context_scope):
        generate_question.question: str
        generate_question.options: List[str]
    """
    q_data = data["generate_question"]
    return {
        "valid": len(q_data["options"]) >= 3,
        "score": 0.95
    }
```

### Old Style (Deprecated)

```python
class QuestionInput(TypedDict):
    question: str
    options: List[str]

@udf_tool(input_type=QuestionInput, output_type=ValidationResult)
def validate_question_func(data: QuestionInput) -> ValidationResult:
    return {"valid": True}
```

**Why the change?**
- context_scope already defines what data flows in
- No need to duplicate input structure in code
- Consistent with LLM actions
- Less boilerplate

**When to use type hints:**
For complex UDFs, you can still use local type annotations:
```python
@udf_tool(output_schema="Result")
def complex_func(data: dict) -> dict:
    q_data: QuestionData = data["generate_question"]  # Local hint
    # IDE now helps with q_data structure
```
```

---

### Phase 3: Remove input_type (Breaking Change - v2.0.0)

#### 3.1 Remove input_type Parameter

**File:** `udf_registry.py`

```python
def udf_tool(
    func: Optional[Callable] = None,
    *,
    output_type: Optional[type] = None,
    output_schema: Optional[str] = None,
    granularity: Granularity = Granularity.RECORD,
) -> Callable:
    """
    Register a UDF with output schema validation.

    Input structure is defined by context_scope in workflow YAML.
    Only output validation is performed at runtime.
    """
    # ... decorator with no input_type handling
```

#### 3.2 Remove Input Validation

**File:** `tooling.py`

```python
def execute_user_defined_function(
    udf_name: str,
    input_data: Union[Dict[str, Any], List[Any]],
    validate_output: bool = True,  # Remove validate_input parameter
    **kwargs: Any,
) -> Any:
    """Execute UDF with output validation only."""
    from agent_actions.utilities.udf_management.udf_registry import get_udf_metadata

    metadata = get_udf_metadata(udf_name)
    udf = metadata["function"]
    granularity = metadata["granularity"]
    json_output_schema = metadata.get("json_output_schema")

    # NO INPUT VALIDATION - context_scope guarantees input structure

    # Execute function
    try:
        result = udf(input_data, **kwargs)
    except Exception as e:
        raise AgentActionsException(
            f"Error executing UDF '{udf_name}': {safe_format_error(e)}",
            context={
                "function": udf_name,
                "operation": "execute_udf",
                "granularity": granularity.value,
            },
            cause=e,
        ) from e

    # Validate output
    if validate_output and json_output_schema is not None:
        _validate_udf_output(udf_name, result, granularity, json_output_schema)

    return result
```

#### 3.3 Update Tests

**Files:**
- All test files using `@udf_tool` with `input_type`
- Update to use `output_schema` or `output_type` only
- Verify context_scope defines required fields

**Example test update:**

**Before:**
```python
class TestInput(TypedDict):
    value: int

@udf_tool(input_type=TestInput, output_type=dict)
def test_func(data: TestInput):
    return {"result": data["value"] * 2}

# Test
result = execute_user_defined_function("test_func", {"value": 5})
```

**After:**
```python
@udf_tool(output_type=dict)
def test_func(data: dict):
    return {"result": data["value"] * 2}

# Test (context_scope would provide this structure)
result = execute_user_defined_function("test_func", {"value": 5})
```

---

## Migration Guide

### For Existing Codebases

**Step 1: Update UDF Decorators**

```python
# Before
@udf_tool(input_type=MyInput, output_type=MyOutput)
def my_func(data: MyInput) -> MyOutput:
    return {"result": "..."}

# After
@udf_tool(output_type=MyOutput)
def my_func(data: dict) -> dict:
    return {"result": "..."}
```

**Step 2: Verify context_scope**

Ensure workflow YAML declares all fields the UDF needs:

```yaml
context_scope:
  observe:
    - dependency.field1
    - dependency.field2
```

**Step 3: Add Type Hints (Optional)**

For complex UDFs, add local type hints:

```python
@udf_tool(output_type=MyOutput)
def my_func(data: dict) -> dict:
    input_data: MyInput = data["dependency"]  # Local hint
    return process(input_data)
```

**Step 4: Update Tests**

Remove input validation assertions, rely on context_scope validation.

---

## Testing Strategy

### Unit Tests

**Test File:** `tests/utilities/udf_management/test_udf_registry_no_input.py`

```python
def test_udf_without_input_type():
    """UDF can be registered without input_type."""
    @udf_tool(output_schema="Result")
    def test_func(data: dict):
        return {"value": 42}

    metadata = get_udf_metadata("test_func")
    assert metadata["json_schema"] is None
    assert metadata["json_output_schema"] is not None

def test_udf_with_input_type_still_works():
    """Backward compatibility: input_type still works."""
    class TestInput(TypedDict):
        value: int

    @udf_tool(input_type=TestInput, output_type=dict)
    def test_func(data: TestInput):
        return {"result": data["value"]}

    metadata = get_udf_metadata("test_func")
    assert metadata["json_schema"] is not None
    assert metadata["json_output_schema"] is not None

def test_output_schema_loads_file(tmp_path):
    """output_schema loads external schema file."""
    schema_dir = tmp_path / "schema"
    schema_dir.mkdir()

    schema_file = schema_dir / "Result.yml"
    schema_file.write_text("""
name: Result
fields:
  - id: value
    type: integer
    required: true
""")

    # Mock schema_dir in decorator
    @udf_tool(output_schema="Result")
    def test_func(data: dict):
        return {"value": 42}

    metadata = get_udf_metadata("test_func")
    assert metadata["output_schema_name"] == "Result"
```

### Integration Tests

**Test File:** `tests/integration/test_udf_no_input_validation.py`

```python
def test_udf_executes_without_input_validation():
    """UDF without input_type executes successfully."""
    @udf_tool(output_type=dict)
    def test_func(data: dict):
        return {"result": data["value"] * 2}

    result = execute_user_defined_function(
        "test_func",
        {"value": 5},
        validate_input=True  # Should not fail
    )
    assert result["result"] == 10

def test_udf_validates_output():
    """Output validation still works."""
    class Output(TypedDict):
        result: int

    @udf_tool(output_type=Output)
    def test_func(data: dict):
        return {"result": "not_an_int"}  # Invalid

    with pytest.raises(SchemaValidationError):
        execute_user_defined_function("test_func", {"value": 5})
```

### Static Analysis Tests

**Test File:** `tests/validation/test_context_scope_inference.py`

```python
def test_schema_extractor_infers_from_context_scope():
    """Schema extractor infers input fields from context_scope."""
    config = {
        "kind": "tool",
        "impl": "test_func",
        "context_scope": {
            "observe": [
                "dep1.field1",
                "dep1.field2",
                "dep2.field3"
            ]
        }
    }

    # Mock dependency schemas
    schemas = {
        "dep1": MockSchema(fields={"field1", "field2"}),
        "dep2": MockSchema(fields={"field3"})
    }

    extractor = SchemaExtractor(schemas=schemas, udf_registry={})
    input_schema = extractor.extract_input_schema(config)

    assert "dep1.field1" in input_schema.required_fields
    assert "dep1.field2" in input_schema.required_fields
    assert "dep2.field3" in input_schema.required_fields
    assert input_schema.derived_from_context_scope
```

---

## Files to Modify

| File | Lines | Changes |
|------|-------|---------|
| `agent_actions/utilities/udf_management/udf_registry.py` | 87-191 | Make input_type optional, add output_schema |
| `agent_actions/utilities/udf_management/tooling.py` | 122-124 | Skip input validation if no schema |
| `agent_actions/validation/static_analyzer/schema_extractor.py` | 198-237 | Infer input from context_scope |
| `agent_actions/validation/static_analyzer/schemas.py` | - | Add derived_from_context_scope flag |
| `docs/guides/udf_tools.md` | - | Update documentation |
| `tests/utilities/udf_management/test_udf_registry.py` | - | Add tests for optional input_type |
| `tests/integration/test_udf_execution.py` | - | Add tests for no input validation |
| All sample projects (`qanalabs_quiz_gen/`, etc.) | - | Update UDF decorators |

---

## Rollout Plan

### Stage 1: Phase 1 (Week 1)
- Implement backward-compatible changes
- Make input_type optional
- Add output_schema support
- Update schema_extractor to infer from context_scope
- Add unit tests

**Risk:** Low (backward compatible)

### Stage 2: Phase 2 (Week 2)
- Add deprecation warnings
- Update documentation
- Update sample projects
- Communicate to users

**Risk:** Low (warnings only)

### Stage 3: Phase 3 (Week 4-6)
- Remove input_type parameter (v2.0.0)
- Remove input validation entirely
- Update all tests
- Major version release

**Risk:** Medium (breaking change, requires user migration)

---

## Success Criteria

1. ✅ UDFs can be registered without `input_type`
2. ✅ UDFs with `output_schema` load external schema files
3. ✅ Input validation skipped if no `input_type` defined
4. ✅ Static analysis infers input fields from `context_scope`
5. ✅ Backward compatibility: old UDFs still work
6. ✅ Deprecation warnings shown for `input_type`
7. ✅ Documentation updated
8. ✅ All tests pass
9. ✅ Sample projects updated

---

## Open Questions

### Q1: How to handle schema_dir in udf_registry?

**Problem:** `output_schema` needs schema_dir to load files, but decorator doesn't have access to project paths.

**Options:**
1. **Lazy loading**: Load schema at first execution, not registration
2. **Global config**: Store schema_dir in global settings
3. **Require full path**: `output_schema="/path/to/schema/Result.yml"`
4. **Defer to runtime**: Store schema name, load in `execute_user_defined_function`

**Recommendation:** Option 4 (defer to runtime)

```python
# At registration (decorator)
UDF_REGISTRY[func_name_lower] = {
    "output_schema_name": output_schema,  # Just store name
    # Don't load file yet
}

# At execution (tooling.py)
def execute_user_defined_function(udf_name, input_data, schema_dir, **kwargs):
    metadata = get_udf_metadata(udf_name)

    if metadata.get("output_schema_name"):
        schema_name = metadata["output_schema_name"]
        loaded = SchemaLoader.load_schema(schema_name, schema_dir)
        json_output_schema = unified_to_json_schema(loaded)
    else:
        json_output_schema = metadata.get("json_output_schema")
```

### Q2: Should we support schema_name in workflow YAML for tools?

**Current LLM actions:**
```yaml
- name: generate_question
  kind: llm
  schema_name: Question  # Loads schema/Question.yml
```

**Should tool actions support this too?**
```yaml
- name: validate_question
  kind: tool
  impl: validate_func
  output_schema: ValidationResult  # NEW: Loads schema/ValidationResult.yml
```

**Recommendation:** Yes, for consistency

Update `action_expander.py` to pass `output_schema` from config to runtime.

### Q3: Granularity and context flattening?

**Current:** UDFs receive full context dict with namespaces.

**Future enhancement:** Auto-flatten for RECORD granularity?

```yaml
- name: process
  kind: tool
  impl: process_func
  granularity: Record
  context_scope:
    observe: [dep1.field1, dep2.field2]
  flatten_context: true  # NEW option
```

```python
# Without flatten
data = {"dep1": {"field1": "..."}, "dep2": {"field2": "..."}}

# With flatten
data = {"field1": "...", "field2": "..."}
```

**Recommendation:** Out of scope for this spec, consider for future enhancement.

---

## Related Documents

- [RFC: Simplified Dependency Model](./RFC_simplified_dependency_model.md)
- [SPEC: Auto-Inferred Context Dependencies](./SPEC_auto_inferred_context_dependencies.md)
- [Progressive Data Exposure](../design/PROGRESSIVE_DATA_EXPOSURE.md)
- [UDF Tools Guide](../guides/udf_tools.md)

---

## Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-01-16 | Claude | Initial specification |
