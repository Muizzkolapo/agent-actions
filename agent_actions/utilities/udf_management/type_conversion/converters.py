"""Type converters for Python type hints to unified schema format.

Converts TypedDict, Pydantic BaseModel, and dataclass types to the
unified schema format used throughout the codebase.
"""

import dataclasses
from typing import Any, Dict, List, Type, Union, get_origin, get_args

from agent_actions.errors import ConfigurationError

from .detector import detect_type_category, is_typeddict, TypeCategory, HAS_PYDANTIC

# JSON Schema type mapping - int maps to 'integer' (not 'number')
TYPE_MAP: Dict[type, str] = {
    str: 'string',
    int: 'integer',
    float: 'number',
    bool: 'boolean',
    list: 'array',
    dict: 'object',
    type(None): 'null',
}


def _get_json_schema_type(py_type: Any) -> str:
    """
    Convert Python type to JSON Schema type string.

    Handles:
    - Primitive types (str, int, float, bool)
    - Container types (list, dict)
    - Optional[T] -> underlying type
    - Union types -> 'string' (fallback for complex unions)

    Args:
        py_type: Python type annotation

    Returns:
        JSON Schema type string
    """
    origin = get_origin(py_type)

    # Handle Optional[T] and Union
    if origin is Union:
        args = get_args(py_type)
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1:
            return _get_json_schema_type(non_none[0])
        return 'string'  # Complex unions default to string

    # Handle List[T]
    if origin is list:
        return 'array'

    # Handle Dict[K, V]
    if origin is dict:
        return 'object'

    # Primitive type lookup
    return TYPE_MAP.get(py_type, 'string')


def _is_optional(py_type: Any) -> bool:
    """Check if type is Optional[T] (Union[T, None])."""
    origin = get_origin(py_type)
    if origin is Union:
        args = get_args(py_type)
        return type(None) in args
    return False


def _unwrap_optional(py_type: Any) -> Any:
    """Extract T from Optional[T], or return type unchanged."""
    origin = get_origin(py_type)
    if origin is Union:
        args = get_args(py_type)
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1:
            return non_none[0]
    return py_type


def derive_schema_from_type(type_hint: Type) -> Dict[str, Any]:
    """
    Derive unified schema from Python type hint.

    Public API for converting type hints to unified schema format.

    Args:
        type_hint: TypedDict, Pydantic BaseModel, or dataclass

    Returns:
        Unified schema dict with 'name' and 'fields' keys

    Raises:
        ConfigurationError: If type is not supported

    Example:
        >>> from typing import TypedDict
        >>> class UserInput(TypedDict):
        ...     name: str
        ...     age: int
        >>> schema = derive_schema_from_type(UserInput)
        >>> schema['name']
        'UserInput'
    """
    category = detect_type_category(type_hint)

    if category == TypeCategory.PYDANTIC:
        return _from_pydantic(type_hint)

    if category == TypeCategory.DATACLASS:
        return _from_dataclass(type_hint)

    if category == TypeCategory.TYPEDDICT:
        return _from_typeddict(type_hint)

    raise ConfigurationError(
        f"Unsupported type hint: {type_hint}. "
        f"Expected TypedDict, Pydantic BaseModel, or dataclass.",
        context={
            'type': str(type_hint),
            'operation': 'derive_schema_from_type',
            'supported_types': ['TypedDict', 'Pydantic BaseModel', 'dataclass']
        }
    )


def _from_typeddict(tp: Type) -> Dict[str, Any]:
    """Convert TypedDict to unified schema format."""
    annotations = getattr(tp, '__annotations__', {})
    required_keys = getattr(tp, '__required_keys__', set(annotations.keys()))

    fields: List[Dict[str, Any]] = []

    for field_name, field_type in annotations.items():
        field_schema = _build_field(
            name=field_name,
            py_type=field_type,
            is_required=field_name in required_keys and not _is_optional(field_type)
        )
        fields.append(field_schema)

    return {
        'name': tp.__name__,
        'fields': fields
    }


def _from_dataclass(tp: Type) -> Dict[str, Any]:
    """Convert dataclass to unified schema format."""
    fields: List[Dict[str, Any]] = []

    for field in dataclasses.fields(tp):
        # Check if field has a default value
        has_default = not (
            field.default is dataclasses.MISSING and
            field.default_factory is dataclasses.MISSING
        )

        field_schema = _build_field(
            name=field.name,
            py_type=field.type,
            is_required=not has_default and not _is_optional(field.type)
        )
        fields.append(field_schema)

    return {
        'name': tp.__name__,
        'fields': fields
    }


def _from_pydantic(tp: Type) -> Dict[str, Any]:
    """Convert Pydantic BaseModel to unified schema format."""
    if not HAS_PYDANTIC:
        raise ConfigurationError(
            "Pydantic is not installed. Install with: pip install pydantic",
            context={'operation': 'pydantic_type_conversion'}
        )

    if not hasattr(tp, 'model_json_schema'):
        raise ConfigurationError(
            f"{tp.__name__} is not a Pydantic v2 model (missing model_json_schema)",
            context={
                'type': tp.__name__,
                'operation': 'pydantic_type_conversion'
            }
        )

    # Get JSON Schema from Pydantic
    json_schema = tp.model_json_schema()
    defs = json_schema.get('$defs', {})
    properties = json_schema.get('properties', {})
    required = set(json_schema.get('required', []))

    fields: List[Dict[str, Any]] = []

    for field_name, field_def in properties.items():
        # Resolve $ref if present
        resolved_def = _resolve_ref(field_def, defs)
        field_schema = _pydantic_property_to_field(
            field_name, resolved_def, field_name in required, defs
        )
        fields.append(field_schema)

    return {
        'name': json_schema.get('title', tp.__name__),
        'fields': fields
    }


