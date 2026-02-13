"""Type converters for Python type hints to unified schema format.

Converts TypedDict, Pydantic BaseModel, and dataclass types to the
unified schema format used throughout the codebase.
"""

import dataclasses
import sys
from typing import Any, Dict, List, Tuple, Type, Union, get_origin, get_args

from agent_actions.errors import ConfigurationError
from agent_actions.logging import fire_event
from agent_actions.logging.events.types import CacheHitEvent, CacheMissEvent, CacheInvalidationEvent

# Import for type checking
if sys.version_info >= (3, 10):
    from typing import is_typeddict as STDLIB_IS_TYPEDDICT
else:
    STDLIB_IS_TYPEDDICT = None  # type: ignore

# Optional Pydantic support
try:
    from pydantic import BaseModel as PydanticBaseModel

    HAS_PYDANTIC = True
except ImportError:
    HAS_PYDANTIC = False
    PydanticBaseModel = None  # type: ignore

# JSON Schema type mapping - int maps to 'integer' (not 'number')
TYPE_MAP: Dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
    type(None): "null",
}

# Type schema cache for memoization
_schema_cache: Dict[type, Dict[str, Any]] = {}


def is_typeddict(tp: Type) -> bool:
    """
    Check if a type is a TypedDict.

    Python 3.10+ has typing.is_typeddict, but we need 3.9 compatibility.
    Must exclude Pydantic and dataclass since they also have __annotations__.
    """
    if sys.version_info >= (3, 10) and STDLIB_IS_TYPEDDICT:
        return STDLIB_IS_TYPEDDICT(tp)

    # Python 3.9 fallback - must explicitly exclude other types
    if HAS_PYDANTIC and isinstance(tp, type) and issubclass(tp, PydanticBaseModel):
        return False
    if dataclasses.is_dataclass(tp):
        return False

    return (
        hasattr(tp, "__annotations__")
        and hasattr(tp, "__total__")
        and hasattr(tp, "__required_keys__")
    )


def _analyze_type(py_type: Any) -> Tuple[Any, bool]:
    """
    Analyze a type to unwrap Optional and detect if it's optional.

    Returns:
        Tuple of (unwrapped_type, is_optional)
    """
    origin = get_origin(py_type)
    if origin is Union:
        args = get_args(py_type)
        is_optional = type(None) in args
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1:
            return non_none[0], is_optional
        # Complex union - return as-is
        return py_type, is_optional
    return py_type, False


def _get_json_schema_type(py_type: Any) -> str:
    """Convert Python type to JSON Schema type string."""
    origin = get_origin(py_type)

    # Handle List[T]
    if origin is list:
        return "array"

    # Handle Dict[K, V]
    if origin is dict:
        return "object"

    # Handle Union - unwrap and recurse
    if origin is Union:
        args = get_args(py_type)
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1:
            return _get_json_schema_type(non_none[0])
        return "string"  # Complex unions default to string

    # Primitive type lookup
    return TYPE_MAP.get(py_type, "string")


def derive_schema_from_type(type_hint: Type) -> Dict[str, Any]:
    """
    Derive unified schema from Python type hint.

    Public API for converting type hints to unified schema format.
    Results are cached for performance.

    Args:
        type_hint: TypedDict, Pydantic BaseModel, or dataclass

    Returns:
        Unified schema dict with 'name' and 'fields' keys

    Raises:
        ConfigurationError: If type is not supported
    """
    # Check cache first
    if type_hint in _schema_cache:
        # Fire cache hit event
        type_name = getattr(type_hint, "__name__", str(type_hint))
        fire_event(CacheHitEvent(cache_type="schema_type", key=type_name))
        # Return a copy to prevent mutation of cached value
        return _deep_copy_schema(_schema_cache[type_hint])

    # Fire cache miss event
    type_name = getattr(type_hint, "__name__", str(type_hint))
    fire_event(CacheMissEvent(cache_type="schema_type", key=type_name, reason="type not in cache"))

    # Detection order (most specific to least):
    # 1. Pydantic (has model_json_schema - unique to v2)
    # 2. dataclass (stdlib is_dataclass)
    # 3. TypedDict (must be last - least specific markers)

    if HAS_PYDANTIC and hasattr(type_hint, "model_json_schema"):
        result = _from_pydantic(type_hint)
    elif dataclasses.is_dataclass(type_hint):
        result = _from_dataclass(type_hint)
    elif is_typeddict(type_hint):
        result = _from_typeddict(type_hint)
    else:
        raise ConfigurationError(
            f"Unsupported type hint: {type_hint}. "
            f"Expected TypedDict, Pydantic BaseModel, or dataclass.",
            context={
                "type": str(type_hint),
                "operation": "derive_schema_from_type",
                "supported_types": ["TypedDict", "Pydantic BaseModel", "dataclass"],
            },
        )

    # Cache the result
    _schema_cache[type_hint] = result
    return _deep_copy_schema(result)


