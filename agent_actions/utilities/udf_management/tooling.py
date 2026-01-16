"""Module for loading and running user-defined functions from a specified module."""
# Line-too-long: Descriptive error messages require long lines
# Import-outside-toplevel: Avoid circular imports with udf_registry

import importlib
import importlib.util
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
from agent_actions.errors import AgentActionsException, ConfigurationError  # New modular pattern!
from agent_actions.utilities.safe_format import safe_format_error


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
    validate_input: bool = True,
    validate_output: bool = True,
    schema_dir: Optional[Path] = None,
    **kwargs: Any,
) -> Any:
    """
    Execute UDF with optional input and output schema validation.

    Input validation is optional - when no input_type is defined, the UDF relies
    on context_scope in workflow YAML to define input structure (progressive data exposure).

    Uses CACHED compiled schemas for performance.

    Args:
        udf_name: Simple function name (e.g., 'my_function')
        input_data: Input data (single object or array depending on granularity)
        validate_input: Whether to validate input against schema (if schema defined)
        validate_output: Whether to validate output against schema (if output_type/output_schema defined)
        schema_dir: Optional schema directory for loading external schema files
        **kwargs: Additional arguments

    Returns:
        Result from UDF execution

    Raises:
        SchemaValidationError: If input or output validation fails
        AgentActionsException: If execution fails
    """
    import logging

    from agent_actions.utilities.udf_management.udf_registry import get_udf_metadata

    logger = logging.getLogger(__name__)

    metadata = get_udf_metadata(udf_name)
    udf = metadata["function"]
    granularity = metadata["granularity"]
    json_schema = metadata.get("json_schema")  # May be None (new style - no input_type)
    json_output_schema = metadata.get("json_output_schema")  # May be None
    output_schema_name = metadata.get("output_schema_name")  # External schema file name

    # Validate input if enabled AND schema is defined
    # With new style UDFs (no input_type), input validation is skipped
    # because context_scope in workflow YAML guarantees input structure
    if validate_input and json_schema is not None:
        _validate_udf_input(udf_name, input_data, granularity, json_schema)
    elif validate_input and json_schema is None:
        # No input schema - relying on context_scope for input structure
        logger.debug(
            "Skipping input validation for UDF '%s' (no input_type defined, "
            "relying on context_scope for input structure)",
            udf_name,
        )

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

    # Resolve output schema if using external file
    if validate_output and json_output_schema is None and output_schema_name:
        # Load schema from file at runtime
        json_output_schema = _load_output_schema(output_schema_name, schema_dir, udf_name)

    # Validate output if enabled and output schema is defined
    if validate_output and json_output_schema is not None:
        _validate_udf_output(udf_name, result, granularity, json_output_schema)

    return result


def _load_output_schema(
    schema_name: str,
    schema_dir: Optional[Path],
    udf_name: str,
) -> Dict[str, Any]:
    """Load output schema from external file.

    Args:
        schema_name: Name of the schema file (without extension)
        schema_dir: Directory containing schema files
        udf_name: UDF function name for error messages

    Returns:
        JSON schema for validation

    Raises:
        ConfigurationError: If schema file not found
    """
    from agent_actions.response_processing.schema_loader import SchemaLoader
    from agent_actions.utilities.udf_management.type_conversion import unified_to_json_schema

    resolved_dir = schema_dir or Path.cwd() / "schema"

    try:
        loaded = SchemaLoader.load_schema(schema_name, resolved_dir)
        return unified_to_json_schema(loaded)
    except FileNotFoundError as e:
        raise ConfigurationError(
            f"Output schema file '{schema_name}' not found for UDF '{udf_name}'",
            context={
                "schema_name": schema_name,
                "schema_dir": str(resolved_dir),
                "function": udf_name,
            },
            cause=e,
        ) from e


def _validate_udf_input(
    udf_name: str,
    input_data: Union[Dict[str, Any], List[Any]],
    granularity: Any,
    json_schema: Dict[str, Any],
) -> None:
    """Validate UDF input data against schema."""
    from agent_actions.configuration.new_format_schema import Granularity
    from agent_actions.errors import SchemaValidationError

    if granularity == Granularity.FILE:
        # Expect array input
        if not isinstance(input_data, list):
            raise SchemaValidationError(
                f"UDF '{udf_name}' expects array input (FILE granularity) "
                f"but received {type(input_data).__name__}",
                context={
                    "function": udf_name,
                    "granularity": "FILE",
                    "expected_type": "list",
                    "received_type": type(input_data).__name__,
                },
            )
        # Validate each item in array
        for idx, item in enumerate(input_data):
            _validate_against_schema(item, json_schema, udf_name, item_index=idx)
    else:  # RECORD granularity
        # Expect single object input
        if not isinstance(input_data, dict):
            raise SchemaValidationError(
                f"UDF '{udf_name}' expects object input (RECORD granularity) "
                f"but received {type(input_data).__name__}",
                context={
                    "function": udf_name,
                    "granularity": "RECORD",
                    "expected_type": "dict",
                    "received_type": type(input_data).__name__,
                },
            )

        # Validate against schema
        _validate_against_schema(input_data, json_schema, udf_name)


def _validate_udf_output(
    udf_name: str, result: Any, granularity: Any, json_output_schema: Dict[str, Any]
) -> None:
    """Validate UDF output data against schema."""
    from agent_actions.configuration.new_format_schema import Granularity

    if granularity == Granularity.FILE:
        # For FILE granularity, output should be a list - validate each item
        if isinstance(result, list):
            for idx, item in enumerate(result):
                _validate_against_schema(
                    item, json_output_schema, udf_name, item_index=idx, validation_type="output"
                )
        else:
            # Single result - validate as-is
            _validate_against_schema(result, json_output_schema, udf_name, validation_type="output")
    else:
        # RECORD granularity - validate single result
        _validate_against_schema(result, json_output_schema, udf_name, validation_type="output")


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
