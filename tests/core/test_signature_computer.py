"""
Tests for SignatureComputer logic.

This module tests the SignatureComputer class which implements the core
signature computation logic.
"""
import pytest
from typing import Dict, Any, Optional
from agent_actions.state_management.signature_computer import SignatureComputer
from agent_actions.state_management.signatures import InputSignature, OutputSignature

class TestSignatureComputerOutputSignature:
    """Test SignatureComputer output signature computation."""

    def test_compute_output_signature_with_schema(self):
        """Test output signature computation with schema fields."""
        agent_config = {'output_schema': {'properties': {'summary': {'type': 'string'}, 'entities': {'type': 'array'}, 'metadata': {'type': 'object'}}}, 'observe': [], 'drops': []}
        signature = SignatureComputer.compute_output_signature(agent_config)
        assert isinstance(signature, OutputSignature)
        assert set(signature.schema_fields) == {'summary', 'entities', 'metadata'}
        assert signature.observe_fields == []
        assert signature.dropped_fields == []
        assert signature.get_available_fields() == {'summary', 'entities', 'metadata'}

    def test_compute_output_signature_with_observe_drops(self):
        """Test output signature computation with observe and drops."""
        agent_config = {'output_schema': {'properties': {'analysis': {'type': 'string'}, 'temp_data': {'type': 'object'}}}, 'observe': ['document_id', 'source_url'], 'drops': ['temp_data', 'source_url']}
        signature = SignatureComputer.compute_output_signature(agent_config)
        assert set(signature.schema_fields) == {'analysis', 'temp_data'}
        assert set(signature.observe_fields) == {'document_id', 'source_url'}
        assert set(signature.dropped_fields) == {'temp_data', 'source_url'}
        assert signature.get_available_fields() == {'analysis', 'document_id'}

    def test_compute_output_signature_empty_schema(self):
        """Test output signature with empty schema."""
        agent_config = {'output_schema': {}, 'observe': ['field1', 'field2'], 'drops': ['field1']}
        signature = SignatureComputer.compute_output_signature(agent_config)
        assert signature.schema_fields == []
        assert set(signature.observe_fields) == {'field1', 'field2'}
        assert signature.dropped_fields == ['field1']
        assert signature.get_available_fields() == {'field2'}

    def test_compute_output_signature_no_properties(self):
        """Test output signature when schema has no properties."""
        agent_config = {'output_schema': {'type': 'object'}, 'observe': ['document_id'], 'drops': []}
        signature = SignatureComputer.compute_output_signature(agent_config)
        assert signature.schema_fields == []
        assert signature.observe_fields == ['document_id']
        assert signature.get_available_fields() == {'document_id'}

    def test_compute_output_signature_with_schema_registry(self):
        """Test output signature with schema registry for string references."""
        agent_config = {'output_schema': 'ExtractorSchema', 'observe': ['metadata'], 'drops': []}
        schema_registry = {'ExtractorSchema': {'properties': {'title': {'type': 'string'}, 'content': {'type': 'string'}}}}
        signature = SignatureComputer.compute_output_signature(agent_config, schema_registry)
        assert set(signature.schema_fields) == {'title', 'content'}
        assert signature.observe_fields == ['metadata']
        assert signature.get_available_fields() == {'title', 'content', 'metadata'}

    def test_compute_output_signature_missing_schema_registry(self):
        """Test output signature with string reference but no registry."""
        agent_config = {'output_schema': 'MissingSchema', 'observe': ['field1'], 'drops': []}
        signature = SignatureComputer.compute_output_signature(agent_config)
        assert signature.schema_fields == []
        assert signature.observe_fields == ['field1']
        assert signature.get_available_fields() == {'field1'}

    def test_compute_output_signature_missing_schema_in_registry(self):
        """Test output signature with string reference not in registry."""
        agent_config = {'output_schema': 'NonExistentSchema', 'observe': ['field1'], 'drops': []}
        schema_registry = {'ExistingSchema': {'properties': {'field': {}}}}
        signature = SignatureComputer.compute_output_signature(agent_config, schema_registry)
        assert signature.schema_fields == []
        assert signature.observe_fields == ['field1']
        assert signature.get_available_fields() == {'field1'}

