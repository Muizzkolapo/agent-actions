"""Tests for field reference pattern {reference.field} in PromptUtils."""

import pytest

from agent_actions.prompt.prompt_utils import PromptUtils


class TestParseFieldReferences:
    """Test parsing {reference.field} patterns from prompts."""

    def test_ignore_single_word_braces(self):
        """Should not match single word in braces (no dot)."""
        prompt = "Process {content}"
        refs = PromptUtils.parse_field_references(prompt)
        assert len(refs) == 0

    def test_ignore_double_braces(self):
        """Should not match old source_context{{}} pattern."""
        prompt = "source_context{{['field']}}"
        refs = PromptUtils.parse_field_references(prompt)
        assert len(refs) == 0


class TestResolveFieldReference:
    """Test resolving field references to actual values."""

    def test_resolve_simple_field(self):
        """Should resolve simple field from context."""
        context = {"source": {"content": "hello world"}}
        value = PromptUtils.resolve_field_reference("source", ["content"], context)
        assert value == "hello world"

    def test_resolve_nested_field(self):
        """Should resolve nested field from context."""
        context = {"extractor": {"data": {"metrics": {"count": 5}}}}
        value = PromptUtils.resolve_field_reference(
            "extractor", ["data", "metrics", "count"], context
        )
        assert value == 5

    def test_resolve_array_index(self):
        """Should resolve array index from context."""
        context = {"extractor": {"items": ["a", "b", "c"]}}
        value = PromptUtils.resolve_field_reference("extractor", ["items", "1"], context)
        assert value == "b"

    def test_resolve_first_array_element(self):
        """Should resolve first array element (index 0)."""
        context = {"extractor": {"items": ["first", "second"]}}
        value = PromptUtils.resolve_field_reference("extractor", ["items", "0"], context)
        assert value == "first"

    def test_missing_reference_error(self):
        """Should raise error for missing reference with available list."""
        context = {"source": {}}
        with pytest.raises(ValueError) as exc_info:
            PromptUtils.resolve_field_reference("extractor", ["field"], context)
        assert "Reference 'extractor' not found" in str(exc_info.value)
        assert "Available: [source]" in str(exc_info.value)

    def test_missing_field_error(self):
        """Should raise error for missing field."""
        context = {"extractor": {"summary": "text"}}
        with pytest.raises(ValueError) as exc_info:
            PromptUtils.resolve_field_reference("extractor", ["metrics"], context)
        assert "Field 'metrics' not found in 'extractor'" in str(exc_info.value)

    def test_missing_nested_field_error(self):
        """Should raise error for missing nested field."""
        context = {"extractor": {"data": {}}}
        with pytest.raises(ValueError) as exc_info:
            PromptUtils.resolve_field_reference("extractor", ["data", "metrics", "count"], context)
        assert "Field 'data.metrics.count' not found" in str(exc_info.value)

    def test_array_index_out_of_range(self):
        """Should raise error for array index out of range."""
        context = {"extractor": {"items": ["a", "b"]}}
        with pytest.raises(ValueError) as exc_info:
            PromptUtils.resolve_field_reference("extractor", ["items", "5"], context)
        assert "Index 5 out of range" in str(exc_info.value)


class TestReplaceFieldReferences:
    """Test replacing field references in prompts."""

    def test_no_references_returns_unchanged(self):
        """Should return prompt unchanged if no references."""
        prompt = "This is a plain prompt"
        context = {"source": {"data": "value"}}
        result = PromptUtils.replace_field_references(prompt, context)
        assert result == prompt
