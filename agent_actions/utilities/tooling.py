"""Module for loading and running user-defined functions from a specified module."""
import importlib
import importlib.util
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Tuple
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
        module_name, func_name = udf_name.rsplit('.', 1)
        return (module_name, func_name)
    except ValueError as e:
        raise ConfigurationError("Invalid UDF format. Expected 'module.function'", context={'udf_name': udf_name}, cause=e) from e

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
            potential_file = Path(path) / f'{module_name}.py'
            if potential_file.exists():
                spec = importlib.util.spec_from_file_location(module_name, potential_file)
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    break
        if module is None:
            search_paths = ', '.join(sys.path)
            raise ConfigurationError(f"Module '{module_name}' for UDF not found", context={'module_name': module_name, 'search_paths': search_paths}, cause=e) from e
    try:
        function = getattr(module, function_name)
    except AttributeError as e:
        search_paths = ', '.join(sys.path)
        raise ConfigurationError(f"Function '{function_name}' not found in module '{module_name}'", context={'function_name': function_name, 'module_name': module_name, 'search_paths': search_paths}, cause=e) from e
    return function

def execute_user_defined_function(udf_name: str, input_data: Dict[str, Any], **kwargs: Any) -> Any:
    """
    Dynamically execute a user-defined function (UDF).

    Args:
        udf_name: Simple function name (e.g., 'my_function').
                 Must be decorated with @udf_tool and registered via auto-discovery.
        input_data: The input data to pass to the UDF.
        **kwargs: Additional keyword arguments to pass to the UDF.

    Returns:
        The result of the UDF execution.

    Raises:
        FunctionNotFoundError: If the function is not in the UDF registry.
        Exception: If there's an error executing the function.
    """
    from agent_actions.utilities.udf_registry import get_udf
    udf = get_udf(udf_name)
    try:
        result = udf(input_data, **kwargs)
        return result
    except Exception as e:
        raise AgentActionsException(f"Error executing user defined function '{udf_name}': {safe_format_error(e)}", context={'function': udf_name, 'operation': 'execute_udf'}, cause=e) from e