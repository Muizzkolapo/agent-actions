"""
Integration tests for complete error handling system.

These tests validate the end-to-end error handling flow from
exception occurrence through user-friendly formatting.
"""
import pytest
import tempfile
import os
from pathlib import Path
from unittest.mock import patch, Mock
from agent_actions.shared.exceptions import ValidationError, FileLoadError, ConfigurationError, AgentActionsException
from agent_actions.shared.user_errors import format_user_error
from agent_actions.state_management.error_context import with_command_context, with_agent_context

class TestEndToEndErrorHandling:
    """Test complete error handling flow."""

    def test_validation_error_end_to_end(self):
        """Test validation error from occurrence to user message."""

        @with_command_context('init')
        def create_project(project_name, template='default'):
            if '@' in project_name:
                raise ValidationError(f"Project name '{project_name}' contains invalid characters")
        with pytest.raises(ValidationError) as exc_info:
            create_project('invalid@project', template='minimal')
        exc = exc_info.value
        user_message = format_user_error(exc, {'command': 'init'})
        assert 'Configuration Error' in user_message
        assert 'invalid@project' in user_message
        assert 'invalid characters' in user_message
        assert 'template: minimal' in user_message
        assert 'command: init' in user_message
        assert 'ValidationError' not in user_message
        assert 'Traceback' not in user_message

    def test_file_not_found_end_to_end(self):
        """Test file not found error from occurrence to user message."""

        @with_agent_context
        def load_agent_config(agent_name, config_dir='/configs'):
            config_path = f'{config_dir}/{agent_name}.yml'
            if not os.path.exists(config_path):
                raise FileLoadError(config_path, 'Agent configuration file not found')
        with pytest.raises(FileLoadError) as exc_info:
            load_agent_config('missing_agent', config_dir='/tmp/nonexistent')
        exc = exc_info.value
        user_message = format_user_error(exc, {'command': 'run'})
        assert 'Error' in user_message
        assert 'missing_agent' in user_message.lower()
        assert 'agent_name: missing_agent' in user_message or 'missing_agent' in user_message
        assert 'command: run' in user_message or 'run' in user_message
        assert 'create' in user_message.lower() or 'check' in user_message.lower()
        assert 'FileNotFoundError' not in user_message
        assert 'Traceback' not in user_message

    def test_configuration_error_end_to_end(self):
        """Test configuration error from occurrence to user message."""

        @with_command_context('render')
        @with_agent_context
        def parse_yaml_config(agent_name, config_content):
            if 'invalid_yaml: [' in config_content:
                exc = ConfigurationError('Invalid YAML syntax: unclosed bracket')
                exc.line_number = 5
                exc.config_file = f'{agent_name}.yml'
                raise exc
        with pytest.raises(ConfigurationError) as exc_info:
            parse_yaml_config('test_agent', 'invalid_yaml: [missing_close')
        exc = exc_info.value
        user_message = format_user_error(exc, {'command': 'render'})
        assert 'Configuration Error' in user_message
        assert 'YAML syntax' in user_message
        assert 'test_agent.yml' in user_message
        assert 'line_number: 5' in user_message
        assert 'agent_name: test_agent' in user_message
        assert 'command: render' in user_message

    def test_nested_exception_handling(self):
        """Test handling of nested exception chains."""

        @with_command_context('run')
        def outer_function(agent_name):
            try:
                inner_function(agent_name)
            except Exception as e:
                raise RuntimeError(f"Failed to process agent '{agent_name}'") from e

        def inner_function(agent_name):
            if agent_name == 'broken_agent':
                raise ValidationError('Agent configuration is invalid')
        with pytest.raises(RuntimeError) as exc_info:
            outer_function('broken_agent')
        exc = exc_info.value
        user_message = format_user_error(exc, {'command': 'run'})
        assert 'Configuration Error' in user_message or 'configuration is invalid' in user_message
        assert 'broken_agent' in user_message

    def test_broken_exception_recovery(self):
        """Test recovery from broken exception __str__ methods."""

        class BrokenAgentException(AgentActionsException):

            def __str__(self):
                raise RuntimeError('Broken __str__ method')

        @with_command_context('test')
        def failing_operation():
            exc = BrokenAgentException('Original message', {'agent': 'test_agent'})
            raise exc
        with pytest.raises(BrokenAgentException) as exc_info:
            failing_operation()
        exc = exc_info.value
        user_message = format_user_error(exc, {'command': 'test'})
        assert len(user_message) > 0
        assert 'Error' in user_message
        assert 'test_agent' in user_message
        assert 'command: test' in user_message

    def test_context_merging_across_decorators(self):
        """Test context merging from multiple decorators."""

        @with_command_context('run')
        @with_agent_context
        def complex_operation(agent_name, config_file, output_dir):
            exc = ValidationError('Multiple validation errors found')
            exc.error_count = 3
            raise exc
        with pytest.raises(ValidationError) as exc_info:
            complex_operation('test_agent', 'config.yml', '/output')
        exc = exc_info.value
        user_message = format_user_error(exc, {'additional': 'context'})
        assert 'agent_name: test_agent' in user_message
        assert 'config_file: config.yml' in user_message
        assert 'output_dir: /output' in user_message
        assert 'command: run' in user_message
        assert 'additional: context' in user_message
        assert 'error_count: 3' in user_message

