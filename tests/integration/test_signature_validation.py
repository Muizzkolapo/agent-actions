"""
Integration tests for workflow-level signature validation.

This module tests the complete integration of signature APIs with ConfigManager
for workflow-level operations like field flow validation and conflict detection.
"""
import pytest
import tempfile
import yaml
from pathlib import Path
from typing import Dict, Any
from agent_actions.llm_invocation.realtime.config_handler import ConfigManager
from agent_actions.response_processing.config_schema import AgentConfig
from agent_actions.state_management.signatures import InputSignature, OutputSignature

@pytest.fixture
def temp_workflow_files():
    """Create temporary workflow and defaults files for testing."""
    workflow_file = tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False, prefix='test_workflow_')
    defaults_file = tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False, prefix='defaults_')
    workflow_name = Path(workflow_file.name).stem
    workflow_data = {workflow_name: {'agents': [{'name': 'extractor', 'agent_type': 'extractor', 'model_vendor': 'anthropic', 'model_name': 'claude-3-haiku-20240307', 'api_key': 'fake-key', 'chunk_config': {}, 'output_schema': {'properties': {'summary': {'type': 'string'}, 'entities': {'type': 'array'}, 'metadata': {'type': 'object'}}}, 'observe': ['document_id', 'source_url'], 'drops': ['metadata']}, {'name': 'classifier', 'agent_type': 'classifier', 'model_vendor': 'anthropic', 'model_name': 'claude-3-haiku-20240307', 'api_key': 'fake-key', 'chunk_config': {}, 'dependencies': ['extractor'], 'prompt': 'Classify this content: {extractor.summary}', 'output_schema': {'properties': {'category': {'type': 'string'}, 'confidence': {'type': 'number'}}}}, {'name': 'analyzer', 'agent_type': 'analyzer', 'model_vendor': 'anthropic', 'model_name': 'claude-3-haiku-20240307', 'api_key': 'fake-key', 'chunk_config': {}, 'dependencies': ['extractor', 'classifier'], 'prompt': '\n                    Analyze the extracted content:\n                    Summary: {extractor.summary}\n                    Entities: {extractor.entities}\n                    Category: {classifier.category}\n                    Confidence: {classifier.confidence}\n                    Document: {extractor.document_id}\n                    ', 'output_schema': {'properties': {'analysis': {'type': 'string'}, 'score': {'type': 'number'}}}}]}}
    defaults_data = {'default_agent_config': {'model_vendor': 'anthropic', 'model_name': 'claude-3-haiku-20240307', 'api_key': 'fake-key', 'chunk_config': {}}}
    yaml.dump(workflow_data, workflow_file, default_flow_style=False)
    yaml.dump(defaults_data, defaults_file, default_flow_style=False)
    workflow_file.close()
    defaults_file.close()
    yield (workflow_file.name, defaults_file.name)
    Path(workflow_file.name).unlink(missing_ok=True)
    Path(defaults_file.name).unlink(missing_ok=True)

@pytest.fixture
def conflict_workflow_files():
    """Create workflow with field conflicts for testing."""
    workflow_file = tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False, prefix='conflict_workflow_')
    defaults_file = tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False, prefix='defaults_')
    workflow_name = Path(workflow_file.name).stem
    workflow_data = {workflow_name: {'agents': [{'name': 'agent1', 'agent_type': 'agent1', 'model_vendor': 'anthropic', 'model_name': 'claude-3-haiku-20240307', 'api_key': 'fake-key', 'chunk_config': {}, 'output_schema': {'properties': {'summary': {'type': 'string'}, 'confidence': {'type': 'number'}}}}, {'name': 'agent2', 'agent_type': 'agent2', 'model_vendor': 'anthropic', 'model_name': 'claude-3-haiku-20240307', 'api_key': 'fake-key', 'chunk_config': {}, 'output_schema': {'properties': {'category': {'type': 'string'}, 'confidence': {'type': 'number'}}}}, {'name': 'combiner', 'agent_type': 'combiner', 'model_vendor': 'anthropic', 'model_name': 'claude-3-haiku-20240307', 'api_key': 'fake-key', 'chunk_config': {}, 'dependencies': ['agent1', 'agent2'], 'prompt': 'Combine: {agent1.summary} and {agent2.category}', 'output_schema': {'properties': {'result': {'type': 'string'}}}}]}}
    defaults_data = {'default_agent_config': {'model_vendor': 'anthropic', 'model_name': 'claude-3-haiku-20240307', 'api_key': 'fake-key', 'chunk_config': {}}}
    yaml.dump(workflow_data, workflow_file, default_flow_style=False)
    yaml.dump(defaults_data, defaults_file, default_flow_style=False)
    workflow_file.close()
    defaults_file.close()
    yield (workflow_file.name, defaults_file.name)
    Path(workflow_file.name).unlink(missing_ok=True)
    Path(defaults_file.name).unlink(missing_ok=True)

