"""
Module for Loading and running user-defined functions from a specified module.
"""
import importlib
from agent_actions.logging_setup import setup_logging

logger = setup_logging()

def load_user_defined_function(module_name, function_name):
    """
    Load a user-defined function from a specified module.
    """
    try:
        module = importlib.import_module(module_name)
        function = getattr(module, function_name)
        return function
    except ImportError as e:
        logger.error(f"Module '{module_name}' could not be imported: {e}")
        raise
    except AttributeError as e:
        logger.error(f"Function '{function_name}' not found in module '{module_name}': {e}")
        raise

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
    except ImportError as e:
        logger.error(f"Failed to import module '{module_name}' for UDF '{udf_name}': {e}")
        raise ValueError(f"UDF '{udf_name}' could not be found: {e}")
    except AttributeError as e:
        logger.error(f"Function '{func_name}' not found in module '{module_name}'")
        raise ValueError(f"UDF '{udf_name}' could not be found: {e}")

    try:
        result = udf(input_data)
        return result
    except Exception as e:
        logger.error(f"Error executing UDF '{udf_name}': {e}")
        raise RuntimeError(f"Error executing UDF '{udf_name}': {e}")
