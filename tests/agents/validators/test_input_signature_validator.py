"""Tests for Input Signature Validation."""
import pytest
from agent_actions.validation.input_signature_validator import InputSignatureValidator, ValidationResult, FieldValidationResult

class TestValidateAgentInputs:
    """Test validating agent input references."""

    def test_valid_schema_field_reference(self):
        """Should validate reference to schema field."""
        agent_config = {'prompt': 'Analyze {extractor.summary}', 'dependencies': ['extractor']}
        dep_configs = {'extractor': {'output_schema': {'properties': {'summary': {}, 'metrics': {}}}}}
        result = InputSignatureValidator.validate_agent_inputs(agent_config, dep_configs, 'analyzer')
        assert result.is_valid()
        assert len(result.successes) == 1
        assert len(result.errors) == 0
        assert result.successes[0].field_name == 'summary'
        assert result.successes[0].agent_name == 'extractor'

    def test_valid_observe_field_reference(self):
        """Should validate reference to observe field."""
        agent_config = {'prompt': 'Process {extractor.document_id}', 'dependencies': ['extractor']}
        dep_configs = {'extractor': {'output_schema': {'properties': {'summary': {}}}, 'observe': ['document_id', 'author']}}
        result = InputSignatureValidator.validate_agent_inputs(agent_config, dep_configs, 'processor')
        assert result.is_valid()
        assert len(result.successes) == 1
        assert result.successes[0].field_name == 'document_id'

    def test_invalid_dropped_field_reference(self):
        """Should error when referencing dropped field."""
        agent_config = {'prompt': 'Use {extractor.temp_data}', 'dependencies': ['extractor']}
        dep_configs = {'extractor': {'output_schema': {'properties': {'summary': {}, 'temp_data': {}}}, 'drops': ['temp_data']}}
        result = InputSignatureValidator.validate_agent_inputs(agent_config, dep_configs, 'user')
        assert not result.is_valid()
        assert len(result.errors) == 1
        assert 'temp_data' in result.errors[0].message
        assert 'not available' in result.errors[0].message

    def test_invalid_missing_field_reference(self):
        """Should error when field doesn't exist in dependency."""
        agent_config = {'prompt': 'Get {extractor.nonexistent}', 'dependencies': ['extractor']}
        dep_configs = {'extractor': {'output_schema': {'properties': {'summary': {}, 'metrics': {}}}}}
        result = InputSignatureValidator.validate_agent_inputs(agent_config, dep_configs, 'getter')
        assert not result.is_valid()
        assert len(result.errors) == 1
        assert 'nonexistent' in result.errors[0].message
        assert 'not available' in result.errors[0].message
        assert 'Available fields' in result.errors[0].help_text

    def test_invalid_undeclared_dependency(self):
        """Should error when dependency not declared."""
        agent_config = {'prompt': 'Use {undeclared.field}', 'dependencies': ['extractor']}
        dep_configs = {'extractor': {'output_schema': {'properties': {'summary': {}}}}}
        result = InputSignatureValidator.validate_agent_inputs(agent_config, dep_configs, 'user')
        assert not result.is_valid()
        assert len(result.errors) == 1
        assert 'undeclared' in result.errors[0].message
        assert 'not in dependencies' in result.errors[0].message
        assert 'Available dependencies' in result.errors[0].help_text

    def test_multiple_valid_references(self):
        """Should validate multiple valid references."""
        agent_config = {'prompt': '\n            Title: {source.title}\n            Summary: {extractor.summary}\n            Label: {classifier.label}\n            ', 'dependencies': ['extractor', 'classifier']}
        dep_configs = {'extractor': {'output_schema': {'properties': {'summary': {}}}}, 'classifier': {'output_schema': {'properties': {'label': {}, 'confidence': {}}}}}
        result = InputSignatureValidator.validate_agent_inputs(agent_config, dep_configs, 'combiner')
        assert result.is_valid()
        assert len(result.successes) == 3
        source_success = [s for s in result.successes if s.agent_name == 'source'][0]
        assert 'always available' in source_success.message

    def test_mixed_valid_and_invalid_references(self):
        """Should report both valid and invalid references."""
        agent_config = {'prompt': 'Valid: {extractor.summary} Invalid: {extractor.missing}', 'dependencies': ['extractor']}
        dep_configs = {'extractor': {'output_schema': {'properties': {'summary': {}, 'metrics': {}}}}}
        result = InputSignatureValidator.validate_agent_inputs(agent_config, dep_configs, 'analyzer')
        assert not result.is_valid()
        assert len(result.successes) == 1
        assert len(result.errors) == 1
        assert result.successes[0].field_name == 'summary'
        assert result.errors[0].field_name == 'missing'

    def test_special_source_reference(self):
        """Should validate source reference without dependency check."""
        agent_config = {'prompt': 'Content: {source.page_content}', 'dependencies': []}
        dep_configs = {}
        result = InputSignatureValidator.validate_agent_inputs(agent_config, dep_configs, 'extractor')
        assert result.is_valid()
        assert len(result.successes) == 1
        assert result.successes[0].agent_name == 'source'
        assert 'always available' in result.successes[0].message

    def test_special_loop_reference(self):
        """Should validate loop reference without dependency check."""
        agent_config = {'prompt': 'Processing item {loop.index} of {loop.total}', 'dependencies': []}
        dep_configs = {}
        result = InputSignatureValidator.validate_agent_inputs(agent_config, dep_configs, 'processor')
        assert result.is_valid()
        assert len(result.successes) == 2
        loop_refs = [s for s in result.successes if s.agent_name == 'loop']
        assert len(loop_refs) == 2

    def test_special_workflow_reference(self):
        """Should validate workflow reference without dependency check."""
        agent_config = {'prompt': 'Workflow: {workflow.name} v{workflow.version}', 'dependencies': []}
        dep_configs = {}
        result = InputSignatureValidator.validate_agent_inputs(agent_config, dep_configs, 'reporter')
        assert result.is_valid()
        assert len(result.successes) == 2
        workflow_refs = [s for s in result.successes if s.agent_name == 'workflow']
        assert len(workflow_refs) == 2

    def test_nested_field_validates_first_level_only(self):
        """Should validate only first-level field (e.g., 'data' in 'data.metrics.count')."""
        agent_config = {'prompt': 'Count: {extractor.data.metrics.count}', 'dependencies': ['extractor']}
        dep_configs = {'extractor': {'output_schema': {'properties': {'data': {}, 'summary': {}}}}}
        result = InputSignatureValidator.validate_agent_inputs(agent_config, dep_configs, 'counter')
        assert result.is_valid()
        assert len(result.successes) == 1
        assert result.successes[0].field_name == 'data'

    def test_empty_prompt_returns_valid(self):
        """Should return valid result for empty prompt."""
        agent_config = {'prompt': '', 'dependencies': ['extractor']}
        dep_configs = {'extractor': {'output_schema': {'properties': {'summary': {}}}}}
        result = InputSignatureValidator.validate_agent_inputs(agent_config, dep_configs, 'agent')
        assert result.is_valid()
        assert len(result.successes) == 0
        assert len(result.errors) == 0

    def test_no_references_returns_valid(self):
        """Should return valid result when prompt has no field references."""
        agent_config = {'prompt': 'This is a static prompt with no references', 'dependencies': ['extractor']}
        dep_configs = {'extractor': {'output_schema': {'properties': {'summary': {}}}}}
        result = InputSignatureValidator.validate_agent_inputs(agent_config, dep_configs, 'agent')
        assert result.is_valid()
        assert len(result.successes) == 0
        assert len(result.errors) == 0

    def test_missing_dependency_config(self):
        """Should error when dependency config not provided."""
        agent_config = {'prompt': 'Use {extractor.summary}', 'dependencies': ['extractor']}
        dep_configs = {}
        result = InputSignatureValidator.validate_agent_inputs(agent_config, dep_configs, 'user')
        assert not result.is_valid()
        assert len(result.errors) == 1
        assert 'Configuration not found' in result.errors[0].message
        assert 'extractor' in result.errors[0].message

    def test_depends_on_field_support(self):
        """Should support both 'dependencies' and 'depends_on' fields."""
        agent_config = {'prompt': 'Use {extractor.summary}', 'depends_on': ['extractor']}
        dep_configs = {'extractor': {'output_schema': {'properties': {'summary': {}}}}}
        result = InputSignatureValidator.validate_agent_inputs(agent_config, dep_configs, 'user')
        assert result.is_valid()
        assert len(result.successes) == 1

    def test_complex_scenario_all_directives(self):
        """Should handle complex scenario with all directives."""
        agent_config = {'prompt': '\n            Workflow: {workflow.name}\n            Source: {source.title}\n            Review {loop.index}: {loop.item.text}\n            Summary: {extractor.summary}\n            Document ID: {extractor.document_id}\n            ', 'dependencies': ['extractor']}
        dep_configs = {'extractor': {'output_schema': {'properties': {'summary': {}, 'metrics': {}, 'temp': {}}}, 'observe': ['document_id', 'author'], 'drops': ['temp']}}
        result = InputSignatureValidator.validate_agent_inputs(agent_config, dep_configs, 'analyzer')
        assert result.is_valid()
        assert len(result.successes) == 6
        assert len(result.errors) == 0
        special_refs = [s for s in result.successes if s.agent_name in ('workflow', 'source', 'loop')]
        assert len(special_refs) == 4
        agent_refs = [s for s in result.successes if s.agent_name == 'extractor']
        assert len(agent_refs) == 2
        field_names = {r.field_name for r in agent_refs}
        assert field_names == {'summary', 'document_id'}

