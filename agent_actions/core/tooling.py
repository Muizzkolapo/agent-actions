"""
Module for Loading and running user-defined functions from a specified module.
"""
import importlib
import logging
from agent_actions.logging_setup import setup_logging

# Initialize logger
logger = setup_logging()

def load_user_defined_function(module_name, function_name):
    """
    Load a user-defined function from a specified module.
    """
    logger.info(f"Attempting to load function '{function_name}' from module '{module_name}'")
    try:
        module = importlib.import_module(module_name)
        logger.debug(f"Module '{module_name}' loaded successfully")
        function = getattr(module, function_name)
        logger.info(f"Function '{function_name}' loaded successfully from module '{module_name}'")
        return function
    except ImportError as e:
        logger.error(f"Module '{module_name}' could not be imported: {e}", exc_info=True)
        raise
    except AttributeError as e:
        logger.error(f"Function '{function_name}' not found in module '{module_name}': {e}", exc_info=True)
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
    logger.info(f"Attempting to execute UDF '{udf_name}' with input data: {input_data}")
    module_name, func_name = udf_name.rsplit('.', 1)
    
    try:
        module = importlib.import_module(module_name)
        logger.debug(f"Module '{module_name}' loaded successfully for UDF execution")
        udf = getattr(module, func_name)
        logger.info(f"Function '{func_name}' retrieved successfully for execution")
    except ImportError as e:
        logger.error(f"Failed to import module '{module_name}' for UDF '{udf_name}': {e}", exc_info=True)
        raise ValueError(f"UDF '{udf_name}' could not be found: {e}")
    except AttributeError as e:
        logger.error(f"Function '{func_name}' not found in module '{module_name}' for UDF '{udf_name}': {e}", exc_info=True)
        raise ValueError(f"UDF '{udf_name}' could not be found: {e}")

    try:
        result = udf(input_data)
        logger.info(f"UDF '{udf_name}' executed successfully with result: {result}")
        return result
    except Exception as e:
        logger.error(f"An error occurred during the execution of UDF '{udf_name}': {e}", exc_info=True)
        raise RuntimeError(f"Error executing UDF '{udf_name}': {e}")