def _resolve_ref(field_def: Dict[str, Any], defs: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve $ref to actual definition."""
    if '$ref' in field_def:
        ref_path = field_def['$ref']
        ref_name = ref_path.split('/')[-1]
        if ref_name in defs:
            return defs[ref_name]
    return field_def


def _pydantic_property_to_field(
    field_name: str,
    field_def: Dict[str, Any],
    is_required: bool,
    defs: Dict[str, Any]
) -> Dict[str, Any]:
    """Convert Pydantic JSON Schema property to unified field format."""
    field_type = field_def.get('type', 'string')

    # Handle anyOf (Pydantic's Optional representation)
    if 'anyOf' in field_def:
        any_of = field_def['anyOf']
        non_null = [t for t in any_of if t.get('type') != 'null']
        if non_null:
            resolved = _resolve_ref(non_null[0], defs)
            field_type = resolved.get('type', 'string')
            is_required = False  # anyOf with null means optional

    field_schema: Dict[str, Any] = {
        'id': field_name,
        'type': field_type,
        'required': is_required
    }

    # Copy relevant metadata
    if 'description' in field_def:
        field_schema['description'] = field_def['description']
    if 'enum' in field_def:
        field_schema['enum'] = field_def['enum']

    # Handle array items
    if field_type == 'array' and 'items' in field_def:
        items = field_def['items']
        resolved_items = _resolve_ref(items, defs)
        field_schema['items'] = resolved_items

    # Handle nested objects
    if field_type == 'object' and 'properties' in field_def:
        field_schema['properties'] = field_def['properties']

    return field_schema


def _build_field(name: str, py_type: Any, is_required: bool) -> Dict[str, Any]:
    """Build unified schema field from name and Python type."""
    # Unwrap Optional for analysis
    unwrapped = _unwrap_optional(py_type)
    origin = get_origin(unwrapped)

    field_schema: Dict[str, Any] = {
        'id': name,
        'type': _get_json_schema_type(unwrapped),
        'required': is_required
    }

    # Handle List[T]
    if origin is list:
        args = get_args(unwrapped)
        if args:
            item_type = args[0]
            if is_typeddict(item_type):
                # Nested TypedDict in list
                nested = _from_typeddict(item_type)
                field_schema['items'] = _nested_to_json_schema(nested)
            elif dataclasses.is_dataclass(item_type):
                # Nested dataclass in list
                nested = _from_dataclass(item_type)
                field_schema['items'] = _nested_to_json_schema(nested)
            else:
                field_schema['items'] = {'type': _get_json_schema_type(item_type)}

    # Handle Dict[str, V]
    elif origin is dict:
        args = get_args(unwrapped)
        if len(args) == 2:
            value_type = args[1]
            field_schema['additionalProperties'] = {
                'type': _get_json_schema_type(value_type)
            }

    # Handle nested structured types
    elif is_typeddict(unwrapped):
        nested = _from_typeddict(unwrapped)
        field_schema['type'] = 'object'
        schema_obj = _nested_to_json_schema(nested)
        field_schema['properties'] = schema_obj.get('properties', {})
        if 'required' in schema_obj:
            field_schema['required_fields'] = schema_obj['required']

    elif dataclasses.is_dataclass(unwrapped):
        nested = _from_dataclass(unwrapped)
        field_schema['type'] = 'object'
        schema_obj = _nested_to_json_schema(nested)
        field_schema['properties'] = schema_obj.get('properties', {})
        if 'required' in schema_obj:
            field_schema['required_fields'] = schema_obj['required']

    return field_schema


def _nested_to_json_schema(unified_schema: Dict[str, Any]) -> Dict[str, Any]:
    """Convert nested unified schema to JSON Schema object format."""
    properties: Dict[str, Any] = {}
    required: List[str] = []

    for field in unified_schema.get('fields', []):
        field_id = field['id']
        prop: Dict[str, Any] = {'type': field['type']}

        if 'items' in field:
            prop['items'] = field['items']
        if 'properties' in field:
            prop['properties'] = field['properties']
        if 'additionalProperties' in field:
            prop['additionalProperties'] = field['additionalProperties']
        if 'description' in field:
            prop['description'] = field['description']

        properties[field_id] = prop

        if field.get('required', False):
            required.append(field_id)

    result: Dict[str, Any] = {
        'type': 'object',
        'properties': properties
    }
    if required:
        result['required'] = required

    return result


def unified_to_json_schema(unified_schema: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert unified schema format to standard JSON Schema.

    Used by UDF validation system for direct jsonschema.validate() calls.

    Args:
        unified_schema: Unified format with 'name' and 'fields'

    Returns:
        Standard JSON Schema dict ready for jsonschema.validate()

    Example:
        Input:
        {
            'name': 'UserInput',
            'fields': [
                {'id': 'name', 'type': 'string', 'required': True},
                {'id': 'age', 'type': 'integer', 'required': False}
            ]
        }

        Output:
        {
            'type': 'object',
            'properties': {
                'name': {'type': 'string'},
                'age': {'type': 'integer'}
            },
            'required': ['name'],
            'additionalProperties': False
        }
    """
    # Leverage existing _nested_to_json_schema for core conversion
    json_schema = _nested_to_json_schema(unified_schema)

    # Add additionalProperties: false (required by UDF validation)
    json_schema['additionalProperties'] = False

    return json_schema