class TestFormatValidationErrors:
    """Test formatting validation errors."""

    def test_format_single_error(self):
        """Should format single error with help text."""
        result = ValidationResult(agent_name='analyzer')
        result.errors.append(FieldValidationResult(field_reference='{extractor.missing}', agent_name='extractor', field_name='missing', is_valid=False, message="Field 'missing' not available", help_text="Available fields: ['summary', 'metrics']"))
        formatted = InputSignatureValidator.format_validation_errors(result)
        assert "Validation errors in agent 'analyzer'" in formatted
        assert '{extractor.missing}' in formatted
        assert "Field 'missing' not available" in formatted
        assert "Available fields: ['summary', 'metrics']" in formatted

    def test_format_multiple_errors(self):
        """Should format multiple errors."""
        result = ValidationResult(agent_name='combiner')
        result.errors.extend([FieldValidationResult(field_reference='{extractor.missing}', agent_name='extractor', field_name='missing', is_valid=False, message="Field 'missing' not available", help_text="Available fields: ['summary']"), FieldValidationResult(field_reference='{unknown.field}', agent_name='unknown', field_name='field', is_valid=False, message="Agent 'unknown' not in dependencies", help_text="Add 'unknown' to dependencies list")])
        formatted = InputSignatureValidator.format_validation_errors(result)
        assert '{extractor.missing}' in formatted
        assert '{unknown.field}' in formatted
        assert "Field 'missing' not available" in formatted
        assert "Agent 'unknown' not in dependencies" in formatted

    def test_format_no_errors_returns_empty(self):
        """Should return empty string when no errors."""
        result = ValidationResult(agent_name='agent')
        result.successes.append(FieldValidationResult(field_reference='{extractor.summary}', agent_name='extractor', field_name='summary', is_valid=True, message='Valid'))
        formatted = InputSignatureValidator.format_validation_errors(result)
        assert formatted == ''

