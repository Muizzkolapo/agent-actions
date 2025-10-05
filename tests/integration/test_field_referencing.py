"""
Integration tests for field referencing in DataGenerator.

These tests validate that {reference.field} patterns work end-to-end
when DataGenerator creates agents and formats prompts with real contexts.
"""

import pytest
from unittest.mock import patch, Mock
from agent_actions.agents.generators.data_generator import DataGenerator


class TestFieldReferencingIntegration:
    """Test field references work in real DataGenerator execution."""

    @patch('agent_actions.agents.generators.data_generator.run_dynamic_agent')
    def test_source_field_reference_integration(self, mock_run_agent):
        """Test {source.field} reference is replaced when agent executes."""
        # Setup
        agent_config = {
            'prompt': 'Process this content: {source.page_content}',
            'model_vendor': 'openai',
            'model_name': 'gpt-4o-mini'
        }
        source_content = {
            'page_content': 'This is the original input text'
        }
        contents = {}

        mock_run_agent.return_value = ([{'result': 'success'}], True)

        # Execute
        generator = DataGenerator(agent_config, 'test_agent')
        generator.create_agent_with_data(contents, source_content)

        # Verify the formatted prompt was passed to run_dynamic_agent
        call_args = mock_run_agent.call_args
        formatted_prompt = call_args[0][3]  # 4th positional arg is formatted_prompt

        assert 'This is the original input text' in formatted_prompt
        assert '{source.page_content}' not in formatted_prompt

    @patch('agent_actions.agents.generators.data_generator.run_dynamic_agent')
    def test_dependency_field_reference_integration(self, mock_run_agent):
        """Test {agent.field} reference accesses dependency output."""
        # Setup
        agent_config = {
            'prompt': 'Analyze these metrics: {extractor.metrics}',
            'model_vendor': 'openai',
            'model_name': 'gpt-4o-mini'
        }
        source_content = {'text': 'input'}
        contents = {
            'extractor': {
                'metrics': {'count': 5, 'accuracy': 0.95}
            }
        }

        mock_run_agent.return_value = ([{'result': 'analyzed'}], True)

        # Execute
        generator = DataGenerator(agent_config, 'analyzer')
        generator.create_agent_with_data(contents, source_content)

        # Verify
        call_args = mock_run_agent.call_args
        formatted_prompt = call_args[0][3]

        # Should contain JSON representation of metrics dict
        assert '"count": 5' in formatted_prompt
        assert '"accuracy": 0.95' in formatted_prompt
        assert '{extractor.metrics}' not in formatted_prompt

    @patch('agent_actions.agents.generators.data_generator.run_dynamic_agent')
    def test_nested_field_reference_integration(self, mock_run_agent):
        """Test {agent.nested.field} reference works."""
        # Setup
        agent_config = {
            'prompt': 'Report accuracy: {analyzer.results.metrics.accuracy}',
            'model_vendor': 'openai',
            'model_name': 'gpt-4o-mini'
        }
        source_content = {}
        contents = {
            'analyzer': {
                'results': {
                    'metrics': {
                        'accuracy': 0.87
                    }
                }
            }
        }

        mock_run_agent.return_value = ([{'report': 'done'}], True)

        # Execute
        generator = DataGenerator(agent_config, 'reporter')
        generator.create_agent_with_data(contents, source_content)

        # Verify
        call_args = mock_run_agent.call_args
        formatted_prompt = call_args[0][3]

        assert '0.87' in formatted_prompt
        assert '{analyzer.results.metrics.accuracy}' not in formatted_prompt

    @patch('agent_actions.agents.generators.data_generator.run_dynamic_agent')
    def test_multiple_field_references_integration(self, mock_run_agent):
        """Test multiple field references in same prompt."""
        # Setup
        agent_config = {
            'prompt': '''
Source title: {source.title}
Extractor summary: {extractor.summary}
Classifier label: {classifier.label}
''',
            'model_vendor': 'openai',
            'model_name': 'gpt-4o-mini'
        }
        source_content = {'title': 'Test Document'}
        contents = {
            'extractor': {'summary': 'A test summary'},
            'classifier': {'label': 'positive'}
        }

        mock_run_agent.return_value = ([{'combined': 'result'}], True)

        # Execute
        generator = DataGenerator(agent_config, 'combiner')
        generator.create_agent_with_data(contents, source_content)

        # Verify all references replaced
        call_args = mock_run_agent.call_args
        formatted_prompt = call_args[0][3]

        assert 'Test Document' in formatted_prompt
        assert 'A test summary' in formatted_prompt
        assert 'positive' in formatted_prompt
        assert '{source.title}' not in formatted_prompt
        assert '{extractor.summary}' not in formatted_prompt
        assert '{classifier.label}' not in formatted_prompt

    @patch('agent_actions.agents.generators.data_generator.run_dynamic_agent')
    def test_loop_context_integration(self, mock_run_agent):
        """Test {loop.*} references work when loop_context provided."""
        # Setup
        agent_config = {
            'prompt': 'Processing review {loop.index} of {loop.total}: {loop.item.text}',
            'model_vendor': 'openai',
            'model_name': 'gpt-4o-mini'
        }
        source_content = {}
        contents = {}
        loop_context = {
            'index': 2,
            'total': 5,
            'item': {
                'text': 'Great product!',
                'rating': 5
            }
        }

        mock_run_agent.return_value = ([{'sentiment': 'positive'}], True)

        # Execute
        generator = DataGenerator(agent_config, 'sentiment_analyzer')
        generator.create_agent_with_data(contents, source_content, loop_context=loop_context)

        # Verify
        call_args = mock_run_agent.call_args
        formatted_prompt = call_args[0][3]

        assert 'Processing review 2 of 5' in formatted_prompt
        assert 'Great product!' in formatted_prompt
        assert '{loop.index}' not in formatted_prompt
        assert '{loop.total}' not in formatted_prompt
        assert '{loop.item.text}' not in formatted_prompt

    @patch('agent_actions.agents.generators.data_generator.run_dynamic_agent')
    def test_workflow_metadata_integration(self, mock_run_agent):
        """Test {workflow.*} references work when workflow_metadata provided."""
        # Setup
        agent_config = {
            'prompt': 'Running workflow: {workflow.name} v{workflow.version} (Run: {workflow.run_id})',
            'model_vendor': 'openai',
            'model_name': 'gpt-4o-mini'
        }
        source_content = {}
        contents = {}
        workflow_metadata = {
            'name': 'customer_review_analysis',
            'version': '1.2.0',
            'run_id': 'run-abc123-xyz'
        }

        mock_run_agent.return_value = ([{'processed': True}], True)

        # Execute
        generator = DataGenerator(agent_config, 'processor')
        generator.create_agent_with_data(contents, source_content, workflow_metadata=workflow_metadata)

        # Verify
        call_args = mock_run_agent.call_args
        formatted_prompt = call_args[0][3]

        assert 'Running workflow: customer_review_analysis v1.2.0' in formatted_prompt
        assert 'Run: run-abc123-xyz' in formatted_prompt
        assert '{workflow.name}' not in formatted_prompt
        assert '{workflow.version}' not in formatted_prompt
        assert '{workflow.run_id}' not in formatted_prompt

    @patch('agent_actions.agents.generators.data_generator.run_dynamic_agent')
    def test_mixed_references_integration(self, mock_run_agent):
        """Test all reference types work together in one prompt."""
        # Setup
        agent_config = {
            'prompt': '''
[{workflow.name}] Processing review {loop.index}:
Source: {source.title}
Previous analysis: {extractor.summary}
Current review: {loop.item.text}
''',
            'model_vendor': 'openai',
            'model_name': 'gpt-4o-mini'
        }
        source_content = {'title': 'Product Reviews'}
        contents = {
            'extractor': {'summary': 'Mostly positive feedback'}
        }
        loop_context = {
            'index': 3,
            'item': {'text': 'Excellent quality'}
        }
        workflow_metadata = {'name': 'review_pipeline'}

        mock_run_agent.return_value = ([{'analyzed': True}], True)

        # Execute
        generator = DataGenerator(agent_config, 'analyzer')
        generator.create_agent_with_data(
            contents,
            source_content,
            loop_context=loop_context,
            workflow_metadata=workflow_metadata
        )

        # Verify all reference types resolved
        call_args = mock_run_agent.call_args
        formatted_prompt = call_args[0][3]

        assert '[review_pipeline] Processing review 3' in formatted_prompt
        assert 'Product Reviews' in formatted_prompt
        assert 'Mostly positive feedback' in formatted_prompt
        assert 'Excellent quality' in formatted_prompt

        # No unresolved references
        assert '{workflow.' not in formatted_prompt
        assert '{loop.' not in formatted_prompt
        assert '{source.' not in formatted_prompt
        assert '{extractor.' not in formatted_prompt

    @patch('agent_actions.agents.generators.data_generator.run_dynamic_agent')
    def test_array_index_reference_integration(self, mock_run_agent):
        """Test {agent.array.0} array index access works."""
        # Setup
        agent_config = {
            'prompt': 'First item: {extractor.items.0}, Second: {extractor.items.1}',
            'model_vendor': 'openai',
            'model_name': 'gpt-4o-mini'
        }
        source_content = {}
        contents = {
            'extractor': {
                'items': ['alpha', 'beta', 'gamma']
            }
        }

        mock_run_agent.return_value = ([{'result': 'ok'}], True)

        # Execute
        generator = DataGenerator(agent_config, 'selector')
        generator.create_agent_with_data(contents, source_content)

        # Verify
        call_args = mock_run_agent.call_args
        formatted_prompt = call_args[0][3]

        assert 'First item: alpha, Second: beta' in formatted_prompt
        assert '{extractor.items.0}' not in formatted_prompt

    def test_missing_reference_raises_clear_error(self):
        """Test that missing reference raises helpful error."""
        # Setup
        agent_config = {
            'prompt': 'Use data from: {unknown_agent.field}',
            'model_vendor': 'openai',
            'model_name': 'gpt-4o-mini'
        }
        source_content = {}
        contents = {'extractor': {'data': 'test'}}

        # Execute and expect error
        generator = DataGenerator(agent_config, 'test_agent')

        with pytest.raises(Exception) as exc_info:
            generator.create_agent_with_data(contents, source_content)

        # Verify error message is helpful
        error_message = str(exc_info.value)
        assert 'unknown_agent' in error_message
        assert 'not found' in error_message or 'Available' in error_message

    def test_missing_field_raises_clear_error(self):
        """Test that missing field raises helpful error."""
        # Setup
        agent_config = {
            'prompt': 'Get metrics: {extractor.missing_field}',
            'model_vendor': 'openai',
            'model_name': 'gpt-4o-mini'
        }
        source_content = {}
        contents = {'extractor': {'data': 'test', 'summary': 'text'}}

        # Execute and expect error
        generator = DataGenerator(agent_config, 'test_agent')

        with pytest.raises(Exception) as exc_info:
            generator.create_agent_with_data(contents, source_content)

        # Verify error message is helpful
        error_message = str(exc_info.value)
        assert 'missing_field' in error_message
        assert 'not found' in error_message
