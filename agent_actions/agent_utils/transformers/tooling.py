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
        module_name, function_name = udf.rsplit('.', 1)
        func = load_user_defined_function(module_name, function_name)
        return func()
    except ValueError as ve:
        logging.error("Error parsing UDF %s: %s", udf, ve)
        raise
