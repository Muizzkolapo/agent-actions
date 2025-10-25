"""
Tests for user_errors module user-friendly error formatting.
"""
import pytest
from unittest.mock import Mock, patch
from pathlib import Path
from agent_actions.shared.user_errors import UserError, ErrorTranslator, format_user_error
from agent_actions.shared.exceptions import AgentActionsException, ValidationError, FileLoadError, ConfigurationError

class TestUserError:
    """Test UserError dataclass."""

    def test_user_error_creation(self):
        """Test creating UserError with all fields."""
        error = UserError(category='validation', title='Invalid Configuration', details="Missing required field 'name'", fix="Add 'name' field to your configuration", context={'file': 'config.yml', 'line': 5})
        assert error.category == 'validation'
        assert error.title == 'Invalid Configuration'
        assert error.details == "Missing required field 'name'"
        assert error.fix == "Add 'name' field to your configuration"
        assert error.context == {'file': 'config.yml', 'line': 5}

    def test_user_error_minimal(self):
        """Test creating UserError with minimal fields."""
        error = UserError(category='error', title='Something went wrong')
        assert error.category == 'error'
        assert error.title == 'Something went wrong'
        assert error.details is None
        assert error.fix is None
        assert error.context is None

    def test_user_error_format(self):
        """Test UserError string formatting."""
        error = UserError(category='validation', title='Invalid Configuration', details="Missing required field 'name'", fix="Add 'name' field to your configuration", context={'file': 'config.yml'})
        formatted = str(error)
        assert 'Invalid Configuration' in formatted
        assert "Missing required field 'name'" in formatted
        assert "Add 'name' field to your configuration" in formatted
        assert 'config.yml' in formatted

class TestErrorTranslator:
    """Test ErrorTranslator class."""

    def test_translator_initialization(self):
        """Test ErrorTranslator initialization."""
        translator = ErrorTranslator()
        assert hasattr(translator, 'translate')
        assert hasattr(translator, '_is_config_error')
        assert hasattr(translator, '_is_file_error')
        assert hasattr(translator, '_is_auth_error')

    def test_validation_error_handling(self):
        """Test handling ValidationError."""
        translator = ErrorTranslator()
        exc = ValidationError('Invalid agent name: must contain only letters')
        context = {'command': 'init', 'agent': 'invalid-name!'}
        result = translator.translate(exc, context)
        assert result.category == 'Configuration Error'
        assert 'Configuration Error' in result.title or 'Invalid configuration' in result.title
        assert 'invalid agent name' in result.details.lower() or 'must contain only letters' in result.details.lower()
        assert result.fix is not None

    def test_file_not_found_error_handling(self):
        """Test handling FileLoadError."""
        translator = ErrorTranslator()
        exc = FileLoadError('test_agent.yml', 'Agent configuration file not found')
        context = {'command': 'run', 'agent': 'test_agent'}
        result = translator.translate(exc, context)
        assert result.category in ['File Error', 'Configuration Error']
        assert result.title is not None
        assert 'test_agent' in result.details.lower()
        assert result.fix is not None

    def test_configuration_error_handling(self):
        """Test handling ConfigurationError."""
        translator = ErrorTranslator()
        exc = ConfigurationError('Invalid YAML syntax in configuration file')
        context = {'command': 'run', 'file': 'config.yml'}
        result = translator.translate(exc, context)
        assert result.category == 'Configuration Error'
        assert 'configuration' in result.title.lower() or 'invalid' in result.title.lower()
        assert 'YAML syntax' in result.details or 'Invalid' in result.details
        assert result.fix is not None

    def test_permission_error_handling(self):
        """Test handling permission errors (FileSystemError in our code)."""
        translator = ErrorTranslator()
        from agent_actions.shared.exceptions import FileSystemError
        exc = FileSystemError('Permission denied: cannot write to output directory')
        context = {'command': 'init', 'directory': '/protected/dir'}
        result = translator.translate(exc, context)
        assert result.category in ['File Error', 'Error', 'Authentication Error']
        assert result.title is not None
        assert result.fix is not None

    def test_generic_exception_handling(self):
        """Test handling generic exceptions."""
        translator = ErrorTranslator()
        exc = RuntimeError('Unexpected error during processing')
        context = {'command': 'run'}
        result = translator.translate(exc, context)
        assert result.category == 'Error'
        assert 'Error' in result.title
        assert 'Unexpected error' in result.details or 'processing' in result.details
        assert result.fix is not None

    def test_agent_actions_exception_with_context(self):
        """Test handling AgentActionsException with context."""
        translator = ErrorTranslator()
        exc = AgentActionsException('Custom error message', {'agent': 'test', 'step': 'validation'})
        context = {'command': 'run'}
        result = translator.translate(exc, context)
        assert 'Custom error message' in result.details
        assert result.context is not None
        assert 'agent' in result.context
        assert 'test' in result.context['agent']

    def test_context_extraction_from_exception(self):
        """Test context extraction from exception attributes."""
        translator = ErrorTranslator()
        exc = ValueError('Test error')
        exc.context = {'file': 'test.yml', 'line': 10}
        exc.agent_name = 'test_agent'
        context = {'command': 'run'}
        result = translator.translate(exc, context)
        assert result.context is not None
        assert 'file' in result.context
        assert 'agent_name' in result.context

    def test_safe_error_message_extraction(self):
        """Test safe extraction of error messages."""
        translator = ErrorTranslator()

        class BrokenException(Exception):

            def __str__(self):
                raise RuntimeError('Broken __str__')
        exc = BrokenException('Original message')
        context = {'command': 'test'}
        result = translator.translate(exc, context)
        assert result.category == 'Error'
        assert result.title is not None
        assert result.details is not None

