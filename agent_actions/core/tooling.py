"""
Module for loading and running user-defined functions from a specified module.
"""
import importlib
from typing import Any, Callable, Dict, Tuple
from agent_actions.cli.exceptions import AgentActionsError, ConfigurationError


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
        return module_name, func_name
    except ValueError as e:
        raise ValueError("Invalid UDF format. Expected 'module.function'") from e


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
        raise ConfigurationError(f"Module '{module_name}' for UDF not found.") from e
    
    try:
        function = getattr(module, function_name)
    except AttributeError as e:
        raise ConfigurationError(f"Function '{function_name}' not found in module '{module_name}'.") from e
    
    return function


def execute_user_defined_function(udf_name: str, input_data: Dict[str, Any], **kwargs: Any) -> Any:
    """
    Dynamically execute a user-defined function (UDF).

    Args:
        udf_name: The full path to the UDF (e.g., 'module_name.function_name').
        input_data: The input data to pass to the UDF.
        **kwargs: Additional keyword arguments to pass to the UDF.

    Returns:
        The result of the UDF execution.

    Raises:
        ImportError: If the module cannot be found.
        AttributeError: If the function cannot be found in the module.
        Exception: If there's an error executing the function.
    """
    module_name, func_name = _split_udf_name(udf_name)
    udf = load_user_defined_function(module_name, func_name)
    
    try:
        result = udf(input_data, **kwargs)
        return result
    except ConfigurationError: # Re-raise if load_user_defined_function failed
        raise
    except Exception as e:
        raise AgentActionsError(f"Error executing user defined function '{func_name}': {str(e)}") from e