class TestCompleteWorkflowSignatureValidation:
    """Test complete workflow signature validation integration."""

    def test_complete_workflow_signature_validation(self, temp_workflow_files):
        """Test end-to-end workflow signature analysis."""
        workflow_path, defaults_path = temp_workflow_files
        config_manager = ConfigManager(workflow_path, defaults_path)
        config_manager.load_configs()
        config_manager.validate_agent_name()
        user_agents = config_manager.get_user_agents()
        config_manager.merge_agent_configs(user_agents)
        config_manager.determine_execution_order()
        all_signatures = config_manager.get_all_signatures()
        assert len(all_signatures) == 3
        assert 'extractor' in all_signatures
        assert 'classifier' in all_signatures
        assert 'analyzer' in all_signatures
        extractor_sig = all_signatures['extractor']
        assert extractor_sig['dependencies'] == []
        assert extractor_sig['execution_order_index'] == 0
        output_sig = extractor_sig['output_signature']
        assert set(output_sig.schema_fields) == {'summary', 'entities', 'metadata'}
        assert set(output_sig.observe_fields) == {'document_id', 'source_url'}
        assert output_sig.dropped_fields == ['metadata']
        expected_available = {'summary', 'entities', 'document_id', 'source_url'}
        assert output_sig.get_available_fields() == expected_available
        classifier_sig = all_signatures['classifier']
        assert classifier_sig['dependencies'] == ['extractor']
        assert classifier_sig['execution_order_index'] == 1
        input_sig = classifier_sig['input_signature']
        assert input_sig.dependencies == {'extractor': ['summary']}
        analyzer_sig = all_signatures['analyzer']
        assert analyzer_sig['dependencies'] == ['extractor', 'classifier']
        assert analyzer_sig['execution_order_index'] == 2
        analyzer_input = analyzer_sig['input_signature']
        expected_deps = {'extractor': ['summary', 'entities', 'document_id'], 'classifier': ['category', 'confidence']}
        assert analyzer_input.dependencies == expected_deps

    def test_field_flow_error_detection(self):
        """Test field flow validation detects missing field dependencies."""
        workflow_data = {'error_workflow': {'agents': [{'name': 'producer', 'agent_type': 'producer', 'model_vendor': 'anthropic', 'model_name': 'claude-3-haiku-20240307', 'api_key': 'fake-key', 'chunk_config': {}, 'output_schema': {'properties': {'available_field': {'type': 'string'}}}}, {'name': 'consumer', 'agent_type': 'consumer', 'model_vendor': 'anthropic', 'model_name': 'claude-3-haiku-20240307', 'api_key': 'fake-key', 'chunk_config': {}, 'dependencies': ['producer'], 'prompt': 'Use: {producer.missing_field}', 'output_schema': {'properties': {'result': {'type': 'string'}}}}]}}
        defaults_data = {'default_agent_config': {'model_vendor': 'anthropic', 'model_name': 'claude-3-haiku-20240307', 'api_key': 'fake-key', 'chunk_config': {}}}
        workflow_file = tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False, prefix='error_workflow_')
        workflow_name = Path(workflow_file.name).stem
        workflow_data = {workflow_name: workflow_data['error_workflow']}
        defaults_file = tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False, prefix='defaults_')
        yaml.dump(workflow_data, workflow_file)
        yaml.dump(defaults_data, defaults_file)
        workflow_file.close()
        defaults_file.close()
        workflow_path = workflow_file.name
        defaults_path = defaults_file.name
        try:
            config_manager = ConfigManager(workflow_path, defaults_path)
            config_manager.load_configs()
            config_manager.validate_agent_name()
            user_agents = config_manager.get_user_agents()
            config_manager.merge_agent_configs(user_agents)
            with pytest.raises(Exception) as exc_info:
                config_manager.determine_execution_order()
            assert 'input_signatures' in str(exc_info.value) or 'missing_field' in str(exc_info.value)
        finally:
            Path(workflow_path).unlink(missing_ok=True)
            Path(defaults_path).unlink(missing_ok=True)

    def test_conflict_detection_multiple_providers(self, conflict_workflow_files):
        """Test conflict detection identifies fields provided by multiple dependencies."""
        workflow_path, defaults_path = conflict_workflow_files
        config_manager = ConfigManager(workflow_path, defaults_path)
        config_manager.load_configs()
        config_manager.validate_agent_name()
        user_agents = config_manager.get_user_agents()
        config_manager.merge_agent_configs(user_agents)
        config_manager.determine_execution_order()
        conflicts = config_manager.detect_field_conflicts('combiner')
        assert 'conflicts' in conflicts
        assert 'confidence' in conflicts['conflicts']
        assert set(conflicts['conflicts']['confidence']) == {'agent1', 'agent2'}
        assert set(conflicts['agent_dependencies']) == {'agent1', 'agent2'}
        assert 'all_available_fields' in conflicts
        agent1_fields = conflicts['all_available_fields']['agent1']
        agent2_fields = conflicts['all_available_fields']['agent2']
        assert 'summary' in agent1_fields
        assert 'confidence' in agent1_fields
        assert 'category' in agent2_fields
        assert 'confidence' in agent2_fields

    def test_validate_field_flow_comprehensive(self, temp_workflow_files):
        """Test comprehensive field flow validation."""
        workflow_path, defaults_path = temp_workflow_files
        config_manager = ConfigManager(workflow_path, defaults_path)
        config_manager.load_configs()
        config_manager.validate_agent_name()
        user_agents = config_manager.get_user_agents()
        config_manager.merge_agent_configs(user_agents)
        config_manager.determine_execution_order()
        validation = config_manager.validate_field_flow()
        assert validation['valid'] is True
        assert validation['errors'] == []
        agent_validations = validation['agent_validations']
        assert len(agent_validations) == 3
        for agent_name in ['extractor', 'classifier', 'analyzer']:
            assert agent_name in agent_validations
            assert agent_validations[agent_name]['valid'] is True
            assert agent_validations[agent_name]['errors'] == []
        field_flow = validation['field_flow_summary']
        assert len(field_flow['extractor']) == 4
        assert len(field_flow['classifier']) == 6
        assert len(field_flow['analyzer']) == 8

    def test_signature_parity_with_existing_validation(self, temp_workflow_files):
        """Test signature validation consistency with InputSignatureValidator."""
        workflow_path, defaults_path = temp_workflow_files
        config_manager = ConfigManager(workflow_path, defaults_path)
        config_manager.load_configs()
        config_manager.validate_agent_name()
        user_agents = config_manager.get_user_agents()
        config_manager.merge_agent_configs(user_agents)
        config_manager.determine_execution_order()
        assert len(config_manager.execution_order) == 3
        assert config_manager.execution_order == ['extractor', 'classifier', 'analyzer']