class TestFormatUserError:
    """Test format_user_error function."""

    def test_format_validation_error(self):
        """Test formatting ValidationError."""
        exc = ValidationError('Agent name cannot contain special characters')
        context = {'command': 'init', 'agent': 'invalid@name'}
        result = format_user_error(exc, context)
        assert 'Configuration Error' in result
        assert 'special characters' in result
        assert 'invalid@name' in result

    def test_format_file_not_found(self):
        """Test formatting FileLoadError."""
        exc = FileLoadError('/path/to/missing/file.yml')
        context = {'command': 'run', 'agent': 'missing_agent'}
        result = format_user_error(exc, context)
        assert 'File Error' in result or 'File Not Found' in result or 'not found' in result.lower()
        assert 'missing_agent' in result
        assert result is not None

    def test_format_with_empty_context(self):
        """Test formatting with empty context."""
        exc = ValueError('Test error message')
        result = format_user_error(exc, {})
        assert 'Test error message' in result
        assert len(result) > 0

    def test_format_with_none_context(self):
        """Test formatting with None context."""
        exc = ValueError('Test error message')
        result = format_user_error(exc, None)
        assert 'Test error message' in result
        assert len(result) > 0

    def test_format_preserves_command_context(self):
        """Test that command context is preserved in output."""
        exc = ConfigurationError('Invalid configuration syntax')
        context = {'command': 'render', 'agent': 'test_agent', 'file': 'config.yml'}
        result = format_user_error(exc, context)
        assert 'render' in result
        assert 'test_agent' in result
        assert 'config.yml' in result

    def test_format_handles_broken_exception(self):
        """Test formatting handles broken exception gracefully."""

        class BrokenException(Exception):

            def __str__(self):
                raise ValueError('Broken formatting')
        exc = BrokenException('Original message')
        context = {'command': 'test'}
        result = format_user_error(exc, context)
        assert len(result) > 0
        assert 'Error' in result

    def test_format_with_nested_exceptions(self):
        """Test formatting with nested exception chains."""
        root_cause = ValidationError('Missing required field')
        wrapper = RuntimeError('Configuration loading failed')
        wrapper.__cause__ = root_cause
        context = {'command': 'run', 'file': 'config.yml'}
        result = format_user_error(wrapper, context)
        assert 'Missing required field' in result or 'Configuration Error' in result

    @patch('agent_actions.core.user_errors.ErrorTranslator')
    def test_format_uses_translator(self, mock_translator_class):
        """Test that format_user_error uses ErrorTranslator."""
        mock_translator = Mock()
        mock_translator_class.return_value = mock_translator
        mock_translator.translate.return_value = UserError(category='test', title='Test Error', details='Test details')
        exc = ValueError('Test')
        context = {'command': 'test'}
        format_user_error(exc, context)
        mock_translator_class.assert_called_once()
        mock_translator.translate.assert_called_once_with(exc, context)

    def test_format_with_pathlib_paths(self):
        """Test formatting with pathlib.Path objects in context."""
        exc = FileLoadError('/path/to/config.yml', 'Config file not found')
        context = {'command': 'run', 'config_file': Path('/path/to/config.yml'), 'output_dir': Path('/path/to/output')}
        result = format_user_error(exc, context)
        assert 'config.yml' in result
        assert 'output' in result

    def test_format_command_specific_guidance(self):
        """Test that different commands get appropriate guidance."""
        exc = ValidationError('Invalid configuration')
        init_result = format_user_error(exc, {'command': 'init'})
        run_result = format_user_error(exc, {'command': 'run'})
        assert len(init_result) > 0
        assert len(run_result) > 0
        assert 'init' in init_result or 'run' in run_result