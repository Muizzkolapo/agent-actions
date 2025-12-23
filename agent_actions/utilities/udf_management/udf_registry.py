"""
UDF (User-Defined Function) Registry for Agent Actions.

This module provides a decorator-based registration system for user-defined functions,
similar to dbt macros. Functions are auto-discovered and referenced by name only.

Key Features:
- @udf_tool decorator with type hint schemas (TypedDict, Pydantic, dataclass)
- Case-insensitive exact name matching
- Duplicate detection at registration time
- Function metadata storage (module, file, docstring, signature, schema)
- Thread-safe registry operations
- Input and output schema validation
- Schema compilation caching for performance

Usage:
    from typing import TypedDict
    from agent_actions import udf_tool
    from agent_actions.configuration.new_format_schema import Granularity

    class MyInput(TypedDict):
        text: str

    class MyOutput(TypedDict):
        result: str

    @udf_tool(input_type=MyInput, output_type=MyOutput)
    def my_function(data):
        '''Process data.'''
        return {'result': data['text']}

    # Batch processing
    @udf_tool(input_type=MyInput, granularity=Granularity.FILE)
    def batch_function(data):
        return [{'result': item['text']} for item in data]
"""
# pylint: disable=line-too-long

import inspect
import threading
from typing import Any, Callable, Dict, List, Optional

from agent_actions.configuration.new_format_schema import Granularity
from agent_actions.errors import ConfigurationError, DuplicateFunctionError, FunctionNotFoundError

# Thread safety
_registry_lock = threading.RLock()

# Registry with cached compiled schemas
UDF_REGISTRY: Dict[str, Dict[str, Any]] = {}


def udf_tool(
    func: Optional[Callable] = None,
    *,
    input_type: type,
    output_type: Optional[type] = None,
    granularity: Granularity = Granularity.RECORD
) -> Callable:
    """
    Decorator to register a UDF with type-based schema.

    Args:
        func: The function to register
        input_type: Python type (TypedDict, Pydantic, dataclass) for input schema (REQUIRED)
        output_type: Python type for output validation (optional)
        granularity: RECORD (default) or FILE processing

    Raises:
        ConfigurationError: If input_type is not provided or not a valid type

    Examples:
        from typing import TypedDict, List, Optional

        class UserInput(TypedDict):
            user_id: str
            email: str
            age: Optional[int]

        class UserOutput(TypedDict):
            status: str

        @udf_tool(input_type=UserInput, output_type=UserOutput)
        def process_user(data, **kwargs):
            return {'status': 'processed'}

        # Batch processing with FILE granularity
        @udf_tool(input_type=UserInput, granularity=Granularity.FILE)
        def process_users_batch(data, **kwargs):
            return [{'status': 'processed'} for _ in data]
    """

    def decorator(f: Callable) -> Callable:
        from agent_actions.utilities.udf_management.type_conversion import derive_schema_from_type

        # Derive input schema from type
        resolved_schema = derive_schema_from_type(input_type)

        # Derive output schema if provided
        resolved_output_schema = None
        if output_type is not None:
            resolved_output_schema = derive_schema_from_type(output_type)

        # Thread-safe registration
        with _registry_lock:
            func_name_lower = f.__name__.lower()

            # Check for duplicates (atomic check-and-register)
            if func_name_lower in UDF_REGISTRY:
                existing = UDF_REGISTRY[func_name_lower]
                raise DuplicateFunctionError(
                    function_name=f.__name__,
                    existing_location=f"{existing['module']}.{existing['name']}",
                    existing_file=existing['file'],
                    new_location=f'{f.__module__}.{f.__name__}',
                    new_file=inspect.getfile(f)
                )

            # Pre-compile input schema for performance (cache it)
            from agent_actions.response_processing.schema_change import compile_unified_schema
            compiled_schema_cache = {
                'openai': compile_unified_schema(resolved_schema, 'openai'),
                'anthropic': compile_unified_schema(resolved_schema, 'anthropic'),
                'gemini': compile_unified_schema(resolved_schema, 'gemini'),
            }

            # Pre-compile output schema if provided
            compiled_output_cache = None
            if resolved_output_schema is not None:
                compiled_output_cache = {
                    'openai': compile_unified_schema(resolved_output_schema, 'openai'),
                    'anthropic': compile_unified_schema(resolved_output_schema, 'anthropic'),
                    'gemini': compile_unified_schema(resolved_output_schema, 'gemini'),
                }

            # Store with schema and granularity
            UDF_REGISTRY[func_name_lower] = {
                'function': f,
                'module': f.__module__,
                'name': f.__name__,
                'file': inspect.getfile(f),
                'docstring': f.__doc__,
                'signature': inspect.signature(f),
                'input_type': input_type,
                'output_type': output_type,
                'schema': resolved_schema,
                'output_schema': resolved_output_schema,
                'granularity': granularity,
                'compiled_schemas': compiled_schema_cache,
                'compiled_output_schemas': compiled_output_cache,
            }

        return f

    # Support both @udf_tool(input_type=X) and direct call
    if func is not None:
        # Called as @udf_tool without parentheses - not allowed anymore
        raise ConfigurationError(
            "udf_tool requires input_type parameter. Use @udf_tool(input_type=MyType)",
            context={'operation': 'udf_tool_registration'}
        )
    return decorator


