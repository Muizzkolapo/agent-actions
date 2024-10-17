"""
Module for Loading and running user-defined function from a specified module.
"""
import importlib
import logging

def load_user_defined_function(module_name, function_name):
    """
    Load a user-defined function from a specified module.
    """
    try:
        module = importlib.import_module(module_name)
        function = getattr(module, function_name)
        return function
    except (ImportError, AttributeError) as e:
        logging.error("Error loading function %s from module %s: %s", function_name, module_name, e)
        raise

def execute_user_defined_function(udf_name, input_data):
    print(input_data)
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
        module = __import__(module_name, fromlist=[func_name])
        udf = getattr(module, func_name)
    except (ImportError, AttributeError) as e:
        raise ValueError(f"UDF '{udf_name}' could not be found: {e}")
    
    return udf(input_data)