class TestComplexWorkflowScenarios:
    """Test signature validation in complex workflow scenarios."""

    def test_large_workflow_performance(self):
        """Test signature validation performance with large workflows."""
        num_agents = 15
        agents = []
        for i in range(num_agents):
            agent = {'name': f'agent_{i}', 'agent_type': f'agent_{i}', 'model_vendor': 'anthropic', 'model_name': 'claude-3-haiku-20240307', 'api_key': 'fake-key', 'chunk_config': {}, 'output_schema': {'properties': {f'field_{i}': {'type': 'string'}}}}
            if i > 0:
                agent['dependencies'] = [f'agent_{i - 1}']
                agent['prompt'] = f'Process: {{agent_{i - 1}.field_{i - 1}}}'
            agents.append(agent)
        workflow_data = {'large_workflow': {'agents': agents}}
        defaults_data = {'default_agent_config': {'model_vendor': 'anthropic', 'model_name': 'claude-3-haiku-20240307', 'api_key': 'fake-key', 'chunk_config': {}}}
        workflow_file = tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False, prefix='large_workflow_')
        workflow_name = Path(workflow_file.name).stem
        workflow_data = {workflow_name: workflow_data['large_workflow']}
        defaults_file = tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False, prefix='defaults_')
        yaml.dump(workflow_data, workflow_file)
        yaml.dump(defaults_data, defaults_file)
        workflow_file.close()
        defaults_file.close()
        workflow_path = workflow_file.name
        defaults_path = defaults_file.name
        try:
            config_manager = ConfigManager(workflow_path, defaults_path)
            config_manager.load_configs()
            config_manager.validate_agent_name()
            user_agents = config_manager.get_user_agents()
            config_manager.merge_agent_configs(user_agents)
            config_manager.determine_execution_order()
            all_signatures = config_manager.get_all_signatures()
            validation = config_manager.validate_field_flow()
            assert len(all_signatures) == num_agents
            assert validation['valid'] is True
            assert len(config_manager.execution_order) == num_agents
        finally:
            Path(workflow_path).unlink(missing_ok=True)
            Path(defaults_path).unlink(missing_ok=True)

    def test_nested_field_path_validation(self):
        """Test signature validation with nested field paths."""
        workflow_data = {'nested_workflow': {'agents': [{'name': 'data_producer', 'agent_type': 'data_producer', 'model_vendor': 'anthropic', 'model_name': 'claude-3-haiku-20240307', 'api_key': 'fake-key', 'chunk_config': {}, 'output_schema': {'properties': {'data': {'type': 'object'}, 'metrics': {'type': 'object'}, 'results': {'type': 'array'}}}}, {'name': 'data_consumer', 'agent_type': 'data_consumer', 'model_vendor': 'anthropic', 'model_name': 'claude-3-haiku-20240307', 'api_key': 'fake-key', 'chunk_config': {}, 'dependencies': ['data_producer'], 'prompt': '\n                        Process nested data:\n                        Count: {data_producer.data.metrics.count}\n                        Value: {data_producer.results.items.0.value}\n                        Average: {data_producer.metrics.stats.average}\n                        ', 'output_schema': {'properties': {'processed': {'type': 'string'}}}}]}}
        defaults_data = {'default_agent_config': {'model_vendor': 'anthropic', 'model_name': 'claude-3-haiku-20240307', 'api_key': 'fake-key', 'chunk_config': {}}}
        workflow_file = tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False, prefix='nested_workflow_')
        workflow_name = Path(workflow_file.name).stem
        workflow_data = {workflow_name: workflow_data['nested_workflow']}
        defaults_file = tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False, prefix='defaults_')
        yaml.dump(workflow_data, workflow_file)
        yaml.dump(defaults_data, defaults_file)
        workflow_file.close()
        defaults_file.close()
        workflow_path = workflow_file.name
        defaults_path = defaults_file.name
        try:
            config_manager = ConfigManager(workflow_path, defaults_path)
            config_manager.load_configs()
            config_manager.validate_agent_name()
            user_agents = config_manager.get_user_agents()
            config_manager.merge_agent_configs(user_agents)
            config_manager.determine_execution_order()
            all_signatures = config_manager.get_all_signatures()
            consumer_sig = all_signatures['data_consumer']
            input_deps = consumer_sig['input_signature'].dependencies
            expected_fields = {'data.metrics.count', 'results.items.0.value', 'metrics.stats.average'}
            actual_fields = set(input_deps['data_producer'])
            assert actual_fields == expected_fields
        finally:
            Path(workflow_path).unlink(missing_ok=True)
            Path(defaults_path).unlink(missing_ok=True)

    def test_schema_registry_workflow_integration(self, temp_workflow_files):
        """Test workflow-level schema registry integration."""
        workflow_path, defaults_path = temp_workflow_files
        schema_registry = {'CustomSchema': {'properties': {'custom_field1': {'type': 'string'}, 'custom_field2': {'type': 'number'}}}}
        config_manager = ConfigManager(workflow_path, defaults_path)
        config_manager.load_configs()
        config_manager.validate_agent_name()
        user_agents = config_manager.get_user_agents()
        config_manager.merge_agent_configs(user_agents)
        config_manager.determine_execution_order()
        all_signatures = config_manager.get_all_signatures(schema_registry)
        validation = config_manager.validate_field_flow(schema_registry)
        assert len(all_signatures) == 3
        assert validation['valid'] is True
        conflicts = config_manager.detect_field_conflicts('analyzer', schema_registry)
        assert 'conflicts' in conflicts

