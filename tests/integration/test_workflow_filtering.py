import pytest
import yaml
import tempfile
import os
import json
from unittest.mock import patch
from agent_actions.core.graph.agent_workflow import AgentWorkflow
from agent_actions.tasks.services.batch_service import BatchService
from agent_actions.core.parser.where_parser import WhereClauseParser


class TestWorkflowIntegration:
    """Integration tests for WHERE clause filtering in workflows"""

    @pytest.fixture
    def sample_config(self):
        return {
            'agents': [
                {
                    'agent_type': 'FilterAgent',
                    'model_vendor': 'openai',
                    'model_name': 'gpt-3.5-turbo',
                    'where_clause': {
                        'clause': 'questionable != "Low Value"',
                        'scope': 'item',
                        'passthrough_on_empty': True
                    }
                },
                {
                    'agent_type': 'ProcessAgent',
                    'dependencies': ['FilterAgent'],
                    'skip_if': 'len(previous_outputs.get("FilterAgent", [])) == 0'
                }
            ]
        }

    @pytest.fixture
    def sample_data(self):
        return [
            {
                "id": "1",
                "questionable": "Low Value",
                "why_questionable": "Basic content",
                "content": "Simple text"
            },
            {
                "id": "2",
                "questionable": "High Value",
                "why_questionable": "Complex analysis",
                "content": "Detailed analysis content"
            },
            {
                "id": "3",
                "questionable": "Medium Value",
                "why_questionable": "Moderate complexity",
                "content": "Standard content"
            }
        ]

    def test_agent_skip_condition(self, sample_config):
        workflow = AgentWorkflow.__new__(AgentWorkflow)
        workflow.where_parser = WhereClauseParser()
        from rich.console import Console
        workflow.console = Console()
        agent_config = sample_config['agents'][1]
        previous_outputs = {"FilterAgent": []}
        assert workflow._should_skip_agent(agent_config, previous_outputs) is True
        previous_outputs = {"FilterAgent": [{"id": "1", "data": "test"}]}
        assert workflow._should_skip_agent(agent_config, previous_outputs) is False

    def test_item_level_filtering(self, sample_data):
        config = {
            'where_clause': {
                'clause': 'questionable != "Low Value"',
                'scope': 'item',
                'passthrough_on_empty': True
            }
        }
        batch_service = BatchService()
        filtered_items = [
            item for item in sample_data
            if batch_service._should_process_item(item, config)
        ]
        assert len(filtered_items) == 2
        assert all(item['questionable'] != "Low Value" for item in filtered_items)
        assert filtered_items[0]['id'] == "2"
        assert filtered_items[1]['id'] == "3"

    def test_complex_where_clause_filtering(self, sample_data):
        for item in sample_data:
            item['score'] = 50 if item['questionable'] == "Low Value" else 80
        config = {
            'where_clause': {
                'clause': 'questionable != "Low Value" AND score >= 70',
                'scope': 'item'
            }
        }
        batch_service = BatchService()
        filtered_items = [
            item for item in sample_data
            if batch_service._should_process_item(item, config)
        ]
        assert len(filtered_items) == 2
        assert all(item['score'] >= 70 for item in filtered_items)

    def test_nested_field_filtering(self, sample_data):
        for item in sample_data:
            item['metadata'] = {
                'quality_score': 30 if item['questionable'] == "Low Value" else 85,
                'source': 'trusted'
            }
        config = {
            'where_clause': {
                'clause': 'metadata.quality_score > 50',
                'scope': 'item'
            }
        }
        batch_service = BatchService()
        filtered_items = [
            item for item in sample_data
            if batch_service._should_process_item(item, config)
        ]
        assert len(filtered_items) == 2
        assert all(item['metadata']['quality_score'] > 50 for item in filtered_items)

    def test_backwards_compatibility(self, sample_data):
        config = {
            'conditional_clause': 'row_content.get("questionable") != "Low Value"'
        }
        batch_service = BatchService()
        with patch('agent_actions.services.batch_service.execute_user_defined_function') as mock_func:
            mock_func.side_effect = lambda clause, data: data.get("questionable") != "Low Value"
            filtered_items = [
                item for item in sample_data
                if batch_service._should_process_item(item, config)
            ]
            assert len(filtered_items) == 2
            mock_func.assert_called()

    def test_error_handling_in_filtering(self, sample_data):
        config = {
            'where_clause': {
                'clause': 'invalid.field.path > 5',
                'scope': 'item',
                'passthrough_on_empty': True
            }
        }
        batch_service = BatchService()
        results = []
        for item in sample_data:
            try:
                should_process = batch_service._should_process_item(item, config)
                results.append(should_process)
            except Exception:
                pytest.fail("Should not raise exception on invalid field access")
        assert all(results)

    def test_passthrough_creation(self, sample_config):
        with tempfile.TemporaryDirectory() as temp_dir:
            workflow = AgentWorkflow.__new__(AgentWorkflow)
            workflow.where_parser = WhereClauseParser()
            from rich.console import Console
            workflow.console = Console()
            workflow.agent_runner = type('AR', (), {'get_agent_folder': lambda self, name: temp_dir})()
            workflow.execution_order = ['FilterAgent']
            workflow.agent_name = 'Workflow'
            workflow._create_passthrough_output(0, 'TestAgent')
            expected_dir = os.path.join(temp_dir, 'target', 'node_0_TestAgent')
            expected_file = os.path.join(expected_dir, '.agent_skipped')
            assert os.path.exists(expected_dir)
            assert os.path.exists(expected_file)
            with open(expected_file, 'r') as fh:
                content = fh.read()
                assert 'TestAgent' in content
                assert 'skipped' in content.lower()


class TestBatchServiceIntegration:
    """Integration tests for batch service filtering"""

    def test_batch_processing_with_filtering(self):
        sample_batch = [
            {"id": "1", "questionable": "Low Value", "content": "Basic"},
            {"id": "2", "questionable": "High Value", "content": "Advanced"},
            {"id": "3", "questionable": "Medium Value", "content": "Standard"}
        ]
        agent_config = {
            'where_clause': {
                'clause': 'questionable != "Low Value"',
                'scope': 'item'
            }
        }
        batch_service = BatchService()
        with patch.object(batch_service, '_process_batch') as mock_process:
            mock_process.return_value = {"results": "processed"}
            filtered_batch = [
                item for item in sample_batch
                if batch_service._should_process_item(item, agent_config)
            ]
            assert len(filtered_batch) == 2
            assert all(item['questionable'] != "Low Value" for item in filtered_batch)

    def test_mixed_filtering_modes(self):
        sample_data = [
            {"id": "1", "status": "active", "score": 80, "questionable": "High Value"},
            {"id": "2", "status": "inactive", "score": 90, "questionable": "High Value"},
            {"id": "3", "status": "active", "score": 60, "questionable": "Low Value"}
        ]
        config = {
            'conditional_clause': 'row_content.get("status") == "active"',
            'where_clause': {
                'clause': 'score >= 70',
                'scope': 'item'
            }
        }
        batch_service = BatchService()
        with patch('agent_actions.services.batch_service.execute_user_defined_function') as mock_func:
            mock_func.side_effect = lambda clause, data: data.get("status") == "active"
            filtered_items = [
                item for item in sample_data
                if batch_service._should_process_item(item, config)
            ]
            assert len(filtered_items) == 1
            assert filtered_items[0]['id'] == "1"
