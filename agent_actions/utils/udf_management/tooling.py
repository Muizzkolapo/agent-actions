"""Loading and execution of user-defined functions from specified modules."""

from collections.abc import Callable
from typing import Any

from agent_actions.errors import AgentActionsError, ConfigurationError, SchemaValidationError
from agent_actions.utils.module_loader import load_module_from_path
from agent_actions.utils.safe_format import safe_format_error


def load_user_defined_function(module_name: str, function_name: str) -> Callable:
    """Load a user-defined function from a specified module.

    Delegates module loading to :func:`~agent_actions.utils.module_loader.load_module_from_path`
    which handles file-based loading with caching and fallback to standard import.

    Raises:
        ConfigurationError: If the module or function cannot be found.
    """
    module = load_module_from_path(
        module_name,
        module_path=None,
        execute=True,
        fallback_import=False,
        cache=True,
    )
    if module is None:
        raise ConfigurationError(
            f"Module '{module_name}' for UDF not found",
            context={"module_name": module_name},
        )
    try:
        function = getattr(module, function_name)
    except AttributeError as e:
        raise ConfigurationError(
            f"Function '{function_name}' not found in module '{module_name}'",
            context={
                "function_name": function_name,
                "module_name": module_name,
            },
            cause=e,
        ) from e
    return function  # type: ignore[no-any-return]


def execute_user_defined_function(
    udf_name: str,
    input_data: dict[str, Any] | list[Any],
    validate_output: bool = True,
    json_output_schema: dict[str, Any] | None = None,
    **kwargs: Any,
) -> Any:
    """Execute a registered UDF with optional output schema validation.

    Raises:
        SchemaValidationError: If output validation fails.
        AgentActionsError: If execution fails.
    """
    from agent_actions.config.types import Granularity
    from agent_actions.utils.udf_management.bus import Bus
    from agent_actions.utils.udf_management.registry import get_udf_metadata

    metadata = get_udf_metadata(udf_name)
    udf = metadata["function"]
    granularity = metadata["granularity"]

    # Hand RECORD-mode dict input to the UDF as a Bus so authors can opt into
    # data.require() (the action-keyed bus on the tool path; a flat eval context
    # on the guard-clause path). FILE mode receives a list, so it is excluded.
    # Bus is a transparent dict subclass — get/[]/iteration unchanged.
    if (
        granularity == Granularity.RECORD
        and isinstance(input_data, dict)
        and not isinstance(input_data, Bus)
    ):
        input_data = Bus(input_data)

    try:
        result = udf(input_data, **kwargs)
    except Exception as e:
        raise AgentActionsError(
            f"Error executing UDF '{udf_name}': {safe_format_error(e)}",
            context={
                "function": udf_name,
                "operation": "execute_udf",
                "granularity": granularity.value,
            },
            cause=e,
        ) from e

    if validate_output and json_output_schema is not None:
        _validate_udf_output(udf_name, result, json_output_schema)

    return result


def _validate_udf_output(udf_name: str, result: Any, json_output_schema: dict[str, Any]) -> None:
    """Validate UDF output against a per-item JSON Schema."""
    errors = output_schema_errors(udf_name, result, json_output_schema)
    if errors:
        raise errors[0][1]


def output_schema_errors(
    udf_name: str, result: Any, json_output_schema: dict[str, Any]
) -> list[tuple[int | None, SchemaValidationError]]:
    """Each item of a UDF's output its per-item schema refuses, by position in the output.

    A ``FileUDFResult`` item is its output's ``data``. A result that is not a list is
    checked as one item, at position ``None``.
    """
    from agent_actions.utils.udf_management.registry import FileUDFResult

    items = [out["data"] for out in result.outputs] if isinstance(result, FileUDFResult) else result
    positioned: list[tuple[int | None, Any]] = (
        list(enumerate(items)) if isinstance(items, list) else [(None, items)]
    )

    errors: list[tuple[int | None, SchemaValidationError]] = []
    for idx, item in positioned:
        try:
            _validate_against_schema(
                item, json_output_schema, udf_name, item_index=idx, validation_type="output"
            )
        except SchemaValidationError as e:
            errors.append((idx, e))
    return errors


def _validate_against_schema(
    data: dict[str, Any],
    compiled_schema: dict[str, Any],
    func_name: str,
    item_index: int | None = None,
    validation_type: str = "input",
) -> None:
    """Validate data against a compiled JSON Schema.

    Raises:
        SchemaValidationError: On validation failure with path details.
    """
    import jsonschema  # type: ignore[import-untyped]
    from jsonschema import ValidationError as JsonSchemaValidationError

    from agent_actions.errors import SchemaValidationError

    try:
        jsonschema.validate(instance=data, schema=compiled_schema)

    except JsonSchemaValidationError as e:
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