class TestSignatureValidationEdgeCases:
    """Test edge cases in signature validation."""

    def test_empty_workflow_validation(self):
        """Test signature validation with empty workflow."""
        workflow_data = {'empty_workflow': {'agents': []}}
        defaults_data = {'default_agent_config': {}}
        workflow_file = tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False, prefix='empty_workflow_')
        workflow_name = Path(workflow_file.name).stem
        workflow_data = {workflow_name: workflow_data['empty_workflow']}
        defaults_file = tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False, prefix='defaults_')
        yaml.dump(workflow_data, workflow_file)
        yaml.dump(defaults_data, defaults_file)
        workflow_file.close()
        defaults_file.close()
        workflow_path = workflow_file.name
        defaults_path = defaults_file.name
        try:
            config_manager = ConfigManager(workflow_path, defaults_path)
            config_manager.load_configs()
            config_manager.validate_agent_name()
            user_agents = config_manager.get_user_agents()
            config_manager.merge_agent_configs(user_agents)
            config_manager.determine_execution_order()
            all_signatures = config_manager.get_all_signatures()
            validation = config_manager.validate_field_flow()
            assert all_signatures == {}
            assert validation['valid'] is True
            assert validation['errors'] == []
        finally:
            Path(workflow_path).unlink(missing_ok=True)
            Path(defaults_path).unlink(missing_ok=True)

    def test_single_agent_workflow(self):
        """Test signature validation with single agent workflow."""
        workflow_data = {'single_workflow': {'agents': [{'name': 'solo', 'agent_type': 'solo', 'model_vendor': 'anthropic', 'model_name': 'claude-3-haiku-20240307', 'api_key': 'fake-key', 'chunk_config': {}, 'output_schema': {'properties': {'result': {'type': 'string'}}}}]}}
        defaults_data = {'default_agent_config': {'model_vendor': 'anthropic', 'model_name': 'claude-3-haiku-20240307', 'api_key': 'fake-key', 'chunk_config': {}}}
        workflow_file = tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False, prefix='single_workflow_')
        workflow_name = Path(workflow_file.name).stem
        workflow_data = {workflow_name: workflow_data['single_workflow']}
        defaults_file = tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False, prefix='defaults_')
        yaml.dump(workflow_data, workflow_file)
        yaml.dump(defaults_data, defaults_file)
        workflow_file.close()
        defaults_file.close()
        workflow_path = workflow_file.name
        defaults_path = defaults_file.name
        try:
            config_manager = ConfigManager(workflow_path, defaults_path)
            config_manager.load_configs()
            config_manager.validate_agent_name()
            user_agents = config_manager.get_user_agents()
            config_manager.merge_agent_configs(user_agents)
            config_manager.determine_execution_order()
            all_signatures = config_manager.get_all_signatures()
            validation = config_manager.validate_field_flow()
            conflicts = config_manager.detect_field_conflicts('solo')
            assert len(all_signatures) == 1
            assert 'solo' in all_signatures
            assert validation['valid'] is True
            assert conflicts['conflicts'] == {}
        finally:
            Path(workflow_path).unlink(missing_ok=True)
            Path(defaults_path).unlink(missing_ok=True)