def _deep_copy_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
    """Create a deep copy of a schema dict to prevent mutation."""
    result = {"name": schema["name"], "fields": []}
    for field in schema["fields"]:
        result["fields"].append(dict(field))
    return result


def _from_typeddict(tp: Type) -> Dict[str, Any]:
    """Convert TypedDict to unified schema format."""
    annotations = getattr(tp, "__annotations__", {})
    required_keys = getattr(tp, "__required_keys__", set(annotations.keys()))

    fields: List[Dict[str, Any]] = []

    for field_name, field_type in annotations.items():
        unwrapped, is_optional = _analyze_type(field_type)
        field_schema = _build_field(
            name=field_name,
            _py_type=field_type,
            unwrapped_type=unwrapped,
            is_required=field_name in required_keys and not is_optional,
        )
        fields.append(field_schema)

    return {"name": tp.__name__, "fields": fields}


def _from_dataclass(tp: Type) -> Dict[str, Any]:
    """Convert dataclass to unified schema format."""
    fields: List[Dict[str, Any]] = []

    for field in dataclasses.fields(tp):
        # Check if field has a default value
        has_default = not (
            field.default is dataclasses.MISSING and field.default_factory is dataclasses.MISSING
        )

        unwrapped, is_optional = _analyze_type(field.type)
        field_schema = _build_field(
            name=field.name,
            _py_type=field.type,
            unwrapped_type=unwrapped,
            is_required=not has_default and not is_optional,
        )
        fields.append(field_schema)

    return {"name": tp.__name__, "fields": fields}


def _from_pydantic(tp: Type) -> Dict[str, Any]:
    """Convert Pydantic BaseModel to unified schema format."""
    if not HAS_PYDANTIC:
        raise ConfigurationError(
            "Pydantic is not installed. Install with: uv pip install pydantic",
            context={"operation": "pydantic_type_conversion"},
        )

    if not hasattr(tp, "model_json_schema"):
        raise ConfigurationError(
            f"{tp.__name__} is not a Pydantic v2 model (missing model_json_schema)",
            context={"type": tp.__name__, "operation": "pydantic_type_conversion"},
        )

    # Get JSON Schema from Pydantic
    json_schema = tp.model_json_schema()
    defs = json_schema.get("$defs", {})
    properties = json_schema.get("properties", {})
    required = set(json_schema.get("required", []))

    fields: List[Dict[str, Any]] = []

    for field_name, field_def in properties.items():
        # Inline $ref resolution
        resolved_def = field_def
        if "$ref" in field_def:
            ref_name = field_def["$ref"].split("/")[-1]
            if ref_name in defs:
                resolved_def = defs[ref_name]

        field_schema = _pydantic_property_to_field(
            field_name, resolved_def, field_name in required, defs
        )
        fields.append(field_schema)

    return {"name": json_schema.get("title", tp.__name__), "fields": fields}


