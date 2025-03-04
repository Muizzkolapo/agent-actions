"""
Module for Loading and running user-defined functions from a specified module.
"""
import importlib
from agent_actions.core.exceptions import raise_udf_not_found, raise_udf_execution_error


def load_user_defined_function(module_name, function_name):
    """
    Load a user-defined function from a specified module.
    """
    try:
        module = importlib.import_module(module_name)
        function = getattr(module, function_name)
        return function
    except ImportError as e:
        raise_udf_not_found(function_name, module_name)
    except AttributeError as e:
        raise_udf_not_found(function_name, module_name)

def execute_user_defined_function(udf_name, input_data):
    """
    Dynamically execute a user-defined function (UDF).
    
    Parameters:
        udf_name (str): The full path to the UDF (e.g., module_name.function_name).
        input_data (dict): The input data to pass to the UDF.
    
    Returns:
        The result of the UDF execution.
    """
    module_name, func_name = udf_name.rsplit('.', 1)
    
    try:
        module = importlib.import_module(module_name)
        udf = getattr(module, func_name)
    except (ImportError, AttributeError) as e:
        raise_udf_not_found(func_name, module_name)

    try:
        result = udf(input_data)
        return result
    except Exception as e:
        raise_udf_execution_error(udf_name, str(e))
