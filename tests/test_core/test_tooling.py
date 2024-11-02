import unittest
from unittest.mock import patch, MagicMock
from agent_actions.core.tooling import load_user_defined_function, execute_user_defined_function

class TestUDFLoader(unittest.TestCase):

    @patch('agent_actions.udf_loader.importlib.import_module')
    @patch('agent_actions.udf_loader.logger')
    def test_load_user_defined_function_success(self, mock_logger, mock_import_module):
        # Mock function in module
        mock_module = MagicMock()
        mock_import_module.return_value = mock_module
        mock_module.some_function = lambda x: x

        function = load_user_defined_function('some_module', 'some_function')
        self.assertIsNotNone(function)
        mock_logger.info.assert_any_call("Attempting to load function 'some_function' from module 'some_module'")
        mock_logger.debug.assert_called_with("Module 'some_module' loaded successfully")
        mock_logger.info.assert_called_with("Function 'some_function' loaded successfully from module 'some_module'")

    @patch('agent_actions.udf_loader.importlib.import_module', side_effect=ImportError("Module not found"))
    @patch('agent_actions.udf_loader.logger')
    def test_load_user_defined_function_module_not_found(self, mock_logger, mock_import_module):
        with self.assertRaises(ImportError):
            load_user_defined_function('non_existent_module', 'some_function')
        mock_logger.error.assert_called_with(
            "Module 'non_existent_module' could not be imported: Module not found", exc_info=True
        )

    @patch('agent_actions.udf_loader.importlib.import_module')
    @patch('agent_actions.udf_loader.logger')
    def test_load_user_defined_function_function_not_found(self, mock_logger, mock_import_module):
        mock_module = MagicMock()
        mock_import_module.return_value = mock_module

        with self.assertRaises(AttributeError):
            load_user_defined_function('some_module', 'non_existent_function')
        mock_logger.error.assert_called_with(
            "Function 'non_existent_function' not found in module 'some_module': ", exc_info=True
        )

    @patch('agent_actions.udf_loader.importlib.import_module')
    @patch('agent_actions.udf_loader.logger')
    def test_execute_user_defined_function_success(self, mock_logger, mock_import_module):
        mock_module = MagicMock()
        mock_import_module.return_value = mock_module
        mock_module.some_function = lambda x: x

        result = execute_user_defined_function('some_module.some_function', {'key': 'value'})
        self.assertEqual(result, {'key': 'value'})
        mock_logger.info.assert_any_call("Attempting to execute UDF 'some_module.some_function' with input data: {'key': 'value'}")
        mock_logger.info.assert_called_with("UDF 'some_module.some_function' executed successfully with result: {'key': 'value'}")

    @patch('agent_actions.udf_loader.importlib.import_module', side_effect=ImportError("Module not found"))
    @patch('agent_actions.udf_loader.logger')
    def test_execute_user_defined_function_module_not_found(self, mock_logger, mock_import_module):
        with self.assertRaises(ValueError):
            execute_user_defined_function('non_existent_module.some_function', {'key': 'value'})
        mock_logger.error.assert_called_with(
            "Failed to import module 'non_existent_module' for UDF 'non_existent_module.some_function': Module not found",
            exc_info=True
        )

    @patch('agent_actions.udf_loader.importlib.import_module')
    @patch('agent_actions.udf_loader.logger')
    def test_execute_user_defined_function_execution_error(self, mock_logger, mock_import_module):
        # Simulate a function that raises an error during execution
        mock_module = MagicMock()
        mock_import_module.return_value = mock_module
        mock_module.some_function = MagicMock(side_effect=RuntimeError("Execution error"))

        with self.assertRaises(RuntimeError):
            execute_user_defined_function('some_module.some_function', {'key': 'value'})
        mock_logger.error.assert_called_with(
            "An error occurred during the execution of UDF 'some_module.some_function': Execution error",
            exc_info=True
        )

if __name__ == '__main__':
    unittest.main()
