# Implementation Plan: Type Hint Support & Output Validation

## Overview

Add `input_type`/`output_type` parameters to `@udf_tool` decorator, supporting TypedDict, Pydantic, and dataclasses.

---

## Phase 1: Type Hint Derivation (Core Feature)

### Files to Modify
- [agent_actions/utilities/udf_management/udf_registry.py](file:///Users/muizz/Documents/codeshop/agent-actions/agent_actions/utilities/udf_management/udf_registry.py)

### Implementation Steps

#### Step 1.1: Add Optional Dependency Detection
```python
# In udf_registry.py - top of file

import dataclasses
import sys
from typing import (
    Any, Dict, get_type_hints, get_origin, get_args,
    Union, Optional as TypingOptional
)

# Optional Pydantic support
try:
    from pydantic import BaseModel
    HAS_PYDANTIC = True
except ImportError:
    HAS_PYDANTIC = False
    BaseModel = None

# TypedDict detection (Python 3.10+ has is_typeddict, fallback for 3.9)
if sys.version_info >= (3, 10):
    from typing import is_typeddict
else:
    def is_typeddict(tp) -> bool:
        """Check if a type is a TypedDict (Python 3.9 compatible)."""
        return (
            hasattr(tp, '__annotations__') and
            hasattr(tp, '__total__') and
            hasattr(tp, '__required_keys__') and
            not dataclasses.is_dataclass(tp) and
            not (HAS_PYDANTIC and isinstance(tp, type) and issubclass(tp, BaseModel))
        )
```

#### Step 1.2: Add Type Detection Helper
```python
def _unwrap_annotated(py_type) -> Any:
    """Strip Annotated wrapper if present."""
    origin = get_origin(py_type)
    if origin is not None:
        # Check for Annotated (typing.Annotated or typing_extensions.Annotated)
        if getattr(origin, '__name__', None) == 'Annotated':
            args = get_args(py_type)
            return args[0] if args else py_type
    return py_type


def _python_type_to_schema_type(py_type) -> str:
    """Convert Python type to JSON Schema type string."""
    # Unwrap Annotated first
    py_type = _unwrap_annotated(py_type)

    origin = get_origin(py_type)

    # Handle Optional[T] -> T (nullable handled separately)
    if origin is Union:
        args = get_args(py_type)
        non_none_args = [a for a in args if a is not type(None)]
        if len(non_none_args) == 1:
            return _python_type_to_schema_type(non_none_args[0])
        # For Union[A, B, ...], default to string (complex unions need explicit handling)
        return 'string'

    if origin is list:
        return 'array'
    if origin is dict:
        return 'object'

    # Use 'integer' for int (JSON Schema distinguishes int from float)
    type_mapping = {
        str: 'string',
        int: 'integer',
        float: 'number',
        bool: 'boolean',
        list: 'array',
        dict: 'object',
        type(None): 'null'
    }

    return type_mapping.get(py_type, 'string')


def _is_optional_type(py_type) -> bool:
    """Check if type is Optional[T] (Union[T, None])."""
    py_type = _unwrap_annotated(py_type)
    origin = get_origin(py_type)
    if origin is Union:
        args = get_args(py_type)
        return type(None) in args
    return False
```

#### Step 1.3: Add TypedDict Support
```python
def _derive_schema_from_typeddict(type_hint) -> Dict[str, Any]:
    """Derive schema from TypedDict."""
    fields = []
    annotations = type_hint.__annotations__

    # Get required keys (Python 3.9+)
    required_keys = getattr(type_hint, '__required_keys__', set(annotations.keys()))

    for field_name, field_type in annotations.items():
        # Unwrap Annotated if present
        unwrapped_type = _unwrap_annotated(field_type)

        field_schema = {
            'id': field_name,
            'type': _python_type_to_schema_type(unwrapped_type),
            'required': field_name in required_keys and not _is_optional_type(unwrapped_type)
        }

        # Handle List[T]
        origin = get_origin(unwrapped_type)
        if origin is list:
            args = get_args(unwrapped_type)
            if args:
                field_schema['items'] = {'type': _python_type_to_schema_type(args[0])}

        # Handle Dict[K, V]
        elif origin is dict:
            args = get_args(unwrapped_type)
            if len(args) == 2:
                field_schema['additionalProperties'] = {'type': _python_type_to_schema_type(args[1])}

        # Handle nested TypedDict
        elif is_typeddict(unwrapped_type):
            nested_schema = _derive_schema_from_typeddict(unwrapped_type)
            field_schema['type'] = 'object'
            field_schema['properties'] = {f['id']: f for f in nested_schema['fields']}

        fields.append(field_schema)

    return {
        'name': type_hint.__name__,
        'fields': fields
    }
```

#### Step 1.4: Add Pydantic Support
```python
def _derive_schema_from_pydantic(type_hint) -> Dict[str, Any]:
    """Derive schema from Pydantic model."""
    if not HAS_PYDANTIC:
        raise ValueError("Pydantic is not installed. Install with: pip install pydantic")

    if not hasattr(type_hint, 'model_json_schema'):
        raise ValueError(f"{type_hint} is not a Pydantic v2 model")

    # Pydantic provides JSON schema
    json_schema = type_hint.model_json_schema()

    # Convert to unified format
    return _convert_json_schema_to_unified(json_schema)


def _convert_json_schema_to_unified(json_schema: Dict) -> Dict[str, Any]:
    """Convert JSON schema to unified format."""
    fields = []
    properties = json_schema.get('properties', {})
    required = json_schema.get('required', [])

    # Handle $defs for nested models
    defs = json_schema.get('$defs', {})

    for field_name, field_def in properties.items():
        # Resolve $ref if present
        if '$ref' in field_def:
            ref_name = field_def['$ref'].split('/')[-1]
            field_def = defs.get(ref_name, field_def)

        field_schema = {
            'id': field_name,
            'type': field_def.get('type', 'string'),
            'required': field_name in required
        }

        if 'description' in field_def:
            field_schema['description'] = field_def['description']

        if field_def.get('type') == 'array' and 'items' in field_def:
            field_schema['items'] = field_def['items']

        if 'enum' in field_def:
            field_schema['enum'] = field_def['enum']

        fields.append(field_schema)

    return {
        'name': json_schema.get('title', 'schema'),
        'fields': fields
    }
```

#### Step 1.5: Add Dataclass Support
```python
def _derive_schema_from_dataclass(type_hint) -> Dict[str, Any]:
    """Derive schema from dataclass."""
    if not dataclasses.is_dataclass(type_hint):
        raise ValueError(f"{type_hint} is not a dataclass")

    fields = []
    for field in dataclasses.fields(type_hint):
        unwrapped_type = _unwrap_annotated(field.type)

        # Use 'is' for sentinel comparison, not '=='
        has_default = not (
            field.default is dataclasses.MISSING and
            field.default_factory is dataclasses.MISSING
        )

        field_schema = {
            'id': field.name,
            'type': _python_type_to_schema_type(unwrapped_type),
            'required': not has_default and not _is_optional_type(unwrapped_type)
        }

        # Handle List[T]
        origin = get_origin(unwrapped_type)
        if origin is list:
            args = get_args(unwrapped_type)
            if args:
                field_schema['items'] = {'type': _python_type_to_schema_type(args[0])}

        # Handle Dict[K, V]
        elif origin is dict:
            args = get_args(unwrapped_type)
            if len(args) == 2:
                field_schema['additionalProperties'] = {'type': _python_type_to_schema_type(args[1])}

        # Handle nested dataclass
        elif dataclasses.is_dataclass(unwrapped_type):
            nested_schema = _derive_schema_from_dataclass(unwrapped_type)
            field_schema['type'] = 'object'
            field_schema['properties'] = {f['id']: f for f in nested_schema['fields']}

        fields.append(field_schema)

    return {
        'name': type_hint.__name__,
        'fields': fields
    }
```

#### Step 1.6: Main Derivation Function
```python
def _derive_schema_from_type(type_hint) -> Dict[str, Any]:
    """
    Derive unified schema from Python type hint.

    Supports:
    - TypedDict
    - Pydantic BaseModel (v2)
    - dataclass

    Detection order is explicit to avoid ambiguity:
    1. Pydantic (check model_json_schema method)
    2. dataclass (check is_dataclass)
    3. TypedDict (check is_typeddict - must be last as others have __annotations__)
    """
    # Check for Pydantic first (has model_json_schema method)
    if HAS_PYDANTIC and hasattr(type_hint, 'model_json_schema'):
        return _derive_schema_from_pydantic(type_hint)

    # Check for dataclass second
    if dataclasses.is_dataclass(type_hint):
        return _derive_schema_from_dataclass(type_hint)

    # Check for TypedDict last (most types have __annotations__)
    if is_typeddict(type_hint):
        return _derive_schema_from_typeddict(type_hint)

    raise ValueError(
        f"Unsupported type hint: {type_hint}. "
        f"Expected TypedDict, Pydantic BaseModel, or dataclass."
    )
```

---

## Phase 2: Update Decorator

### Step 2.1: Add New Parameters
```python
def udf_tool(
    func: Optional[Callable] = None,
    *,
    # Type-based (NEW)
    input_type: Optional[type] = None,
    output_type: Optional[type] = None,

    # Manual schemas (existing)
    input_schema: Optional[Dict] = None,
    output_schema: Optional[Dict] = None,
    schema: Optional[Dict] = None,  # Backward compat
    schema_file: Optional[str] = None,

    # Processing
    granularity: Granularity = Granularity.RECORD
) -> Callable:
```

### Step 2.2: Schema Resolution Logic
```python
def decorator(f: Callable) -> Callable:
    # Resolve input schema (priority: input_type > input_schema > schema > schema_file)
    resolved_input_schema = None
    if input_type:
        resolved_input_schema = _derive_schema_from_type(input_type)
    elif input_schema:
        resolved_input_schema = _validate_inline_schema(input_schema, f)
    elif schema:
        resolved_input_schema = _validate_inline_schema(schema, f)
    elif schema_file:
        resolved_input_schema = _load_schema_from_file_secure(schema_file, f)
    else:
        raise ConfigurationError(
            f"UDF tool '{f.__name__}' must have a schema. "
            f"Provide 'input_type', 'input_schema', 'schema', or 'schema_file'."
        )

    # Resolve output schema (optional)
    resolved_output_schema = None
    if output_type:
        resolved_output_schema = _derive_schema_from_type(output_type)
    elif output_schema:
        resolved_output_schema = _validate_inline_schema(output_schema, f)

    # Compile schemas to JSON Schema format
    compiled_input_schema = compile_schema_to_formats(resolved_input_schema)
    compiled_output_schema = None
    if resolved_output_schema:
        compiled_output_schema = compile_schema_to_formats(resolved_output_schema)

    # Store in registry
    UDF_REGISTRY[func_name_lower] = {
        'function': f,
        'input_schema': resolved_input_schema,
        'output_schema': resolved_output_schema,
        'compiled_schemas': {
            'input': compiled_input_schema,
            'output': compiled_output_schema
        },
        'granularity': granularity,
        # ... rest of metadata
    }
```

---

## Phase 3: Output Validation

### Files to Modify
- [agent_actions/utilities/udf_management/tooling.py](file:///Users/muizz/Documents/codeshop/agent-actions/agent_actions/utilities/udf_management/tooling.py)
- [agent_actions/errors/validation.py](file:///Users/muizz/Documents/codeshop/agent-actions/agent_actions/errors/validation.py)

### Step 3.1: Add Error Class
```python
# In errors/validation.py

class OutputSchemaValidationError(SchemaValidationError):
    """Raised when function output doesn't match output schema."""
    pass
```

### Step 3.2: Add Validation Function
```python
# In tooling.py

def _validate_output_against_schema(
    output_data: Any,
    compiled_schema: Dict[str, Any],
    func_name: str,
    granularity: Granularity
) -> None:
    """Validate function output against schema."""
    import jsonschema
    from jsonschema import ValidationError as JsonSchemaValidationError

    json_schema = compiled_schema.get('schema', compiled_schema)

    try:
        jsonschema.validate(instance=output_data, schema=json_schema)
    except JsonSchemaValidationError as e:
        error_path = ' -> '.join(str(p) for p in e.path) if e.path else 'root'

        raise OutputSchemaValidationError(
            f"Output validation failed for UDF '{func_name}' at {error_path}: {e.message}",
            context={
                'function': func_name,
                'validation_error': e.message,
                'error_path': error_path,
                'actual_output': output_data,
                'expected_schema': e.schema
            }
        ) from e
```

### Step 3.3: Update Execution Function
```python
def execute_user_defined_function(
    udf_name: str,
    input_data: Union[Dict[str, Any], List[Any]],
    validate_input: bool = True,
    validate_output: bool = True,  # NEW
    **kwargs: Any
) -> Any:
    """Execute UDF with input and output validation."""

    metadata = get_udf_metadata(udf_name)
    udf = metadata['function']

    # Input validation (existing)
    if validate_input:
        # ... existing logic ...

    # Execute
    result = udf(input_data, **kwargs)

    # Output validation (NEW)
    compiled_schemas = metadata.get('compiled_schemas', {})
    output_schema = compiled_schemas.get('output')

    if validate_output and output_schema:
        compiled_output = output_schema.get('openai', output_schema)
        _validate_output_against_schema(
            result, compiled_output, udf_name, metadata['granularity']
        )

    return result
```

---

## Phase 4: Testing

### Test Files to Create
- `tests/core/test_type_hint_derivation.py`
- `tests/core/test_output_validation.py`

### Test Coverage

#### Type Detection Tests
```python
def test_type_detection_order():
    """Ensure Pydantic, dataclass, TypedDict are detected correctly."""
    from pydantic import BaseModel
    from typing import TypedDict

    class PydanticModel(BaseModel):
        text: str

    @dataclasses.dataclass
    class DataclassModel:
        text: str

    class TypedDictModel(TypedDict):
        text: str

    # Each should be detected as the correct type
    assert hasattr(PydanticModel, 'model_json_schema')
    assert dataclasses.is_dataclass(DataclassModel)
    assert is_typeddict(TypedDictModel)

    # TypedDict check should NOT match the others
    assert not is_typeddict(PydanticModel)
    assert not is_typeddict(DataclassModel)
```

#### TypedDict Tests
```python
def test_typeddict_simple():
    class Input(TypedDict):
        text: str

    @udf_tool(input_type=Input)
    def tool(data):
        return data

    metadata = get_udf_metadata('tool')
    assert metadata['input_schema']['fields'][0]['id'] == 'text'
    assert metadata['input_schema']['fields'][0]['type'] == 'string'


def test_typeddict_optional_fields():
    class Input(TypedDict, total=False):
        required: Required[str]
        optional: str

    schema = _derive_schema_from_typeddict(Input)
    fields = {f['id']: f for f in schema['fields']}
    assert fields['required']['required'] is True
    assert fields['optional']['required'] is False


def test_typeddict_with_list():
    class Input(TypedDict):
        items: List[str]

    schema = _derive_schema_from_typeddict(Input)
    field = schema['fields'][0]
    assert field['type'] == 'array'
    assert field['items']['type'] == 'string'


def test_typeddict_with_dict():
    class Input(TypedDict):
        metadata: Dict[str, int]

    schema = _derive_schema_from_typeddict(Input)
    field = schema['fields'][0]
    assert field['type'] == 'object'
    assert field['additionalProperties']['type'] == 'integer'


def test_typeddict_nested():
    class Inner(TypedDict):
        value: int

    class Outer(TypedDict):
        inner: Inner

    schema = _derive_schema_from_typeddict(Outer)
    field = schema['fields'][0]
    assert field['type'] == 'object'
    assert 'properties' in field


def test_typeddict_with_optional_type():
    class Input(TypedDict):
        maybe_text: Optional[str]

    schema = _derive_schema_from_typeddict(Input)
    field = schema['fields'][0]
    assert field['type'] == 'string'
    assert field['required'] is False
```

#### Pydantic Tests
```python
def test_pydantic_model():
    class Input(BaseModel):
        text: str
        count: int = Field(ge=0)

    @udf_tool(input_type=Input)
    def tool(data):
        return data

    metadata = get_udf_metadata('tool')
    fields = {f['id']: f for f in metadata['input_schema']['fields']}
    assert fields['text']['required'] is True
    assert fields['count']['required'] is False


def test_pydantic_nested_model():
    class Inner(BaseModel):
        value: int

    class Outer(BaseModel):
        inner: Inner

    schema = _derive_schema_from_pydantic(Outer)
    # Verify nested schema is resolved


def test_pydantic_not_installed():
    """Test graceful error when Pydantic not available."""
    # Mock HAS_PYDANTIC = False and verify error message
```

#### Dataclass Tests
```python
def test_dataclass_simple():
    @dataclasses.dataclass
    class Input:
        text: str
        count: int = 0

    schema = _derive_schema_from_dataclass(Input)
    fields = {f['id']: f for f in schema['fields']}
    assert fields['text']['required'] is True
    assert fields['count']['required'] is False


def test_dataclass_with_factory():
    @dataclasses.dataclass
    class Input:
        items: List[str] = dataclasses.field(default_factory=list)

    schema = _derive_schema_from_dataclass(Input)
    field = schema['fields'][0]
    assert field['required'] is False
```

#### Type Mapping Tests
```python
def test_int_maps_to_integer():
    """Verify int maps to 'integer', not 'number'."""
    assert _python_type_to_schema_type(int) == 'integer'
    assert _python_type_to_schema_type(float) == 'number'


def test_annotated_unwrapping():
    """Verify Annotated types are unwrapped."""
    from typing import Annotated

    annotated_str = Annotated[str, "some metadata"]
    assert _python_type_to_schema_type(annotated_str) == 'string'
```

#### Output Validation Tests
```python
def test_output_validation_success():
    class Output(TypedDict):
        result: str

    @udf_tool(
        input_schema={'fields': [{'id': 'text', 'type': 'string'}]},
        output_type=Output
    )
    def tool(data):
        return {'result': 'ok'}

    result = execute_user_defined_function('tool', {'text': 'test'})
    assert result == {'result': 'ok'}


def test_output_validation_failure():
    class Output(TypedDict):
        result: str

    @udf_tool(
        input_schema={'fields': [{'id': 'text', 'type': 'string'}]},
        output_type=Output
    )
    def bad_tool(data):
        return {'wrong_field': 'value'}

    with pytest.raises(OutputSchemaValidationError) as exc_info:
        execute_user_defined_function('bad_tool', {'text': 'test'})

    assert 'wrong_field' not in str(exc_info.value) or 'result' in str(exc_info.value)


def test_output_validation_disabled():
    class Output(TypedDict):
        result: str

    @udf_tool(
        input_schema={'fields': [{'id': 'text', 'type': 'string'}]},
        output_type=Output
    )
    def tool(data):
        return {'wrong': 'output'}

    # Should not raise when validation disabled
    result = execute_user_defined_function(
        'tool', {'text': 'test'}, validate_output=False
    )
    assert result == {'wrong': 'output'}


def test_output_validation_with_pydantic():
    class Output(BaseModel):
        result: str
        count: int

    @udf_tool(
        input_schema={'fields': [{'id': 'text', 'type': 'string'}]},
        output_type=Output
    )
    def tool(data):
        return {'result': 'ok', 'count': 42}

    result = execute_user_defined_function('tool', {'text': 'test'})
    assert result['count'] == 42
```

#### Integration Tests
```python
def test_end_to_end_type_derivation_to_execution():
    """Full integration: register with types -> compile -> execute -> validate."""
    class Input(TypedDict):
        query: str
        limit: int

    class Output(TypedDict):
        results: List[str]
        total: int

    @udf_tool(input_type=Input, output_type=Output)
    def search_tool(data):
        return {
            'results': ['item1', 'item2'],
            'total': 2
        }

    # Verify registration
    metadata = get_udf_metadata('search_tool')
    assert metadata['input_schema'] is not None
    assert metadata['output_schema'] is not None
    assert metadata['compiled_schemas']['input'] is not None
    assert metadata['compiled_schemas']['output'] is not None

    # Execute with valid input
    result = execute_user_defined_function(
        'search_tool',
        {'query': 'test', 'limit': 10}
    )
    assert result['total'] == 2

    # Verify input validation still works
    with pytest.raises(SchemaValidationError):
        execute_user_defined_function(
            'search_tool',
            {'query': 'test'}  # missing 'limit'
        )


def test_backward_compatibility_with_schema_dict():
    """Verify old-style schema dict still works."""
    @udf_tool(schema={'fields': [{'id': 'text', 'type': 'string'}]})
    def old_style_tool(data):
        return data

    result = execute_user_defined_function('old_style_tool', {'text': 'hello'})
    assert result == {'text': 'hello'}
```

#### Edge Case Tests
```python
def test_empty_typeddict():
    class Empty(TypedDict):
        pass

    schema = _derive_schema_from_typeddict(Empty)
    assert schema['fields'] == []


def test_unsupported_type_hint():
    with pytest.raises(ValueError, match="Unsupported type hint"):
        _derive_schema_from_type(str)  # Plain str is not a structured type


def test_invalid_pydantic_v1():
    """Verify Pydantic v1 models fail with clear error."""
    # If using Pydantic v1 style, should get helpful error
```

---

## Implementation Order

1. **Phase 1**: Type derivation helpers and detection
2. **Phase 2**: Decorator updates with schema compilation
3. **Phase 3**: Output validation in execution path
4. **Phase 4**: Comprehensive testing

---

## Backward Compatibility

All existing code continues to work:

```python
# Old code - still works
@udf_tool(schema={'fields': [{'id': 'text', 'type': 'string'}]})
def old_tool(data):
    return data

# New code - also works
@udf_tool(input_type=NewInput, output_type=NewOutput)
def new_tool(data):
    return data
```

---

## Success Criteria

- [ ] TypedDict support working (including Optional, List, Dict, nested)
- [ ] Pydantic support working (v2, with nested models)
- [ ] Dataclass support working (with default factories)
- [ ] `int` correctly maps to `integer` in JSON Schema
- [ ] `Annotated[T, ...]` types are properly unwrapped
- [ ] Output schema compilation step implemented
- [ ] Output validation working
- [ ] Graceful error when Pydantic not installed
- [ ] All tests passing
- [ ] Backward compatibility maintained
- [ ] Documentation updated
