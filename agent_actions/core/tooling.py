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

def execute_user_defined_function(udf):
    """
    Execute a user-defined function specified in the UDF string.
    """
    try:
        module_name, function_name = udf.split('.')
        func = load_user_defined_function(module_name, function_name)
        return func()
    except ModuleNotFoundError as e:
        logging.error(f"Error loading function {function_name} from module {module_name}: {e}")
        return None
    except Exception as e:
        logging.error(f"An error occurred while executing the UDF {udf}: {e}")
        return None