class TestSignatureComputerInputSignature:
    """Test SignatureComputer input signature computation."""

    def test_compute_input_signature_from_prompt(self):
        """Test input signature computation from prompt parsing."""
        agent_config = {'prompt': 'Analyze: {extractor.summary} and {classifier.category}. Document: {source.title}', 'dependencies': ['extractor', 'classifier']}
        dependency_configs = {'extractor': {'output_schema': {'properties': {'summary': {}, 'entities': {}}}, 'observe': [], 'drops': []}, 'classifier': {'output_schema': {'properties': {'category': {}, 'confidence': {}}}, 'observe': [], 'drops': []}}
        signature = SignatureComputer.compute_input_signature(agent_config, dependency_configs)
        assert isinstance(signature, InputSignature)
        expected_deps = {'extractor': ['summary'], 'classifier': ['category']}
        assert signature.dependencies == expected_deps
        assert 'title' in signature.source_fields
        all_fields = signature.get_all_fields()
        assert 'summary' in all_fields
        assert 'category' in all_fields
        assert 'title' in all_fields

    def test_compute_input_signature_no_prompt(self):
        """Test input signature when no prompt is provided."""
        agent_config = {'dependencies': ['extractor']}
        dependency_configs = {'extractor': {'output_schema': {'properties': {'summary': {}}}, 'observe': [], 'drops': []}}
        signature = SignatureComputer.compute_input_signature(agent_config, dependency_configs)
        assert signature.dependencies == {}
        assert signature.source_fields == []
        assert signature.get_all_fields() == set()

    def test_compute_input_signature_empty_prompt(self):
        """Test input signature with empty prompt."""
        agent_config = {'prompt': '', 'dependencies': ['extractor']}
        dependency_configs = {'extractor': {'output_schema': {'properties': {'summary': {}}}, 'observe': [], 'drops': []}}
        signature = SignatureComputer.compute_input_signature(agent_config, dependency_configs)
        assert signature.dependencies == {}
        assert signature.source_fields == []
        assert signature.get_all_fields() == set()

    def test_compute_input_signature_loop_references(self):
        """Test input signature with loop field references."""
        agent_config = {'prompt': 'Processing item {loop.index} of {loop.total} with data {loop.item.text}', 'dependencies': []}
        signature = SignatureComputer.compute_input_signature(agent_config, {})
        expected_loop_fields = ['index', 'total', 'item.text']
        assert signature.loop_fields == expected_loop_fields
        assert 'index' in signature.get_all_fields()
        assert 'total' in signature.get_all_fields()
        assert 'item.text' in signature.get_all_fields()

    def test_compute_input_signature_workflow_references(self):
        """Test input signature with workflow field references."""
        agent_config = {'prompt': 'Workflow {workflow.name} version {workflow.version} run {workflow.run_id}', 'dependencies': []}
        signature = SignatureComputer.compute_input_signature(agent_config, {})
        expected_workflow_fields = ['name', 'version', 'run_id']
        assert signature.workflow_fields == expected_workflow_fields
        assert 'name' in signature.get_all_fields()
        assert 'version' in signature.get_all_fields()
        assert 'run_id' in signature.get_all_fields()

    def test_compute_input_signature_mixed_references(self):
        """Test input signature with mixed field reference types."""
        agent_config = {'prompt': '\n            Source: {source.title}\n            Workflow: {workflow.name}\n            Loop: {loop.index}\n            Agent: {extractor.summary}\n            ', 'dependencies': ['extractor']}
        dependency_configs = {'extractor': {'output_schema': {'properties': {'summary': {}, 'entities': {}}}, 'observe': [], 'drops': []}}
        signature = SignatureComputer.compute_input_signature(agent_config, dependency_configs)
        assert signature.dependencies == {'extractor': ['summary']}
        assert 'title' in signature.source_fields
        assert 'name' in signature.workflow_fields
        assert 'index' in signature.loop_fields
        all_fields = signature.get_all_fields()
        assert all_fields == {'title', 'name', 'index', 'summary'}

    def test_compute_input_signature_nested_field_paths(self):
        """Test input signature with nested field paths."""
        agent_config = {'prompt': 'Data: {extractor.data.metrics.count} and {extractor.results.items.0.value}', 'dependencies': ['extractor']}
        dependency_configs = {'extractor': {'output_schema': {'properties': {'data': {}, 'results': {}}}, 'observe': [], 'drops': []}}
        signature = SignatureComputer.compute_input_signature(agent_config, dependency_configs)
        assert signature.dependencies == {'extractor': ['data.metrics.count', 'results.items.0.value']}
        assert signature.get_all_fields() == {'data.metrics.count', 'results.items.0.value'}

    def test_dependency_field_extraction(self):
        """Test dependency field extraction accuracy."""
        agent_config = {'prompt': 'Fields: {agent1.field1} {agent1.field2} {agent2.field3}', 'dependencies': ['agent1', 'agent2']}
        dependency_configs = {'agent1': {'output_schema': {'properties': {'field1': {}, 'field2': {}, 'other': {}}}, 'observe': [], 'drops': []}, 'agent2': {'output_schema': {'properties': {'field3': {}, 'field4': {}}}, 'observe': [], 'drops': []}}
        signature = SignatureComputer.compute_input_signature(agent_config, dependency_configs)
        expected_deps = {'agent1': ['field1', 'field2'], 'agent2': ['field3']}
        assert signature.dependencies == expected_deps