class TestRealWorldScenarios:
    """Test realistic error scenarios that might occur in production."""

    def test_missing_agent_config_scenario(self):
        """Test scenario: User tries to run non-existent agent."""

        def simulate_agent_run(agent_name):
            config_path = f'/agents/{agent_name}.yml'
            raise FileLoadError(config_path, 'No such file or directory')
        with pytest.raises(FileLoadError) as exc_info:
            simulate_agent_run('nonexistent_agent')
        user_message = format_user_error(exc_info.value, {'command': 'run', 'agent': 'nonexistent_agent'})
        assert 'File Error' in user_message or 'File Not Found' in user_message or 'not found' in user_message.lower()
        assert 'nonexistent_agent' in user_message.lower()
        assert 'create' in user_message.lower() or 'check' in user_message.lower()

    def test_yaml_syntax_error_scenario(self):
        """Test scenario: User has syntax error in YAML config."""

        def simulate_yaml_parsing(config_content):
            exc = ConfigurationError('YAML syntax error at line 15: expected a value')
            exc.line_number = 15
            exc.column = 8
            raise exc
        with pytest.raises(ConfigurationError) as exc_info:
            simulate_yaml_parsing('invalid: yaml: content')
        user_message = format_user_error(exc_info.value, {'command': 'run', 'file': 'agent_config.yml'})
        assert 'Configuration Error' in user_message
        assert 'line 15' in user_message
        assert 'YAML syntax' in user_message
        assert 'agent_config.yml' in user_message

    def test_permission_denied_scenario(self):
        """Test scenario: User lacks permissions for operation."""

        def simulate_permission_error():
            raise PermissionError("Permission denied: cannot write to '/protected/output'")
        with pytest.raises(PermissionError) as exc_info:
            simulate_permission_error()
        user_message = format_user_error(exc_info.value, {'command': 'init', 'output_dir': '/protected/output'})
        assert 'Error' in user_message
        assert '/protected/output' in user_message or 'protected' in user_message.lower()
        assert user_message is not None and len(user_message) > 50

    def test_template_rendering_error_scenario(self):
        """Test scenario: Template rendering fails."""

        def simulate_template_error():
            exc = ConfigurationError("Template variable 'undefined_var' is not defined")
            exc.template_file = 'workflow.j2'
            exc.line_number = 23
            raise exc
        with pytest.raises(ConfigurationError) as exc_info:
            simulate_template_error()
        user_message = format_user_error(exc_info.value, {'command': 'render', 'agent': 'test_agent', 'template_dir': './templates'})
        assert 'Configuration Error' in user_message
        assert 'undefined_var' in user_message
        assert 'workflow.j2' in user_message
        assert '23' in user_message and ('line' in user_message.lower() or 'line_number' in user_message)

    def test_agent_execution_timeout_scenario(self):
        """Test scenario: Agent execution times out."""

        def simulate_timeout_error():
            exc = RuntimeError('Agent execution timed out after 300 seconds')
            exc.timeout_seconds = 300
            exc.agent_status = 'running'
            raise exc
        with pytest.raises(RuntimeError) as exc_info:
            simulate_timeout_error()
        user_message = format_user_error(exc_info.value, {'command': 'run', 'agent': 'slow_agent'})
        assert 'timed out' in user_message.lower()
        assert '300 seconds' in user_message
        assert 'slow_agent' in user_message

