"""
Module for loading and running user-defined functions from a specified module.
"""
import importlib
from typing import Any, Callable, Dict

from agent_actions.core.exceptions import UDFNotFoundError, UDFExecutionError
from agent_actions.core.error_utils import try_operation


def load_user_defined_function(module_name: str, function_name: str) -> Callable:
    """
    Load a user-defined function from a specified module.
    
    Args:
        module_name: Name of the module containing the function
        function_name: Name of the function to load
        
    Returns:
        The loaded function
        
    Raises:
        UDFNotFoundError: If the module or function cannot be found
    """
    def _load_function():
        try:
            module = importlib.import_module(module_name)
            function = getattr(module, function_name)
            return function
        except ImportError:
            raise UDFNotFoundError(
                function_name=function_name,
                module_name=module_name,
                reason="Module not found"
            )
        except AttributeError:
            raise UDFNotFoundError(
                function_name=function_name,
                module_name=module_name,
                reason="Function not found in module"
            )
    
    return try_operation(
        _load_function,
        f"Failed to load function '{function_name}' from module '{module_name}'",
        UDFNotFoundError,
        function_name=function_name,
        module_name=module_name
    )


def execute_user_defined_function(udf_name: str, input_data: Dict[str, Any]) -> Any:
    """
    Dynamically execute a user-defined function (UDF).
    
    Args:
        udf_name: The full path to the UDF (e.g., module_name.function_name)
        input_data: The input data to pass to the UDF
    
    Returns:
        The result of the UDF execution
        
    Raises:
        UDFNotFoundError: If the module or function cannot be found
        UDFExecutionError: If there's an error executing the function
    """
    # Split the UDF name into module and function parts
    try:
        module_name, func_name = udf_name.rsplit('.', 1)
    except ValueError:
        raise UDFNotFoundError(
            function_name=udf_name,
            module_name="unknown",
            reason="Invalid UDF format. Expected 'module.function'"
        )
    
    # Load the function
    udf = load_user_defined_function(module_name, func_name)
    
    # Execute the function
    def _execute_function():
        try:
            return udf(input_data)
        except Exception as e:
            raise UDFExecutionError(
                function_name=func_name,
                reason=str(e)
            )
    
    return try_operation(
        _execute_function,
        f"Failed to execute function '{func_name}'",
        UDFExecutionError,
        function_name=func_name
    )