class TestSignatureComputerFieldAvailability:
    """Test SignatureComputer field availability validation."""

    def test_validate_field_availability_valid(self):
        """Test field availability validation with valid references."""
        input_signature = InputSignature(dependencies={'extractor': ['summary', 'entities']}, source_fields=['title'])
        dependency_signatures = {'extractor': OutputSignature(schema_fields=['summary', 'entities', 'metadata'], observe_fields=['document_id'], dropped_fields=['metadata'])}
        validation = SignatureComputer.validate_field_availability(input_signature, dependency_signatures)
        assert validation['valid'] is True
        assert validation['errors'] == []

    def test_validate_field_availability_missing_fields(self):
        """Test field availability validation with missing fields."""
        input_signature = InputSignature(dependencies={'extractor': ['summary', 'missing_field']}, source_fields=[])
        dependency_signatures = {'extractor': OutputSignature(schema_fields=['summary', 'entities'], observe_fields=[], dropped_fields=[])}
        validation = SignatureComputer.validate_field_availability(input_signature, dependency_signatures)
        assert validation['valid'] is False
        assert len(validation['errors']) == 1
        assert 'missing_field' in validation['errors'][0]
        assert 'extractor' in validation['errors'][0]

    def test_validate_field_availability_dropped_fields(self):
        """Test field availability validation with dropped fields."""
        input_signature = InputSignature(dependencies={'extractor': ['summary', 'metadata']}, source_fields=[])
        dependency_signatures = {'extractor': OutputSignature(schema_fields=['summary', 'metadata'], observe_fields=[], dropped_fields=['metadata'])}
        validation = SignatureComputer.validate_field_availability(input_signature, dependency_signatures)
        assert validation['valid'] is False
        assert len(validation['errors']) == 1
        assert 'metadata' in validation['errors'][0]
        assert 'not available' in validation['errors'][0]

    def test_validate_field_availability_missing_dependency(self):
        """Test field availability validation with missing dependency."""
        input_signature = InputSignature(dependencies={'missing_agent': ['field1']}, source_fields=[])
        dependency_signatures = {}
        validation = SignatureComputer.validate_field_availability(input_signature, dependency_signatures)
        assert validation['valid'] is False
        assert len(validation['errors']) == 1
        assert 'missing_agent' in validation['errors'][0]
        assert 'not found' in validation['errors'][0]

class TestSignatureComputerErrorHandling:
    """Test SignatureComputer error handling scenarios."""

    def test_compute_output_signature_invalid_config(self):
        """Test output signature computation with invalid config."""
        agent_config = {'observe': ['field1'], 'drops': []}
        signature = SignatureComputer.compute_output_signature(agent_config)
        assert signature.schema_fields == []
        assert signature.observe_fields == ['field1']

    def test_compute_input_signature_missing_dependencies(self):
        """Test input signature with missing dependency configs."""
        agent_config = {'prompt': 'Use {missing_agent.field}', 'dependencies': ['missing_agent']}
        dependency_configs = {}
        signature = SignatureComputer.compute_input_signature(agent_config, dependency_configs)
        assert signature.dependencies == {}
        assert signature.get_all_fields() == set()

    def test_compute_signature_with_malformed_schema(self):
        """Test signature computation with malformed schema."""
        agent_config = {'output_schema': 'not_a_dict_or_string', 'observe': [], 'drops': []}
        signature = SignatureComputer.compute_output_signature(agent_config)
        assert signature.schema_fields == []

    def test_schema_registry_integration_edge_cases(self):
        """Test schema registry integration with edge cases."""
        agent_config = {'output_schema': 'TestSchema'}
        signature = SignatureComputer.compute_output_signature(agent_config, {})
        assert signature.schema_fields == []
        signature = SignatureComputer.compute_output_signature(agent_config, None)
        assert signature.schema_fields == []
        malformed_registry = {'TestSchema': 'not_a_dict'}
        signature = SignatureComputer.compute_output_signature(agent_config, malformed_registry)
        assert signature.schema_fields == []