def _pydantic_property_to_field(
    field_name: str, field_def: Dict[str, Any], is_required: bool, defs: Dict[str, Any]
) -> Dict[str, Any]:
    """Convert Pydantic JSON Schema property to unified field format."""
    field_type = field_def.get("type", "string")

    # Handle anyOf (Pydantic's Optional representation)
    if "anyOf" in field_def:
        any_of = field_def["anyOf"]
        non_null = [t for t in any_of if t.get("type") != "null"]
        if non_null:
            # Inline $ref resolution for anyOf items
            resolved = non_null[0]
            if "$ref" in resolved:
                ref_name = resolved["$ref"].split("/")[-1]
                if ref_name in defs:
                    resolved = defs[ref_name]
            field_type = resolved.get("type", "string")
            is_required = False  # anyOf with null means optional

    field_schema: Dict[str, Any] = {"id": field_name, "type": field_type, "required": is_required}

    # Copy relevant metadata
    if "description" in field_def:
        field_schema["description"] = field_def["description"]
    if "enum" in field_def:
        field_schema["enum"] = field_def["enum"]

    # Handle array items
    if field_type == "array" and "items" in field_def:
        items = field_def["items"]
        # Inline $ref resolution for items
        if "$ref" in items:
            ref_name = items["$ref"].split("/")[-1]
            if ref_name in defs:
                items = defs[ref_name]
        field_schema["items"] = items

    # Handle nested objects
    if field_type == "object" and "properties" in field_def:
        field_schema["properties"] = field_def["properties"]

    return field_schema


def _build_field(
    name: str,
    _py_type: Any,  # Used in error messages and validation
    unwrapped_type: Any,
    is_required: bool,
) -> Dict[str, Any]:
    """Build unified schema field from name and Python type."""
    origin = get_origin(unwrapped_type)

    field_schema: Dict[str, Any] = {
        "id": name,
        "type": _get_json_schema_type(unwrapped_type),
        "required": is_required,
    }

    # Handle List[T]
    if origin is list:
        args = get_args(unwrapped_type)
        if args:
            item_type = args[0]
            if is_typeddict(item_type):
                nested = _from_typeddict(item_type)
                field_schema["items"] = _nested_to_json_schema(nested)
            elif dataclasses.is_dataclass(item_type):
                nested = _from_dataclass(item_type)
                field_schema["items"] = _nested_to_json_schema(nested)
            else:
                field_schema["items"] = {"type": _get_json_schema_type(item_type)}

    # Handle Dict[str, V]
    elif origin is dict:
        args = get_args(unwrapped_type)
        if len(args) == 2:
            value_type = args[1]
            field_schema["additionalProperties"] = {"type": _get_json_schema_type(value_type)}

    # Handle nested structured types
    elif is_typeddict(unwrapped_type):
        nested = _from_typeddict(unwrapped_type)
        field_schema["type"] = "object"
        schema_obj = _nested_to_json_schema(nested)
        field_schema["properties"] = schema_obj.get("properties", {})
        if "required" in schema_obj:
            field_schema["required_fields"] = schema_obj["required"]

    elif dataclasses.is_dataclass(unwrapped_type):
        nested = _from_dataclass(unwrapped_type)
        field_schema["type"] = "object"
        schema_obj = _nested_to_json_schema(nested)
        field_schema["properties"] = schema_obj.get("properties", {})
        if "required" in schema_obj:
            field_schema["required_fields"] = schema_obj["required"]

    return field_schema


def _nested_to_json_schema(unified_schema: Dict[str, Any]) -> Dict[str, Any]:
    """Convert nested unified schema to JSON Schema object format."""
    properties: Dict[str, Any] = {}
    required: List[str] = []

    for field in unified_schema.get("fields", []):
        field_id = field["id"]
        prop: Dict[str, Any] = {"type": field["type"]}

        if "items" in field:
            prop["items"] = field["items"]
        if "properties" in field:
            prop["properties"] = field["properties"]
        if "additionalProperties" in field:
            prop["additionalProperties"] = field["additionalProperties"]
        if "description" in field:
            prop["description"] = field["description"]

        properties[field_id] = prop

        if field.get("required", False):
            required.append(field_id)

    result: Dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        result["required"] = required

    return result


def unified_to_json_schema(unified_schema: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert unified schema format to standard JSON Schema.

    Used by UDF validation system for direct jsonschema.validate() calls.

    Args:
        unified_schema: Unified format with 'name' and 'fields'

    Returns:
        Standard JSON Schema dict ready for jsonschema.validate()
    """
    json_schema = _nested_to_json_schema(unified_schema)
    json_schema["additionalProperties"] = False
    return json_schema


def clear_schema_cache() -> None:
    """Clear the type schema cache. Useful for testing."""
    entries_removed = len(_schema_cache)
    _schema_cache.clear()

    fire_event(
        CacheInvalidationEvent(
            cache_type="schema_type", entries_removed=entries_removed, reason="manual clear"
        )
    )