class TestValidationResultDataclass:
    """Test ValidationResult dataclass methods."""

    def test_has_errors_true(self):
        """Should return True when errors exist."""
        result = ValidationResult(agent_name='agent')
        result.errors.append(FieldValidationResult(field_reference='{x.y}', agent_name='x', field_name='y', is_valid=False, message='error'))
        assert result.has_errors() is True
        assert result.is_valid() is False

    def test_has_errors_false(self):
        """Should return False when no errors."""
        result = ValidationResult(agent_name='agent')
        result.successes.append(FieldValidationResult(field_reference='{x.y}', agent_name='x', field_name='y', is_valid=True, message='success'))
        assert result.has_errors() is False
        assert result.is_valid() is True

    def test_has_warnings(self):
        """Should detect warnings."""
        result = ValidationResult(agent_name='agent')
        result.warnings.append(FieldValidationResult(field_reference='{x.y}', agent_name='x', field_name='y', is_valid=True, message='warning'))
        assert result.has_warnings() is True

    def test_observe_fallback(self):
        """Should validate reference to observe when observe is not present."""
        agent_config = {'prompt': 'Process {extractor.document_id}', 'dependencies': ['extractor']}
        dep_configs = {'extractor': {'output_schema': {'properties': {'summary': {}}}, 'observe': ['document_id', 'author']}}
        result = InputSignatureValidator.validate_agent_inputs(agent_config, dep_configs, 'processor')
        assert result.is_valid()
        assert len(result.successes) == 1
        assert result.successes[0].field_name == 'document_id'

    def test_drops_fallback(self):
        """Should handle drops when drops is not present."""
        agent_config = {'prompt': 'Use {extractor.temp_data}', 'dependencies': ['extractor']}
        dep_configs = {'extractor': {'output_schema': {'properties': {'summary': {}, 'temp_data': {}}}, 'drops': ['temp_data']}}
        result = InputSignatureValidator.validate_agent_inputs(agent_config, dep_configs, 'user')
        assert not result.is_valid()
        assert len(result.errors) == 1
        assert 'temp_data' in result.errors[0].message
        assert 'not available' in result.errors[0].message