class TestErrorMessageQuality:
    """Test quality and helpfulness of error messages."""

    def test_error_messages_are_actionable(self):
        """Test that error messages provide actionable guidance."""
        test_cases = [(ValidationError('Invalid agent name'), {'command': 'init'}), (FileLoadError('/path/to/config.yml', 'Config file not found'), {'command': 'run'}), (ConfigurationError('YAML syntax error'), {'command': 'render'})]
        for exc, context in test_cases:
            user_message = format_user_error(exc, context)
            actionable_words = ['check', 'create', 'fix', 'ensure', 'verify', 'add', 'remove', 'modify']
            has_actionable_guidance = any((word in user_message.lower() for word in actionable_words))
            assert has_actionable_guidance, f'Message lacks actionable guidance: {user_message}'

    def test_error_messages_avoid_technical_jargon(self):
        """Test that error messages avoid Python-specific terminology."""
        exc = RuntimeError('Some internal error')
        user_message = format_user_error(exc, {'command': 'run'})
        forbidden_terms = ['Traceback', 'stacktrace', '__str__', '__init__', 'TypeError', 'AttributeError', 'KeyError', 'IndexError', 'module', 'class']
        for term in forbidden_terms:
            assert term not in user_message, f"Message contains technical term '{term}': {user_message}"

    def test_error_messages_include_context(self):
        """Test that error messages include relevant context."""
        exc = ValidationError('Invalid configuration')
        context = {'command': 'run', 'agent': 'test_agent', 'config_file': 'config.yml', 'line_number': 42}
        user_message = format_user_error(exc, context)
        assert 'test_agent' in user_message
        assert 'config.yml' in user_message
        assert '42' in user_message
        assert 'run' in user_message

    def test_error_message_length_appropriate(self):
        """Test that error messages are appropriately sized."""
        exc = ValidationError('Test error')
        user_message = format_user_error(exc, {'command': 'test'})
        assert 50 < len(user_message) < 1000, f'Message length inappropriate: {len(user_message)} chars'
        assert 'Test error' in user_message
        assert len(user_message) > len('Test error') + 20

class TestAPIAndNetworkErrors:
    """Test API and network error scenarios - Phase 6 Task 4 completion."""

    def test_network_error_in_api_call(self):
        """Test scenario: Network error during API call to AI provider."""
        from agent_actions.shared.exceptions import NetworkError

        def simulate_network_failure():
            """Simulate a network connection failure during API call."""
            try:
                raise ConnectionError('Failed to connect to api.anthropic.com:443')
            except ConnectionError as e:
                raise NetworkError(operation='create_message', reason='Failed to connect to AI provider API', context={'provider': 'anthropic', 'endpoint': 'https://api.anthropic.com/v1/messages'}, cause=e)
        with pytest.raises(NetworkError) as exc_info:
            simulate_network_failure()
        user_message = format_user_error(exc_info.value, {'command': 'run', 'agent': 'chat_agent', 'model': 'claude-3-5-sonnet-20241022'})
        assert 'Network Error' in user_message or 'network' in user_message.lower()
        assert 'anthropic' in user_message.lower() or 'provider' in user_message.lower()
        assert 'connect' in user_message.lower() or 'connection' in user_message.lower()
        assert 'ConnectionError' not in user_message
        assert 'Traceback' not in user_message
        assert any((word in user_message.lower() for word in ['check', 'verify', 'ensure', 'internet']))

    def test_api_timeout_error(self):
        """Test scenario: API call times out."""
        from agent_actions.shared.exceptions import NetworkError
        import socket

        def simulate_api_timeout():
            """Simulate API timeout."""
            try:
                raise socket.timeout('API request timed out after 60 seconds')
            except socket.timeout as e:
                raise NetworkError(operation='chat_completion', reason='API request timed out', context={'provider': 'openai', 'timeout_seconds': 60}, cause=e)
        with pytest.raises(NetworkError) as exc_info:
            simulate_api_timeout()
        user_message = format_user_error(exc_info.value, {'command': 'run', 'agent': 'summarizer'})
        assert 'timeout' in user_message.lower() or 'timed out' in user_message.lower()
        assert '60' in user_message or 'seconds' in user_message.lower()
        assert 'openai' in user_message.lower() or 'provider' in user_message.lower()

    def test_rate_limit_error_in_api_call(self):
        """Test scenario: Rate limit exceeded during API call."""
        from agent_actions.shared.exceptions import RateLimitError

        def simulate_rate_limit():
            """Simulate rate limit error from AI provider."""
            raise RateLimitError(service='anthropic', retry_after=60, context={'requests_made': 50, 'rate_limit': 50, 'reset_time': '2025-01-27T15:30:00Z'})
        with pytest.raises(RateLimitError) as exc_info:
            simulate_rate_limit()
        user_message = format_user_error(exc_info.value, {'command': 'run', 'agent': 'bulk_processor'})
        assert 'rate limit' in user_message.lower() or 'too many requests' in user_message.lower()
        assert '60' in user_message or 'retry' in user_message.lower()
        assert 'anthropic' in user_message.lower()

