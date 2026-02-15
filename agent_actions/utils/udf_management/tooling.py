"""Module for loading and running user-defined functions from a specified module."""
# Line-too-long: Descriptive error messages require long lines
# Import-outside-toplevel: Avoid circular imports with udf_registry

import importlib
import importlib.util
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
from agent_actions.errors import AgentActionsException, ConfigurationError
from agent_actions.utils.safe_format import safe_format_error


def _split_udf_name(udf_name: str) -> Tuple[str, str]:
    """
    Split a fully qualified UDF name into its module and function parts.

    Args:
        udf_name: The full UDF path in the format 'module_name.function_name'.

    Returns:
        A tuple (module_name, function_name).

    Raises:
        ValueError: If the udf_name format is invalid.
    """
    try:
        module_name, func_name = udf_name.rsplit(".", 1)
        return (module_name, func_name)
    except ValueError as e:
        raise ConfigurationError(
            "Invalid UDF format. Expected 'module.function'",
            context={"udf_name": udf_name},
            cause=e,
        ) from e


def load_user_defined_function(module_name: str, function_name: str) -> Callable:
    """
    Load a user-defined function from a specified module.

    Args:
        module_name: Name of the module containing the function.
        function_name: Name of the function to load.

    Returns:
        The loaded function.

    Raises:
        ImportError: If the module cannot be found.
        AttributeError: If the function cannot be found in the module.
    """
    try:
        module = importlib.import_module(module_name)
    except ImportError as e:
        module = None
        for path in sys.path:
            potential_file = Path(path) / f"{module_name}.py"
            if potential_file.exists():
                spec = importlib.util.spec_from_file_location(module_name, potential_file)
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    break
        if module is None:
            search_paths = ", ".join(sys.path)
            raise ConfigurationError(
                f"Module '{module_name}' for UDF not found",
                context={"module_name": module_name, "search_paths": search_paths},
                cause=e,
            ) from e
    try:
        function = getattr(module, function_name)
    except AttributeError as e:
        search_paths = ", ".join(sys.path)
        raise ConfigurationError(
            f"Function '{function_name}' not found in module '{module_name}'",
            context={
                "function_name": function_name,
                "module_name": module_name,
                "search_paths": search_paths,
            },
            cause=e,
        ) from e
    return function


def execute_user_defined_function(
    udf_name: str,
    input_data: Union[Dict[str, Any], List[Any]],
    validate_output: bool = True,
    json_output_schema: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Any:
    """
    Execute UDF with output schema validation.

    Input structure is defined by context_scope in workflow YAML (progressive data exposure).
    Only output schema validation is performed.

    Args:
        udf_name: Simple function name (e.g., 'my_function')
        input_data: Input data (single object or array depending on granularity)
        validate_output: Whether to validate output against schema
        json_output_schema: Compiled JSON Schema for output validation (from agent config)
        **kwargs: Additional arguments

    Returns:
        Result from UDF execution

    Raises:
        SchemaValidationError: If output validation fails
        AgentActionsException: If execution fails
    """
    from agent_actions.utils.udf_management.registry import get_udf_metadata

    metadata = get_udf_metadata(udf_name)
    udf = metadata["function"]
    granularity = metadata["granularity"]

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

    # Validate output if enabled and output schema is provided
    if validate_output and json_output_schema is not None:
        _validate_udf_output(udf_name, result, json_output_schema)

    return result


def _validate_udf_output(udf_name: str, result: Any, json_output_schema: Dict[str, Any]) -> None:
    """Validate UDF output data against schema.

    json_output_schema always describes a single output item (array schemas
    are resolved to their per-item schema at compile time in _compile_output_schema).
    """
    from agent_actions.utils.udf_management.registry import FileUDFResult

    # Unwrap FileUDFResult for validation (FILE-granularity wrapper)
    items = result.outputs if isinstance(result, FileUDFResult) else result

    # If the result is a list, validate each item individually.
    # This supports 1-to-many expansion (RECORD tools returning lists)
    # and N-to-M transformation (FILE tools returning lists).
    if isinstance(items, list):
        for idx, item in enumerate(items):
            _validate_against_schema(
                item, json_output_schema, udf_name, item_index=idx, validation_type="output"
            )
    else:
        _validate_against_schema(items, json_output_schema, udf_name, validation_type="output")


def _validate_against_schema(
    data: Dict[str, Any],
    compiled_schema: Dict[str, Any],
    func_name: str,
    item_index: Optional[int] = None,
    validation_type: str = "input",
) -> None:
    """
    Validate data against compiled schema.

    Args:
        data: Data to validate
        compiled_schema: Compiled JSON schema
        func_name: UDF function name for error messages
        item_index: Optional index for array item validation
        validation_type: 'input' or 'output' for error messages

    Uses jsonschema for validation with proper error handling.
    """
    import jsonschema
    from jsonschema import ValidationError as JsonSchemaValidationError
    from agent_actions.errors import SchemaValidationError

    try:
        # compiled_schema is now direct JSON Schema (no wrapper)
        jsonschema.validate(instance=data, schema=compiled_schema)

    except JsonSchemaValidationError as e:
        # Build helpful error message
        error_path = " -> ".join(str(p) for p in e.path) if e.path else "root"
        item_info = f" (item {item_index})" if item_index is not None else ""
        type_info = f"{validation_type.capitalize()} schema"

        raise SchemaValidationError(
            f"{type_info} validation failed for UDF '{func_name}'{item_info} at {error_path}: {e.message}",
            context={
                "function": func_name,
                "validation_type": validation_type,
                "validation_error": e.message,
                "error_path": error_path,
                "item_index": item_index,
                "failed_value": e.instance,
                "schema_constraint": e.schema,
            },
            cause=e,
        ) from e
