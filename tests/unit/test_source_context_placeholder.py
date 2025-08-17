"""
Unit tests for source_context{{}} placeholder functionality.
"""

import pytest
import json
from agent_actions.processors.content.prompt_utils import PromptUtils


class TestSourceContextPlaceholder:
    """Test suite for source_context{{}} placeholder replacement."""

    def test_empty_placeholder_returns_full_content(self):
        """Test that source_context{{}} returns full source content."""
        prompt = "Here is the content: source_context{{}}"
        source_content = {"field1": "value1", "field2": "value2", "field3": {"nested": "data"}}
        
        result = PromptUtils.replace_source_context_placeholder(prompt, source_content)
        
        expected_json = json.dumps(source_content, indent=2)
        assert f"Here is the content: {expected_json}" == result

    def test_single_field_selection(self):
        """Test selecting a single field with source_context{{['field_name']}}."""
        prompt = "Page content: source_context{{['page_content']}}"
        source_content = {
            "page_content": "This is the page content",
            "title": "Page Title",
            "metadata": {"author": "John"}
        }
        
        result = PromptUtils.replace_source_context_placeholder(prompt, source_content)
        
        expected_json = json.dumps({"page_content": "This is the page content"}, indent=2)
        assert f"Page content: {expected_json}" == result

    def test_multiple_field_selection(self):
        """Test selecting multiple fields."""
        prompt = "Data: source_context{{['page_content', 'title']}}"
        source_content = {
            "page_content": "Content here",
            "title": "My Title",
            "metadata": {"author": "Jane"},
            "url": "https://example.com"
        }
        
        result = PromptUtils.replace_source_context_placeholder(prompt, source_content)
        
        expected_json = json.dumps({
            "page_content": "Content here",
            "title": "My Title"
        }, indent=2)
        assert f"Data: {expected_json}" == result

    def test_missing_field_returns_empty(self):
        """Test that requesting non-existent fields returns empty."""
        prompt = "Content: source_context{{['non_existent_field']}}"
        source_content = {"field1": "value1", "field2": "value2"}
        
        result = PromptUtils.replace_source_context_placeholder(prompt, source_content)
        
        assert "Content:" == result

    def test_string_source_content(self):
        """Test handling when source_content is a string."""
        prompt = "Content: source_context{{}}"
        source_content = "Just a plain string"
        
        result = PromptUtils.replace_source_context_placeholder(prompt, source_content)
        
        assert "Content: Just a plain string" == result

    def test_list_source_content(self):
        """Test handling when source_content is a list."""
        prompt = "Items: source_context{{}}"
        source_content = ["item1", "item2", {"key": "value"}]
        
        result = PromptUtils.replace_source_context_placeholder(prompt, source_content)
        
        expected_json = json.dumps(source_content, indent=2)
        assert f"Items: {expected_json}" == result

    def test_none_source_content(self):
        """Test handling when source_content is None."""
        prompt = "Content: source_context{{}}"
        source_content = None
        
        result = PromptUtils.replace_source_context_placeholder(prompt, source_content)
        
        assert "Content:" == result

    def test_invalid_field_spec_syntax(self):
        """Test handling of invalid field specification syntax."""
        prompt = "Content: source_context{{invalid syntax}}"
        source_content = {"field1": "value1"}
        
        result = PromptUtils.replace_source_context_placeholder(prompt, source_content)
        
        assert "Content:" == result


    def test_multiple_placeholders_in_prompt(self):
        """Test multiple source_context placeholders in one prompt."""
        prompt = "All: source_context{{}}, Title: source_context{{['title']}}, Content: source_context{{['page_content']}}"
        source_content = {
            "title": "My Title",
            "page_content": "My Content",
            "metadata": {"author": "Bob"}
        }
        
        result = PromptUtils.replace_source_context_placeholder(prompt, source_content)
        
        all_json = json.dumps(source_content, indent=2)
        title_json = json.dumps({"title": "My Title"}, indent=2)
        content_json = json.dumps({"page_content": "My Content"}, indent=2)
        
        expected = f"All: {all_json}, Title: {title_json}, Content: {content_json}"
        assert expected == result

    def test_case_insensitive_placeholder(self):
        """Test that placeholder matching is case insensitive."""
        prompt = "Content: SOURCE_CONTEXT{{}}"
        source_content = {"field": "value"}
        
        result = PromptUtils.replace_source_context_placeholder(prompt, source_content)
        
        expected_json = json.dumps(source_content, indent=2)
        assert f"Content: {expected_json}" == result

    def test_nested_field_extraction(self):
        """Test extracting fields from nested source content."""
        prompt = "Fields: source_context{{['chunk_info', 'page_content']}}"
        source_content = {
            "chunk_info": {
                "chunk_index": 0,
                "total_chunks": 5
            },
            "page_content": "Some content",
            "metadata": {"type": "document"}
        }
        
        result = PromptUtils.replace_source_context_placeholder(prompt, source_content)
        
        expected_json = json.dumps({
            "chunk_info": {
                "chunk_index": 0,
                "total_chunks": 5
            },
            "page_content": "Some content"
        }, indent=2)
        assert f"Fields: {expected_json}" == result

