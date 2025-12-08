"""Tests for field reference pattern {reference.field} in PromptUtils."""
import pytest
from agent_actions.prompt_generation.prompt_utils import PromptUtils

class TestParseFieldReferences:
    """Test parsing {reference.field} patterns from prompts."""

    def test_parse_simple_reference(self):
        """Should parse simple field reference."""
        prompt = 'Process {source.content}'
        refs = PromptUtils.parse_field_references(prompt)
        assert len(refs) == 1
        assert refs[0]['reference'] == 'source'
        assert refs[0]['field_path'] == ['content']
        assert refs[0]['full_match'] == '{source.content}'

    def test_parse_nested_reference(self):
        """Should parse nested field reference."""
        prompt = 'Count: {extractor.data.metrics.count}'
        refs = PromptUtils.parse_field_references(prompt)
        assert len(refs) == 1
        assert refs[0]['reference'] == 'extractor'
        assert refs[0]['field_path'] == ['data', 'metrics', 'count']

    def test_parse_multiple_references(self):
        """Should parse multiple field references."""
        prompt = 'Title: {source.title} and Summary: {extractor.summary}'
        refs = PromptUtils.parse_field_references(prompt)
        assert len(refs) == 2
        assert refs[0]['reference'] == 'source'
        assert refs[0]['field_path'] == ['title']
        assert refs[1]['reference'] == 'extractor'
        assert refs[1]['field_path'] == ['summary']

    def test_ignore_single_word_braces(self):
        """Should not match single word in braces (no dot)."""
        prompt = 'Process {content}'
        refs = PromptUtils.parse_field_references(prompt)
        assert len(refs) == 0

    def test_ignore_double_braces(self):
        """Should not match old source_context{{}} pattern."""
        prompt = "source_context{{['field']}}"
        refs = PromptUtils.parse_field_references(prompt)
        assert len(refs) == 0

    def test_parse_array_index_reference(self):
        """Should parse array index references."""
        prompt = 'First item: {extractor.items.0}'
        refs = PromptUtils.parse_field_references(prompt)
        assert len(refs) == 1
        assert refs[0]['reference'] == 'extractor'
        assert refs[0]['field_path'] == ['items', '0']

class TestResolveFieldReference:
    """Test resolving field references to actual values."""

    def test_resolve_simple_field(self):
        """Should resolve simple field from context."""
        context = {'source': {'content': 'hello world'}}
        value = PromptUtils.resolve_field_reference('source', ['content'], context)
        assert value == 'hello world'

    def test_resolve_nested_field(self):
        """Should resolve nested field from context."""
        context = {'extractor': {'data': {'metrics': {'count': 5}}}}
        value = PromptUtils.resolve_field_reference('extractor', ['data', 'metrics', 'count'], context)
        assert value == 5

    def test_resolve_array_index(self):
        """Should resolve array index from context."""
        context = {'extractor': {'items': ['a', 'b', 'c']}}
        value = PromptUtils.resolve_field_reference('extractor', ['items', '1'], context)
        assert value == 'b'

    def test_resolve_first_array_element(self):
        """Should resolve first array element (index 0)."""
        context = {'extractor': {'items': ['first', 'second']}}
        value = PromptUtils.resolve_field_reference('extractor', ['items', '0'], context)
        assert value == 'first'

    def test_missing_reference_error(self):
        """Should raise error for missing reference with available list."""
        context = {'source': {}}
        with pytest.raises(ValueError) as exc_info:
            PromptUtils.resolve_field_reference('extractor', ['field'], context)
        assert "Reference 'extractor' not found" in str(exc_info.value)
        assert 'Available: [source]' in str(exc_info.value)

    def test_missing_field_error(self):
        """Should raise error for missing field."""
        context = {'extractor': {'summary': 'text'}}
        with pytest.raises(ValueError) as exc_info:
            PromptUtils.resolve_field_reference('extractor', ['metrics'], context)
        assert "Field 'metrics' not found in 'extractor'" in str(exc_info.value)

    def test_missing_nested_field_error(self):
        """Should raise error for missing nested field."""
        context = {'extractor': {'data': {}}}
        with pytest.raises(ValueError) as exc_info:
            PromptUtils.resolve_field_reference('extractor', ['data', 'metrics', 'count'], context)
        assert "Field 'data.metrics.count' not found" in str(exc_info.value)

    def test_array_index_out_of_range(self):
        """Should raise error for array index out of range."""
        context = {'extractor': {'items': ['a', 'b']}}
        with pytest.raises(ValueError) as exc_info:
            PromptUtils.resolve_field_reference('extractor', ['items', '5'], context)
        assert 'Index 5 out of range' in str(exc_info.value)