class TestBatchServiceErrors:
    """Test batch service specific error scenarios - Phase 6 Task 4 completion."""

    def test_invalid_model_in_batch_service(self):
        """Test scenario: Invalid model name specified in batch configuration."""
        from agent_actions.shared.exceptions import ConfigValidationError

        def simulate_batch_invalid_model():
            """Simulate batch service rejecting invalid model."""
            invalid_model = 'claude-4-ultra-mega'
            provider = 'anthropic'
            valid_models = ['claude-3-5-sonnet-20241022', 'claude-3-5-haiku-20241022', 'claude-3-opus-20240229']
            raise ConfigValidationError(config_key='model', reason=f"Model '{invalid_model}' not available for provider '{provider}'", context={'provided_model': invalid_model, 'provider': provider, 'valid_models': valid_models, 'operation': 'batch_job_submission', 'agent': 'batch_processor'})
        with pytest.raises(ConfigValidationError) as exc_info:
            simulate_batch_invalid_model()
        user_message = format_user_error(exc_info.value, {'command': 'batch', 'config_file': 'batch_config.json'})
        assert 'Configuration Error' in user_message or 'configuration' in user_message.lower()
        assert 'model' in user_message.lower()
        assert 'claude-4-ultra-mega' in user_message
        assert 'anthropic' in user_message.lower()
        assert 'claude-3-5-sonnet' in user_message or 'valid_models' in user_message
        assert 'ConfigValidationError' not in user_message
        assert 'Traceback' not in user_message

    def test_batch_provider_mismatch(self):
        """Test scenario: Model doesn't match provider in batch service."""
        from agent_actions.shared.exceptions import ConfigurationError

        def simulate_provider_mismatch():
            """Simulate batch config with mismatched provider/model."""
            raise ConfigurationError("Model provider mismatch: model 'gpt-4' requires provider 'openai', but 'anthropic' was specified", context={'model': 'gpt-4', 'expected_provider': 'openai', 'actual_provider': 'anthropic', 'operation': 'validate_batch_config', 'config_file': 'agents/batch_processor.yml'})
        with pytest.raises(ConfigurationError) as exc_info:
            simulate_provider_mismatch()
        user_message = format_user_error(exc_info.value, {'command': 'batch', 'agent': 'batch_processor'})
        assert 'mismatch' in user_message.lower() or 'provider' in user_message.lower()
        assert 'gpt-4' in user_message
        assert 'openai' in user_message.lower()
        assert 'anthropic' in user_message.lower()
        assert any((word in user_message.lower() for word in ['change', 'update', 'correct', 'fix']))

    def test_batch_file_not_found_in_target_generator(self):
        """Test scenario: File not found during batch target generation."""
        from agent_actions.shared.exceptions import FileLoadError

        def simulate_target_gen_file_error():
            """Simulate file not found during target generation in batch mode."""
            missing_file = '/data/inputs/batch_001.json'
            try:
                raise FileNotFoundError(f"[Errno 2] No such file or directory: '{missing_file}'")
            except FileNotFoundError as e:
                raise FileLoadError(file_path=missing_file, reason='file not found during batch target generation', context={'batch_job_id': 'batch_abc123', 'agent': 'data_processor', 'file_type': 'json', 'operation': 'generate_target'}, cause=e)
        with pytest.raises(FileLoadError) as exc_info:
            simulate_target_gen_file_error()
        user_message = format_user_error(exc_info.value, {'command': 'batch', 'agent': 'data_processor'})
        assert 'File Error' in user_message or 'file' in user_message.lower()
        assert 'not found' in user_message.lower() or 'missing' in user_message.lower()
        assert 'batch_001.json' in user_message
        assert 'batch_abc123' in user_message
        assert 'FileNotFoundError' not in user_message