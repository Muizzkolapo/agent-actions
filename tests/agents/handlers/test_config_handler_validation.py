"""Integration tests for input signature validation in ConfigManager."""

import pytest
from unittest.mock import Mock, patch, MagicMock
from agent_actions.agents.handlers.config_handler import ConfigManager
from agent_actions.core.exceptions import ConfigValidationError
from agent_actions.core.parser.config_schema import AgentConfig


class TestConfigManagerInputValidation:
    """Test input signature validation during config loading."""

    def create_agent_config(self, **kwargs):
        """Helper to create AgentConfig with defaults."""
        defaults = {
            'agent_type': 'llm',
            'model_name': 'gpt-4o-mini',
            'model_vendor': 'openai',
            'prompt': '',
            'dependencies': [],
            'is_operational': True,
            'output_schema': {'properties': {}}
        }
        defaults.update(kwargs)
        return AgentConfig(**defaults)

    @patch('agent_actions.agents.handlers.config_handler.Utils.topological_sort')
    @patch('agent_actions.agents.handlers.config_handler.ConfigValidator')
    def test_valid_field_references_pass_validation(self, mock_validator_class, mock_topo_sort):
        """Should pass validation when field references are valid."""
        # Setup
        config_manager = ConfigManager("test.yml", "default.yml")

        # Create agents with valid field references
        config_manager.agent_configs = {
            'extractor': self.create_agent_config(
                output_schema={'properties': {'summary': {}, 'metrics': {}}}
            ),
            'analyzer': self.create_agent_config(
                prompt='Analyze {extractor.summary}',
                dependencies=['extractor']
            )
        }

        mock_validator_instance = Mock()
        mock_validator_class.return_value = mock_validator_instance
        mock_topo_sort.return_value = ['extractor', 'analyzer']

        # Execute - should not raise
        config_manager.determine_execution_order()

        # Verify topological sort was called (validation passed)
        assert mock_topo_sort.called

    @patch('agent_actions.agents.handlers.config_handler.Utils.topological_sort')
    @patch('agent_actions.agents.handlers.config_handler.ConfigValidator')
    def test_invalid_missing_field_raises_error(self, mock_validator_class, mock_topo_sort):
        """Should raise ConfigValidationError when referencing missing field."""
        # Setup
        config_manager = ConfigManager("test.yml", "default.yml")

        config_manager.agent_configs = {
            'extractor': self.create_agent_config(
                output_schema={'properties': {'summary': {}}}
            ),
            'analyzer': self.create_agent_config(
                prompt='Use {extractor.nonexistent}',
                dependencies=['extractor']
            )
        }

        mock_validator_instance = Mock()
        mock_validator_class.return_value = mock_validator_instance

        # Execute and expect error
        with pytest.raises(ConfigValidationError) as exc_info:
            config_manager.determine_execution_order()

        # Verify error details
        assert 'input_signatures' in str(exc_info.value)
        assert 'nonexistent' in exc_info.value.context['error_details']

    @patch('agent_actions.agents.handlers.config_handler.Utils.topological_sort')
    @patch('agent_actions.agents.handlers.config_handler.ConfigValidator')
    def test_invalid_dropped_field_raises_error(self, mock_validator_class, mock_topo_sort):
        """Should raise error when referencing dropped field."""
        # Setup
        config_manager = ConfigManager("test.yml", "default.yml")

        config_manager.agent_configs = {
            'extractor': self.create_agent_config(
                output_schema={'properties': {'summary': {}, 'temp': {}}},
                drops=['temp']
            ),
            'analyzer': self.create_agent_config(
                prompt='Use {extractor.temp}',
                dependencies=['extractor']
            )
        }

        mock_validator_instance = Mock()
        mock_validator_class.return_value = mock_validator_instance

        # Execute and expect error
        with pytest.raises(ConfigValidationError) as exc_info:
            config_manager.determine_execution_order()

        assert 'temp' in exc_info.value.context['error_details']
        assert 'not available' in exc_info.value.context['error_details']

    @patch('agent_actions.agents.handlers.config_handler.Utils.topological_sort')
    @patch('agent_actions.agents.handlers.config_handler.ConfigValidator')
    def test_invalid_undeclared_dependency_raises_error(self, mock_validator_class, mock_topo_sort):
        """Should raise error when referencing undeclared dependency."""
        # Setup
        config_manager = ConfigManager("test.yml", "default.yml")

        config_manager.agent_configs = {
            'extractor': self.create_agent_config(
                output_schema={'properties': {'summary': {}}}
            ),
            'analyzer': self.create_agent_config(
                prompt='Use {unknown.field}',
                dependencies=['extractor']  # 'unknown' not declared
            )
        }

        mock_validator_instance = Mock()
        mock_validator_class.return_value = mock_validator_instance

        # Execute and expect error
        with pytest.raises(ConfigValidationError) as exc_info:
            config_manager.determine_execution_order()

        assert 'unknown' in exc_info.value.context['error_details']
        assert 'not in dependencies' in exc_info.value.context['error_details']

    @patch('agent_actions.agents.handlers.config_handler.Utils.topological_sort')
    @patch('agent_actions.agents.handlers.config_handler.ConfigValidator')
    def test_valid_observe_field_passes(self, mock_validator_class, mock_topo_sort):
        """Should pass validation when referencing observe field."""
        # Setup
        config_manager = ConfigManager("test.yml", "default.yml")

        config_manager.agent_configs = {
            'extractor': self.create_agent_config(
                output_schema={'properties': {'summary': {}}},
                observe=['document_id', 'metadata']
            ),
            'analyzer': self.create_agent_config(
                prompt='Process {extractor.document_id}',
                dependencies=['extractor']
            )
        }

        mock_validator_instance = Mock()
        mock_validator_class.return_value = mock_validator_instance
        mock_topo_sort.return_value = ['extractor', 'analyzer']

        # Execute - should not raise
        config_manager.determine_execution_order()

        assert mock_topo_sort.called

    @patch('agent_actions.agents.handlers.config_handler.Utils.topological_sort')
    @patch('agent_actions.agents.handlers.config_handler.ConfigValidator')
    def test_special_source_reference_passes(self, mock_validator_class, mock_topo_sort):
        """Should pass validation for special {source.*} references."""
        # Setup
        config_manager = ConfigManager("test.yml", "default.yml")

        config_manager.agent_configs = {
            'extractor': self.create_agent_config(
                prompt='Extract from {source.page_content}',
                dependencies=[]
            )
        }

        mock_validator_instance = Mock()
        mock_validator_class.return_value = mock_validator_instance
        mock_topo_sort.return_value = ['extractor']

        # Execute - should not raise
        config_manager.determine_execution_order()

        assert mock_topo_sort.called

    @patch('agent_actions.agents.handlers.config_handler.Utils.topological_sort')
    @patch('agent_actions.agents.handlers.config_handler.ConfigValidator')
    def test_special_loop_reference_passes(self, mock_validator_class, mock_topo_sort):
        """Should pass validation for special {loop.*} references."""
        # Setup
        config_manager = ConfigManager("test.yml", "default.yml")

        config_manager.agent_configs = {
            'processor': self.create_agent_config(
                prompt='Processing item {loop.index} of {loop.total}',
                dependencies=[]
            )
        }

        mock_validator_instance = Mock()
        mock_validator_class.return_value = mock_validator_instance
        mock_topo_sort.return_value = ['processor']

        # Execute - should not raise
        config_manager.determine_execution_order()

        assert mock_topo_sort.called

    @patch('agent_actions.agents.handlers.config_handler.Utils.topological_sort')
    @patch('agent_actions.agents.handlers.config_handler.ConfigValidator')
    def test_special_workflow_reference_passes(self, mock_validator_class, mock_topo_sort):
        """Should pass validation for special {workflow.*} references."""
        # Setup
        config_manager = ConfigManager("test.yml", "default.yml")

        config_manager.agent_configs = {
            'reporter': self.create_agent_config(
                prompt='Workflow: {workflow.name} v{workflow.version}',
                dependencies=[]
            )
        }

        mock_validator_instance = Mock()
        mock_validator_class.return_value = mock_validator_instance
        mock_topo_sort.return_value = ['reporter']

        # Execute - should not raise
        config_manager.determine_execution_order()

        assert mock_topo_sort.called

    @patch('agent_actions.agents.handlers.config_handler.Utils.topological_sort')
    @patch('agent_actions.agents.handlers.config_handler.ConfigValidator')
    def test_multiple_errors_all_reported(self, mock_validator_class, mock_topo_sort):
        """Should report all validation errors, not just first one."""
        # Setup
        config_manager = ConfigManager("test.yml", "default.yml")

        config_manager.agent_configs = {
            'extractor': self.create_agent_config(
                output_schema={'properties': {'summary': {}}}
            ),
            'analyzer': self.create_agent_config(
                prompt='Use {extractor.missing1} and {extractor.missing2}',
                dependencies=['extractor']
            )
        }

        mock_validator_instance = Mock()
        mock_validator_class.return_value = mock_validator_instance

        # Execute and expect error
        with pytest.raises(ConfigValidationError) as exc_info:
            config_manager.determine_execution_order()

        # Both errors should be in the message
        error_details = exc_info.value.context['error_details']
        assert 'missing1' in error_details
        assert 'missing2' in error_details

    @patch('agent_actions.agents.handlers.config_handler.Utils.topological_sort')
    @patch('agent_actions.agents.handlers.config_handler.ConfigValidator')
    def test_no_prompt_skips_validation(self, mock_validator_class, mock_topo_sort):
        """Should skip validation for agents without prompts."""
        # Setup
        config_manager = ConfigManager("test.yml", "default.yml")

        config_manager.agent_configs = {
            'function_agent': self.create_agent_config(
                agent_type='function',
                prompt='',  # No prompt
                dependencies=[]
            )
        }

        mock_validator_instance = Mock()
        mock_validator_class.return_value = mock_validator_instance
        mock_topo_sort.return_value = ['function_agent']

        # Execute - should not raise
        config_manager.determine_execution_order()

        assert mock_topo_sort.called

    @patch('agent_actions.agents.handlers.config_handler.Utils.topological_sort')
    @patch('agent_actions.agents.handlers.config_handler.ConfigValidator')
    def test_complex_workflow_with_all_directives(self, mock_validator_class, mock_topo_sort):
        """Should validate complex workflow with schema, observe, drops."""
        # Setup
        config_manager = ConfigManager("test.yml", "default.yml")

        config_manager.agent_configs = {
            'extractor': self.create_agent_config(
                output_schema={'properties': {'summary': {}, 'metrics': {}, 'temp': {}}},
                observe=['document_id'],
                drops=['temp']
            ),
            'analyzer': self.create_agent_config(
                prompt='''
                Source: {source.title}
                Summary: {extractor.summary}
                Metrics: {extractor.metrics}
                Document ID: {extractor.document_id}
                ''',
                dependencies=['extractor']
            )
        }

        mock_validator_instance = Mock()
        mock_validator_class.return_value = mock_validator_instance
        mock_topo_sort.return_value = ['extractor', 'analyzer']

        # Execute - should not raise (all references valid)
        config_manager.determine_execution_order()

        assert mock_topo_sort.called

    @patch('agent_actions.agents.handlers.config_handler.Utils.topological_sort')
    @patch('agent_actions.agents.handlers.config_handler.ConfigValidator')
    def test_non_operational_agents_not_validated(self, mock_validator_class, mock_topo_sort):
        """Should skip validation for non-operational agents."""
        # Setup
        config_manager = ConfigManager("test.yml", "default.yml")

        config_manager.agent_configs = {
            'disabled_agent': self.create_agent_config(
                prompt='Use {nonexistent.field}',  # Invalid, but agent is disabled
                is_operational=False
            ),
            'active_agent': self.create_agent_config(
                prompt='Valid prompt',
                is_operational=True
            )
        }

        mock_validator_instance = Mock()
        mock_validator_class.return_value = mock_validator_instance
        mock_topo_sort.return_value = ['active_agent']

        # Execute - should not raise (disabled agent not validated)
        config_manager.determine_execution_order()

        assert mock_topo_sort.called


