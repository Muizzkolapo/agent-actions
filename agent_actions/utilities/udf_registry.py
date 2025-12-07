"""
UDF (User-Defined Function) Registry for Agent Actions.

This module provides a decorator-based registration system for user-defined functions,
similar to dbt macros. Functions are auto-discovered and referenced by name only.

Key Features:
- @udf_tool decorator for automatic registration
- Case-insensitive exact name matching
- Duplicate detection at registration time
- Function metadata storage (module, file, docstring, signature)

Usage:
    from agent_actions import udf_tool

    @udf_tool
    def my_function(data):
        '''Process data.'''
        return processed_data

    # In config:
    # impl: my_function  # Simple name, no module path needed
"""
import inspect
from typing import Any, Callable, Dict, List
from agent_actions.errors import DuplicateFunctionError, FunctionNotFoundError  # New modular pattern!
UDF_REGISTRY: Dict[str, Dict[str, Any]] = {}

def udf_tool(func: Callable) -> Callable:
    """
    Decorator to register a user-defined function in the global registry.

    Functions are registered by name (case-insensitive) and can be referenced
    in config files without module paths.

    Args:
        func: The function to register

    Returns:
        The original function (transparent decorator)

    Raises:
        DuplicateFunctionError: If a function with the same name (case-insensitive)
            is already registered

    Example:
        @udf_tool
        def apply_edited_distractors(data):
            return modified_data
    """
    func_name = func.__name__
    func_name_lower = func_name.lower()
    if func_name_lower in UDF_REGISTRY:
        existing = UDF_REGISTRY[func_name_lower]
        existing_location = f"{existing['module']}.{existing['name']}"
        new_location = f'{func.__module__}.{func_name}'
        raise DuplicateFunctionError(function_name=func_name, existing_location=existing_location, existing_file=existing['file'], new_location=new_location, new_file=inspect.getfile(func))
    UDF_REGISTRY[func_name_lower] = {'function': func, 'module': func.__module__, 'name': func_name, 'file': inspect.getfile(func), 'docstring': func.__doc__, 'signature': inspect.signature(func)}
    return func

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
        func = get_udf('apply_edited_distractors')
        result = func(data)
    """
    func_name_lower = func_name.lower()
    if func_name_lower not in UDF_REGISTRY:
        available = sorted([meta['name'] for meta in UDF_REGISTRY.values()])
        raise FunctionNotFoundError(
            f"Function '{func_name}' not found",
            context={'function_name': func_name, 'available_functions': available}
        )
    return UDF_REGISTRY[func_name_lower]['function']

def list_udfs() -> List[Dict[str, Any]]:
    """
    List all registered UDFs with their metadata.

    Returns:
        List of dicts containing function metadata:
        - name: Function name (original case)
        - module: Module path
        - file: File path
        - docstring: Function docstring
        - signature: Function signature

    Example:
        udfs = list_udfs()
        for udf in udfs:
            print(f"{udf['name']} - {udf['file']}")
    """
    return [{'name': meta['name'], 'module': meta['module'], 'file': meta['file'], 'docstring': meta['docstring'], 'signature': str(meta['signature'])} for meta in sorted(UDF_REGISTRY.values(), key=lambda x: x['name'].lower())]

def clear_registry() -> None:
    """
    Clear the UDF registry.

    This is primarily used for test isolation to ensure tests don't
    interfere with each other.

    Example:
        @pytest.fixture(autouse=True)
        def cleanup():
            clear_registry()
    """
    UDF_REGISTRY.clear()