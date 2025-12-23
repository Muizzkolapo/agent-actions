"""
UDF (User-Defined Function) Registry for Agent Actions.

This module provides a decorator-based registration system for user-defined functions,
similar to dbt macros. Functions are auto-discovered and referenced by name only.

Key Features:
- @udf_tool decorator with REQUIRED schemas
- Case-insensitive exact name matching
- Duplicate detection at registration time
- Function metadata storage (module, file, docstring, signature, schema)
- Thread-safe registry operations
- Security validations (path traversal, file size, symlinks)
- Schema compilation caching for performance

Usage:
    from agent_actions import udf_tool
    from agent_actions.configuration.new_format_schema import Granularity

    @udf_tool(schema={'text': 'string'})
    def my_function(data):
        '''Process data.'''
        return processed_data

    # With file-based schema
    @udf_tool(schema_file='schemas/my_function.yml', granularity=Granularity.FILE)
    def batch_function(data):
        return [process(item) for item in data]
"""
# pylint: disable=line-too-long
# Line-too-long: Descriptive error messages and metadata storage require long lines

import inspect
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

import yaml

from agent_actions.configuration.new_format_schema import Granularity
from agent_actions.errors import ConfigurationError, DuplicateFunctionError, FunctionNotFoundError

# Thread safety
_registry_lock = threading.RLock()

# Registry with cached compiled schemas
UDF_REGISTRY: Dict[str, Dict[str, Any]] = {}

# Security constants
MAX_SCHEMA_FILE_SIZE = 1 * 1024 * 1024  # 1MB

# Thread-local storage for circular reference detection
_schema_loading_stack = threading.local()


def _get_loading_stack() -> List[str]:
    """Get thread-local loading stack for circular reference detection."""
    if not hasattr(_schema_loading_stack, 'stack'):
        _schema_loading_stack.stack = []
    return _schema_loading_stack.stack


def udf_tool(
    func: Optional[Callable] = None,
    *,
    input_type: Optional[type] = None,
    output_type: Optional[type] = None,
    schema: Optional[Union[Dict[str, Any], str]] = None,
    schema_file: Optional[str] = None,
    granularity: Granularity = Granularity.RECORD
) -> Callable:
    """
    Decorator to register a UDF with REQUIRED schema.

    Schema Resolution Priority:
        1. input_type (derives schema from Python type hint)
        2. schema (inline dict)
        3. schema_file (external YAML)

    Args:
        func: The function to register
        input_type: Python type (TypedDict, Pydantic, dataclass) for input schema
        output_type: Python type for output validation (optional)
        schema: Inline schema definition (dict) - uses unified format
        schema_file: Path to schema YAML file (relative to tool directory)
        granularity: RECORD (default) or FILE processing (uses existing Granularity enum)

    Raises:
        ConfigurationError: If no schema source is provided

    Examples:
        # Type-based schema (NEW)
        from typing import TypedDict

        class UserInput(TypedDict):
            user_id: str
            email: str

        class UserOutput(TypedDict):
            status: str

        @udf_tool(input_type=UserInput, output_type=UserOutput)
        def process_user(data, **kwargs):
            return {'status': 'processed'}

        # Inline schema - RECORD granularity (legacy, still works)
        @udf_tool(schema={
            'fields': [
                {'id': 'user_id', 'type': 'string', 'required': True}
            ]
        })
        def process_user_legacy(data, **kwargs):
            return {'status': 'processed'}

        # File-level schema - FILE granularity (batch processing)
        @udf_tool(
            schema_file='process_users.yml',
            granularity=Granularity.FILE
        )
        def process_users_batch(data, **kwargs):
            return [process(user) for user in data]
    """
    
    def decorator(f: Callable) -> Callable:
        # Validate that at least one schema source is provided
        if input_type is None and schema is None and schema_file is None:
            raise ConfigurationError(
                f"UDF tool '{f.__name__}' must have a schema. "
                f"Provide 'input_type', 'schema', or 'schema_file' parameter.",
                context={
                    'function_name': f.__name__,
                    'module': f.__module__,
                    'file': inspect.getfile(f),
                    'operation': 'udf_tool_registration'
                }
            )

        # Resolve input schema (priority: input_type > schema > schema_file)
        if input_type is not None:
            from agent_actions.utilities.udf_management.type_conversion import derive_schema_from_type
            resolved_schema = derive_schema_from_type(input_type)
            schema_source = 'type_hint'
        elif schema_file:
            resolved_schema = _load_schema_from_file_secure(schema_file, f)
            schema_source = 'file'
        else:
            resolved_schema = _validate_inline_schema(schema, f)
            schema_source = 'inline'

        # Resolve output schema (optional)
        resolved_output_schema = None
        if output_type is not None:
            from agent_actions.utilities.udf_management.type_conversion import derive_schema_from_type
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
                'schema': resolved_schema,  # Unified schema format (input)
                'output_schema': resolved_output_schema,  # Unified schema format (output)
                'schema_source': schema_source,
                'schema_file': schema_file,
                'granularity': granularity,  # Use Granularity enum
                'compiled_schemas': compiled_schema_cache,  # CACHED input schemas
                'compiled_output_schemas': compiled_output_cache  # CACHED output schemas
            }
        
        return f
    
    # Support both @udf_tool and @udf_tool(schema=...)
    if func is not None:
        return decorator(func)
    return decorator