class TestFormatInputValidationErrors:
    """Test error message formatting."""

    def test_format_single_error(self):
        """Should format single validation error clearly."""
        from agent_actions.agents.validators.input_signature_validator import (
            ValidationResult, FieldValidationResult
        )

        config_manager = ConfigManager("test.yml", "default.yml")

        result = ValidationResult(agent_name='analyzer')
        result.errors.append(
            FieldValidationResult(
                field_reference='{extractor.missing}',
                agent_name='extractor',
                field_name='missing',
                is_valid=False,
                message="Field 'missing' not available",
                help_text="Available fields: ['summary', 'metrics']"
            )
        )

        formatted = config_manager._format_input_validation_errors([('analyzer', result)])

        assert 'INPUT SIGNATURE VALIDATION ERRORS' in formatted
        assert 'analyzer' in formatted
        assert '{extractor.missing}' in formatted
        assert "Field 'missing' not available" in formatted
        assert "Available fields: ['summary', 'metrics']" in formatted

    def test_format_multiple_errors_multiple_agents(self):
        """Should format errors from multiple agents."""
        from agent_actions.agents.validators.input_signature_validator import (
            ValidationResult, FieldValidationResult
        )

        config_manager = ConfigManager("test.yml", "default.yml")

        result1 = ValidationResult(agent_name='agent1')
        result1.errors.append(
            FieldValidationResult(
                field_reference='{x.field}',
                agent_name='x',
                field_name='field',
                is_valid=False,
                message='Error 1'
            )
        )

        result2 = ValidationResult(agent_name='agent2')
        result2.errors.append(
            FieldValidationResult(
                field_reference='{y.field}',
                agent_name='y',
                field_name='field',
                is_valid=False,
                message='Error 2'
            )
        )

        formatted = config_manager._format_input_validation_errors([
            ('agent1', result1),
            ('agent2', result2)
        ])

        assert 'agent1' in formatted
        assert 'agent2' in formatted
        assert 'Error 1' in formatted
        assert 'Error 2' in formatted
