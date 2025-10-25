"""Tests for DataGenerator._build_namespaced_field_context() method."""
import pytest
from agent_actions.prompt_generation.data_generator import DataGenerator

class TestBuildNamespacedFieldContext:
    """Test the _build_namespaced_field_context method."""

    def test_builds_namespaced_context_with_dependency_configs(self):
        """Test that fields are grouped by agent based on output signature."""
        agent_config = {'dependencies': ['agent_A']}
        agent_name = 'test_agent'
        dependency_configs = {'agent_A': {'output_schema': {'properties': {'field1': {}, 'field2': {}}}}}
        generator = DataGenerator(agent_config, agent_name, dependency_configs)
        contents = {'field1': 'value1', 'field2': 'value2', 'field3': 'value3'}
        field_context = generator._build_namespaced_field_context(contents)
        assert 'agent_A' in field_context
        assert field_context['agent_A'] == {'field1': 'value1', 'field2': 'value2'}
        assert 'field3' not in field_context['agent_A']

    def test_handles_observe_fields_correctly(self):
        """Test that observe fields are included in agent's namespace."""
        agent_config = {'dependencies': ['agent_A']}
        agent_name = 'test_agent'
        dependency_configs = {'agent_A': {'output_schema': {'properties': {'result': {}}}, 'observe': ['id', 'metadata']}}
        generator = DataGenerator(agent_config, agent_name, dependency_configs)
        contents = {'result': 'success', 'id': '123', 'metadata': {'key': 'value'}}
        field_context = generator._build_namespaced_field_context(contents)
        assert 'agent_A' in field_context
        assert field_context['agent_A'] == {'result': 'success', 'id': '123', 'metadata': {'key': 'value'}}

    def test_handles_drops_correctly(self):
        """Test that dropped fields are excluded from agent's namespace."""
        agent_config = {'dependencies': ['agent_A']}
        agent_name = 'test_agent'
        dependency_configs = {'agent_A': {'output_schema': {'properties': {'field1': {}, 'field2': {}}}, 'drops': ['field2']}}
        generator = DataGenerator(agent_config, agent_name, dependency_configs)
        contents = {'field1': 'v1', 'field2': 'v2'}
        field_context = generator._build_namespaced_field_context(contents)
        assert 'agent_A' in field_context
        assert field_context['agent_A'] == {'field1': 'v1'}
        assert 'field2' not in field_context['agent_A']

    def test_backward_compatible_without_dependency_configs(self):
        """Test that no namespacing happens when dependency_configs not provided."""
        agent_config = {'dependencies': ['agent_A']}
        agent_name = 'test_agent'
        dependency_configs = {}
        generator = DataGenerator(agent_config, agent_name, dependency_configs)
        contents = {'field1': 'v1', 'field2': 'v2'}
        field_context = generator._build_namespaced_field_context(contents)
        assert 'agent_A' not in field_context
        assert field_context == {}

    def test_multiple_dependencies(self):
        """Test that multiple dependencies are correctly namespaced."""
        agent_config = {'dependencies': ['agent_A', 'agent_B']}
        agent_name = 'test_agent'
        dependency_configs = {'agent_A': {'output_schema': {'properties': {'field1': {}, 'field2': {}}}}, 'agent_B': {'output_schema': {'properties': {'field3': {}, 'field4': {}}}}}
        generator = DataGenerator(agent_config, agent_name, dependency_configs)
        contents = {'field1': 'v1', 'field2': 'v2', 'field3': 'v3', 'field4': 'v4'}
        field_context = generator._build_namespaced_field_context(contents)
        assert 'agent_A' in field_context
        assert field_context['agent_A'] == {'field1': 'v1', 'field2': 'v2'}
        assert 'agent_B' in field_context
        assert field_context['agent_B'] == {'field3': 'v3', 'field4': 'v4'}

    def test_preserves_source_context(self):
        """Test that source content is preserved in field_context."""
        agent_config = {'dependencies': ['agent_A']}
        agent_name = 'test_agent'
        dependency_configs = {'agent_A': {'output_schema': {'properties': {'field1': {}}}}}
        generator = DataGenerator(agent_config, agent_name, dependency_configs)
        contents = {'field1': 'v1'}
        source_content = {'text': 'source text'}
        field_context = generator._build_namespaced_field_context(contents, source_content=source_content)
        assert 'source' in field_context
        assert field_context['source'] == {'text': 'source text'}
        assert 'agent_A' in field_context

    def test_preserves_loop_context(self):
        """Test that loop context is preserved alongside agent namespaces."""
        agent_config = {'dependencies': ['agent_A']}
        agent_name = 'test_agent'
        dependency_configs = {'agent_A': {'output_schema': {'properties': {'field1': {}}}}}
        generator = DataGenerator(agent_config, agent_name, dependency_configs)
        contents = {'field1': 'v1'}
        loop_context = {'index': 0, 'total': 5}
        field_context = generator._build_namespaced_field_context(contents, loop_context=loop_context)
        assert 'loop' in field_context
        assert field_context['loop'] == {'index': 0, 'total': 5}
        assert 'agent_A' in field_context

    def test_preserves_workflow_metadata(self):
        """Test that workflow metadata is preserved alongside agent namespaces."""
        agent_config = {'dependencies': ['agent_A']}
        agent_name = 'test_agent'
        dependency_configs = {'agent_A': {'output_schema': {'properties': {'field1': {}}}}}
        generator = DataGenerator(agent_config, agent_name, dependency_configs)
        contents = {'field1': 'v1'}
        workflow_metadata = {'name': 'test_workflow', 'version': '1.0'}
        field_context = generator._build_namespaced_field_context(contents, workflow_metadata=workflow_metadata)
        assert 'workflow' in field_context
        assert field_context['workflow'] == {'name': 'test_workflow', 'version': '1.0'}
        assert 'agent_A' in field_context

    def test_all_contexts_together(self):
        """Test that all contexts (source, agent, loop, workflow) coexist properly."""
        agent_config = {'dependencies': ['agent_A']}
        agent_name = 'test_agent'
        dependency_configs = {'agent_A': {'output_schema': {'properties': {'field1': {}}}}}
        generator = DataGenerator(agent_config, agent_name, dependency_configs)
        contents = {'field1': 'v1'}
        source_content = {'text': 'source'}
        loop_context = {'index': 0}
        workflow_metadata = {'name': 'test'}
        field_context = generator._build_namespaced_field_context(contents, source_content=source_content, loop_context=loop_context, workflow_metadata=workflow_metadata)
        assert 'source' in field_context
        assert 'agent_A' in field_context
        assert 'loop' in field_context
        assert 'workflow' in field_context
        assert len(field_context) == 4

    def test_missing_fields_in_contents(self):
        """Test that missing fields from dependency signature are gracefully skipped."""
        agent_config = {'dependencies': ['agent_A']}
        agent_name = 'test_agent'
        dependency_configs = {'agent_A': {'output_schema': {'properties': {'field1': {}, 'field2': {}, 'field3': {}}}}}
        generator = DataGenerator(agent_config, agent_name, dependency_configs)
        contents = {'field1': 'v1', 'field3': 'v3'}
        field_context = generator._build_namespaced_field_context(contents)
        assert 'agent_A' in field_context
        assert field_context['agent_A'] == {'field1': 'v1', 'field3': 'v3'}
        assert 'field2' not in field_context['agent_A']

    def test_no_dependencies(self):
        """Test behavior when agent has no dependencies."""
        agent_config = {'dependencies': []}
        agent_name = 'test_agent'
        dependency_configs = {}
        generator = DataGenerator(agent_config, agent_name, dependency_configs)
        contents = {'field1': 'v1'}
        field_context = generator._build_namespaced_field_context(contents)
        assert field_context == {}

    def test_dependency_not_in_configs(self):
        """Test when dependency is declared but config not available."""
        agent_config = {'dependencies': ['agent_A', 'agent_B']}
        agent_name = 'test_agent'
        dependency_configs = {'agent_A': {'output_schema': {'properties': {'field1': {}}}}}
        generator = DataGenerator(agent_config, agent_name, dependency_configs)
        contents = {'field1': 'v1', 'field2': 'v2'}
        field_context = generator._build_namespaced_field_context(contents)
        assert 'agent_A' in field_context
        assert 'agent_B' not in field_context