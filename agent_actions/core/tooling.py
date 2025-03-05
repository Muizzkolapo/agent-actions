"""
Module for loading and running user-defined functions from a specified module.
"""
import importlib
from typing import Any, Callable, Dict


def load_user_defined_function(module_name: str, function_name: str) -> Callable:
    """
    Load a user-defined function from a specified module.
    
    Args:
        module_name: Name of the module containing the function
        function_name: Name of the function to load
        
    Returns:
        The loaded function
        
    Raises:
        ImportError: If the module cannot be found
        AttributeError: If the function cannot be found in the module
    """
    try:
        module = importlib.import_module(module_name)
        function = getattr(module, function_name)
        return function
    except ImportError:
        raise ImportError(f"Module '{module_name}' not found.")
    except AttributeError:
        raise AttributeError(f"Function '{function_name}' not found in module '{module_name}'.")


def execute_user_defined_function(udf_name: str, input_data: Dict[str, Any]) -> Any:
    """
    Dynamically execute a user-defined function (UDF).
    
    Args:
        udf_name: The full path to the UDF (e.g., module_name.function_name)
        input_data: The input data to pass to the UDF
    
    Returns:
        The result of the UDF execution
        
    Raises:
        ImportError: If the module cannot be found
        AttributeError: If the function cannot be found in the module
        Exception: If there's an error executing the function
    """
    # Split the UDF name into module and function parts
    try:
        module_name, func_name = udf_name.rsplit('.', 1)
    except ValueError:
        raise ValueError("Invalid UDF format. Expected 'module.function'")

    # Load the function
    udf = load_user_defined_function(module_name, func_name)

    # Execute the function
    try:
        return udf(input_data)
    except Exception as e:
        raise Exception(f"Error executing function '{func_name}': {str(e)}")