def _load_schema_from_file_secure(schema_file: str, func: Callable) -> Dict[str, Any]:
    """
    Load schema from YAML file with security validations.
    
    Security checks:
    1. Path traversal protection
    2. Symlink rejection
    3. File size limits
    4. Circular reference detection
    """
    # Resolve schema file path relative to the function's module
    func_file = Path(inspect.getfile(func))
    schema_path = (func_file.parent / schema_file).resolve()
    
    # Security check 1: Path traversal protection
    project_root = Path.cwd()
    try:
        schema_path.relative_to(project_root)
    except ValueError as e:
        raise ConfigurationError(
            f"Schema file '{schema_file}' is outside project bounds",
            context={
                'function_name': func.__name__,
                'schema_file': schema_file,
                'resolved_path': str(schema_path),
                'project_root': str(project_root),
                'security_violation': 'path_traversal'
            },
            cause=e
        ) from e
    
    # Security check 2: Symlink rejection
    if schema_path.is_symlink():
        raise ConfigurationError(
            f"Schema file '{schema_file}' is a symlink (not allowed)",
            context={
                'function_name': func.__name__,
                'schema_file': schema_file,
                'security_violation': 'symlink'
            }
        )
    
    # Security check 3: File existence
    if not schema_path.exists():
        raise ConfigurationError(
            f"Schema file '{schema_file}' not found for UDF '{func.__name__}'",
            context={
                'function_name': func.__name__,
                'schema_file': schema_file,
                'resolved_path': str(schema_path),
                'function_file': str(func_file)
            }
        )
    
    # Security check 4: File size limit (prevent YAML bombs)
    file_size = schema_path.stat().st_size
    if file_size > MAX_SCHEMA_FILE_SIZE:
        raise ConfigurationError(
            f"Schema file '{schema_file}' exceeds size limit ({file_size} > {MAX_SCHEMA_FILE_SIZE} bytes)",
            context={
                'function_name': func.__name__,
                'schema_file': schema_file,
                'file_size': file_size,
                'max_size': MAX_SCHEMA_FILE_SIZE,
                'security_violation': 'file_size_limit'
            }
        )
    
    # Security check 5: Circular reference detection (thread-safe)
    loading_stack = _get_loading_stack()  # Thread-local!
    schema_path_str = str(schema_path)
    
    if schema_path_str in loading_stack:
        raise ConfigurationError(
            f"Circular schema reference detected: {schema_file}",
            context={
                'function_name': func.__name__,
                'schema_file': schema_file,
                'loading_stack': loading_stack.copy(),
                'security_violation': 'circular_reference'
            }
        )
    
    # Load schema directly (FIX: don't use SchemaLoader.load_schema())
    loading_stack.append(schema_path_str)
    try:
        with schema_path.open('r', encoding='utf-8') as file:
            schema = yaml.safe_load(file)
        
        if not isinstance(schema, dict):
            raise ConfigurationError(
                f"Schema file '{schema_file}' must contain a dictionary",
                context={
                    'function_name': func.__name__,
                    'schema_file': schema_file,
                    'schema_type': type(schema).__name__
                }
            )
        
        return schema
    finally:
        loading_stack.pop()


def _validate_inline_schema(schema: Union[Dict[str, Any], str], func: Callable) -> Dict[str, Any]:
    """
    Validate inline schema format.
    
    Accepts two formats:
    1. Unified format: {'name': '...', 'fields': [...]}
    2. Simple dict: {'field_name': 'type'} - converted to unified
    """
    from agent_actions.response_processing.schema_loader import SchemaLoader
    
    if not isinstance(schema, dict):
        raise ConfigurationError(
            f"Schema for UDF '{func.__name__}' must be a dictionary",
            context={'function_name': func.__name__, 'schema_type': type(schema).__name__}
        )
    
    # Check if already in unified format
    if 'fields' in schema:
        # Validate unified format
        if 'name' not in schema:
            schema['name'] = func.__name__
        return schema
    
    # Convert simple dict to unified format
    unified = SchemaLoader.construct_schema_from_dict(schema)
    unified['name'] = func.__name__
    return unified


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
        return UDF_REGISTRY[func_name_lower].copy()  # Return copy for thread safety


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
    with _registry_lock:
        return [
            {
                'name': meta['name'],
                'module': meta['module'],
                'file': meta['file'],
                'docstring': meta['docstring'],
                'signature': str(meta['signature'])
            }
            for meta in sorted(UDF_REGISTRY.values(), key=lambda x: x['name'].lower())
        ]


def clear_registry() -> None:
    """
    Clear the UDF registry. Thread-safe.

    Note: Only clears the registry, not thread-local loading stacks.
    Each thread manages its own loading stack.

    This function should only be called in test cleanup.

    Example:
        @pytest.fixture(autouse=True)
        def cleanup():
            clear_registry()
    """
    with _registry_lock:
        UDF_REGISTRY.clear()
        # Don't clear thread-local stacks - each thread owns its own