def get_udf(func_name: str) -> Callable:
    """
    Retrieve a registered UDF by name (case-insensitive).

    Args:
        func_name: Name of the function to retrieve

    Returns:
        The registered function

    Raises:
        FunctionNotFoundError: If function not found in registry

    Example:
        func = get_udf('process_user')
        result = func(data)
    """
    with _registry_lock:
        func_name_lower = func_name.lower()
        if func_name_lower not in UDF_REGISTRY:
            available = sorted([meta['name'] for meta in UDF_REGISTRY.values()])
            raise FunctionNotFoundError(
                f"Function '{func_name}' not found",
                context={'function_name': func_name, 'available_functions': available}
            )
        return UDF_REGISTRY[func_name_lower]['function']


def get_udf_metadata(func_name: str) -> Dict[str, Any]:
    """
    Get complete UDF metadata including schema and granularity.
    Thread-safe.

    Args:
        func_name: Name of the function

    Returns:
        Dictionary containing all metadata

    Raises:
        FunctionNotFoundError: If function not found
    """
    with _registry_lock:
        func_name_lower = func_name.lower()
        if func_name_lower not in UDF_REGISTRY:
            available = sorted([meta['name'] for meta in UDF_REGISTRY.values()])
            raise FunctionNotFoundError(
                f"Function '{func_name}' not found",
                context={'function_name': func_name, 'available_functions': available}
            )
        return UDF_REGISTRY[func_name_lower].copy()


def list_udfs() -> List[Dict[str, Any]]:
    """
    List all registered UDFs with their metadata.

    Returns:
        List of dicts containing function metadata

    Example:
        udfs = list_udfs()
        for udf in udfs:
            print(f"{udf['name']} - {udf['file']}")
    """
    with _registry_lock:
        return [
            {
                'name': meta['name'],
                'module': meta['module'],
                'file': meta['file'],
                'docstring': meta['docstring'],
                'signature': str(meta['signature']),
                'input_type': meta['input_type'].__name__,
                'output_type': meta['output_type'].__name__ if meta['output_type'] else None,
            }
            for meta in sorted(UDF_REGISTRY.values(), key=lambda x: x['name'].lower())
        ]


def clear_registry() -> None:
    """
    Clear the UDF registry. Thread-safe.

    This function should only be called in test cleanup.

    Example:
        @pytest.fixture(autouse=True)
        def cleanup():
            clear_registry()
    """
    with _registry_lock:
        UDF_REGISTRY.clear()