class TestReplaceFieldReferences:
    """Test replacing field references in prompts."""

    def test_replace_simple_reference(self):
        """Should replace simple field reference."""
        prompt = 'Content: {source.text}'
        context = {'source': {'text': 'hello world'}}
        result = PromptUtils.replace_field_references(prompt, context)
        assert result == 'Content: hello world'

    def test_replace_multiple_references(self):
        """Should replace multiple field references."""
        prompt = 'Title: {source.title}, Summary: {extractor.summary}'
        context = {'source': {'title': 'Test'}, 'extractor': {'summary': 'A summary'}}
        result = PromptUtils.replace_field_references(prompt, context)
        assert result == 'Title: Test, Summary: A summary'

    def test_replace_dict_value_as_json(self):
        """Should convert dict values to JSON."""
        prompt = 'Data: {extractor.metrics}'
        context = {'extractor': {'metrics': {'count': 5, 'accuracy': 0.95}}}
        result = PromptUtils.replace_field_references(prompt, context)
        assert '"count": 5' in result
        assert '"accuracy": 0.95' in result

    def test_replace_list_value_as_json(self):
        """Should convert list values to JSON."""
        prompt = 'Items: {extractor.items}'
        context = {'extractor': {'items': ['a', 'b', 'c']}}
        result = PromptUtils.replace_field_references(prompt, context)
        assert '[\n  "a",\n  "b",\n  "c"\n]' in result

    def test_replace_nested_field(self):
        """Should replace nested field reference."""
        prompt = 'Count: {extractor.data.metrics.count}'
        context = {'extractor': {'data': {'metrics': {'count': 10}}}}
        result = PromptUtils.replace_field_references(prompt, context)
        assert result == 'Count: 10'

    def test_replace_array_index(self):
        """Should replace array index reference."""
        prompt = 'First: {extractor.items.0}, Second: {extractor.items.1}'
        context = {'extractor': {'items': ['alpha', 'beta', 'gamma']}}
        result = PromptUtils.replace_field_references(prompt, context)
        assert result == 'First: alpha, Second: beta'

    def test_error_on_missing_reference(self):
        """Should raise error with context on missing reference."""
        prompt = 'Data: {unknown.field}'
        context = {'source': {}}
        with pytest.raises(ValueError) as exc_info:
            PromptUtils.replace_field_references(prompt, context)
        assert 'Error resolving {unknown.field}' in str(exc_info.value)
        assert "Reference 'unknown' not found" in str(exc_info.value)

    def test_error_on_missing_field(self):
        """Should raise error with context on missing field."""
        prompt = 'Data: {extractor.missing}'
        context = {'extractor': {'present': 'value'}}
        with pytest.raises(ValueError) as exc_info:
            PromptUtils.replace_field_references(prompt, context)
        assert 'Error resolving {extractor.missing}' in str(exc_info.value)
        assert "Field 'missing' not found" in str(exc_info.value)

    def test_no_references_returns_unchanged(self):
        """Should return prompt unchanged if no references."""
        prompt = 'This is a plain prompt'
        context = {'source': {'data': 'value'}}
        result = PromptUtils.replace_field_references(prompt, context)
        assert result == prompt

    def test_numeric_values_converted_to_string(self):
        """Should convert numeric values to strings."""
        prompt = 'Count: {extractor.count}, Score: {extractor.score}'
        context = {'extractor': {'count': 42, 'score': 0.85}}
        result = PromptUtils.replace_field_references(prompt, context)
        assert result == 'Count: 42, Score: 0.85'

class TestLoopContextReferences:
    """Test {loop.*} special references."""

    def test_loop_index_reference(self):
        """Should resolve {loop.index} from loop context."""
        prompt = 'Processing item #{loop.index}'
        context = {'loop': {'index': 3}}
        result = PromptUtils.replace_field_references(prompt, context)
        assert result == 'Processing item #3'

    def test_loop_total_reference(self):
        """Should resolve {loop.total} from loop context."""
        prompt = 'Item {loop.index} of {loop.total}'
        context = {'loop': {'index': 2, 'total': 5}}
        result = PromptUtils.replace_field_references(prompt, context)
        assert result == 'Item 2 of 5'

    def test_loop_item_field_reference(self):
        """Should resolve {loop.item.field} from loop context."""
        prompt = 'Current review: {loop.item.text}'
        context = {'loop': {'item': {'text': 'Great product!', 'rating': 5}}}
        result = PromptUtils.replace_field_references(prompt, context)
        assert result == 'Current review: Great product!'

    def test_loop_item_nested_field_reference(self):
        """Should resolve {loop.item.nested.field} from loop context."""
        prompt = 'Sentiment: {loop.item.analysis.sentiment}'
        context = {'loop': {'item': {'analysis': {'sentiment': 'positive', 'score': 0.92}}}}
        result = PromptUtils.replace_field_references(prompt, context)
        assert result == 'Sentiment: positive'

    def test_loop_multiple_references(self):
        """Should resolve multiple {loop.*} references."""
        prompt = 'Review {loop.index}/{loop.total}: {loop.item.text}'
        context = {'loop': {'index': 1, 'total': 3, 'item': {'text': 'Excellent service'}}}
        result = PromptUtils.replace_field_references(prompt, context)
        assert result == 'Review 1/3: Excellent service'

    def test_loop_context_with_agent_references(self):
        """Should resolve both {loop.*} and {agent.*} references."""
        prompt = 'Review {loop.index}: {loop.item.text}\nPrevious analysis: {extractor.summary}'
        context = {'loop': {'index': 2, 'item': {'text': 'Good quality'}}, 'extractor': {'summary': 'Positive feedback trend'}}
        result = PromptUtils.replace_field_references(prompt, context)
        assert result == 'Review 2: Good quality\nPrevious analysis: Positive feedback trend'

class TestWorkflowMetadataReferences:
    """Test {workflow.*} special references."""

    def test_workflow_name_reference(self):
        """Should resolve {workflow.name} from workflow metadata."""
        prompt = 'Running workflow: {workflow.name}'
        context = {'workflow': {'name': 'customer_review_analysis'}}
        result = PromptUtils.replace_field_references(prompt, context)
        assert result == 'Running workflow: customer_review_analysis'

    def test_workflow_version_reference(self):
        """Should resolve {workflow.version} from workflow metadata."""
        prompt = 'Workflow version: {workflow.version}'
        context = {'workflow': {'version': '1.2.0'}}
        result = PromptUtils.replace_field_references(prompt, context)
        assert result == 'Workflow version: 1.2.0'

    def test_workflow_run_id_reference(self):
        """Should resolve {workflow.run_id} from workflow metadata."""
        prompt = 'Run ID: {workflow.run_id}'
        context = {'workflow': {'run_id': 'run-abc123-xyz'}}
        result = PromptUtils.replace_field_references(prompt, context)
        assert result == 'Run ID: run-abc123-xyz'

    def test_workflow_multiple_references(self):
        """Should resolve multiple {workflow.*} references."""
        prompt = 'Workflow: {workflow.name} v{workflow.version} (Run: {workflow.run_id})'
        context = {'workflow': {'name': 'sentiment_pipeline', 'version': '2.0.1', 'run_id': 'run-def456'}}
        result = PromptUtils.replace_field_references(prompt, context)
        assert result == 'Workflow: sentiment_pipeline v2.0.1 (Run: run-def456)'

    def test_workflow_with_loop_and_agent_references(self):
        """Should resolve {workflow.*}, {loop.*}, and {agent.*} references together."""
        prompt = '[{workflow.name}] Processing review {loop.index} using {extractor.model}'
        context = {'workflow': {'name': 'review_analysis'}, 'loop': {'index': 5}, 'extractor': {'model': 'gpt-4'}}
        result = PromptUtils.replace_field_references(prompt, context)
        assert result == '[review_analysis] Processing review 5 using gpt-4'

    def test_workflow_nested_metadata(self):
        """Should resolve nested workflow metadata fields."""
        prompt = 'Environment: {workflow.config.environment}'
        context = {'workflow': {'config': {'environment': 'production', 'debug': False}}}
        result = PromptUtils.replace_field_references(prompt, context)
        assert result == 'Environment: production'