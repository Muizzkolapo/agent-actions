"""
Unit tests for ContextPreprocessor class.

Tests the context preprocessing functionality including GUID extraction,
content extraction, and context preparation with various input formats.
"""

import pytest
from unittest.mock import Mock, patch

from agent_actions.processors.prompt_processor.context_preprocessor import ContextPreprocessor


class TestContextPreprocessor:
    """Test suite for ContextPreprocessor class."""

    def test_extract_guid_and_content_standard_format(self):
        """Test extraction from standard format with source_guid and content."""
        context_data = {
            "source_guid": "test-guid-123",
            "content": "This is test content"
        }
        
        source_guid, content = ContextPreprocessor.extract_guid_and_content(context_data)
        
        assert source_guid == "test-guid-123"
        assert content == "This is test content"

    def test_extract_guid_and_content_standard_format_with_extra_fields(self):
        """Test extraction from standard format with additional fields."""
        context_data = {
            "source_guid": "test-guid-456",
            "content": {"text": "Complex content", "metadata": {"type": "test"}},
            "extra_field": "should be ignored for content",
            "timestamp": "2023-01-01"
        }
        
        source_guid, content = ContextPreprocessor.extract_guid_and_content(context_data)
        
        assert source_guid == "test-guid-456"
        assert content == {"text": "Complex content", "metadata": {"type": "test"}}

    def test_extract_guid_and_content_chunked_records_format(self):
        """Test extraction from chunked records format."""
        context_data = {
            "source_guid": "chunked-guid-789",
            "chunk_info": {
                "chunk_index": 0,
                "total_chunks": 3,
                "chunk_size": 1000
            },
            "data": "Chunked data content",
            "metadata": {"processed": True},
            "target_id": "target-123",  # Should be filtered out
            "record_index": 5,  # Should be filtered out
            "chunk_index": 2  # Should be filtered out
        }
        
        source_guid, content = ContextPreprocessor.extract_guid_and_content(context_data)
        
        assert source_guid == "chunked-guid-789"
        # Content should exclude internal metadata fields
        expected_content = {
            "chunk_info": {
                "chunk_index": 0,
                "total_chunks": 3,
                "chunk_size": 1000
            },
            "data": "Chunked data content",
            "metadata": {"processed": True}
        }
        assert content == expected_content
        assert "target_id" not in content
        assert "record_index" not in content
        # Note: chunk_index from root should be filtered, but chunk_index in chunk_info should remain

    def test_extract_guid_and_content_chunked_records_minimal(self):
        """Test extraction from minimal chunked records format."""
        context_data = {
            "source_guid": "minimal-chunked-guid",
            "chunk_info": {"chunk_index": 1},
            "content_field": "Some content"
        }
        
        source_guid, content = ContextPreprocessor.extract_guid_and_content(context_data)
        
        assert source_guid == "minimal-chunked-guid"
        expected_content = {
            "chunk_info": {"chunk_index": 1},
            "content_field": "Some content"
        }
        assert content == expected_content

    def test_extract_guid_and_content_direct_source_guid(self):
        """Test extraction from dict with only source_guid."""
        context_data = {
            "source_guid": "direct-guid-999",
            "other_field": "some value",
            "metadata": {"type": "direct"}
        }
        
        source_guid, content = ContextPreprocessor.extract_guid_and_content(context_data)
        
        assert source_guid == "direct-guid-999"
        assert content == context_data  # Entire dict should be returned as content

    def test_extract_guid_and_content_nested_list_structure(self):
        """Test extraction from nested list structure."""
        context_data = [
            {
                "uuid1": {
                    "source_guid": "nested-list-guid-111",
                    "data": "nested data 1"
                }
            },
            {
                "uuid2": {
                    "other_field": "no guid here"
                }
            }
        ]
        
        source_guid, content = ContextPreprocessor.extract_guid_and_content(context_data)
        
        assert source_guid == "nested-list-guid-111"
        assert content == context_data  # Entire list should be returned as content

    def test_extract_guid_and_content_nested_dict_structure(self):
        """Test extraction from nested dict structure."""
        context_data = {
            "outer_key": {
                "source_guid": "nested-dict-guid-222",
                "nested_data": "some nested content"
            },
            "other_outer_key": {
                "no_guid": "here"
            }
        }
        
        source_guid, content = ContextPreprocessor.extract_guid_and_content(context_data)
        
        assert source_guid == "nested-dict-guid-222"
        assert content == context_data  # Entire dict should be returned as content

    def test_extract_guid_and_content_multiple_nested_structures(self):
        """Test extraction from structure with multiple possible GUIDs (should return first found)."""
        context_data = {
            "first_key": {
                "source_guid": "first-guid-333",
                "data": "first data"
            },
            "second_key": {
                "source_guid": "second-guid-444",
                "data": "second data"
            }
        }
        
        source_guid, content = ContextPreprocessor.extract_guid_and_content(context_data)
        
        # Should return the first found GUID (order depends on dict iteration)
        assert source_guid in ["first-guid-333", "second-guid-444"]
        assert content == context_data

    def test_extract_guid_and_content_none_input(self):
        """Test extraction with None input."""
        source_guid, content = ContextPreprocessor.extract_guid_and_content(None)
        
        assert source_guid is None
        assert content is None

    def test_extract_guid_and_content_empty_dict(self):
        """Test extraction with empty dict."""
        context_data = {}
        
        source_guid, content = ContextPreprocessor.extract_guid_and_content(context_data)
        
        assert source_guid is None
        assert content == {}

    def test_extract_guid_and_content_empty_list(self):
        """Test extraction with empty list."""
        context_data = []
        
        source_guid, content = ContextPreprocessor.extract_guid_and_content(context_data)
        
        assert source_guid is None
        assert content == []

    def test_extract_guid_and_content_string_input(self):
        """Test extraction with string input."""
        context_data = "just a string"
        
        source_guid, content = ContextPreprocessor.extract_guid_and_content(context_data)
        
        assert source_guid is None
        assert content == "just a string"

    def test_extract_guid_and_content_list_without_guid(self):
        """Test extraction from list without any GUID."""
        context_data = [
            {"no_guid": "here"},
            {"also_no_guid": "here"},
            "string item"
        ]
        
        source_guid, content = ContextPreprocessor.extract_guid_and_content(context_data)
        
        assert source_guid is None
        assert content == context_data

    def test_extract_guid_and_content_dict_without_guid(self):
        """Test extraction from dict without any GUID."""
        context_data = {
            "field1": "value1",
            "field2": {"nested": "value"},
            "field3": ["list", "items"]
        }
        
        source_guid, content = ContextPreprocessor.extract_guid_and_content(context_data)
        
        assert source_guid is None
        assert content == context_data

    def test_extract_guid_and_content_complex_nested_structure(self):
        """Test extraction from complex nested structure."""
        context_data = [
            {
                "level1": {
                    "level2": {
                        "source_guid": "deep-nested-guid-555",
                        "deep_data": "deeply nested content"
                    }
                }
            }
        ]
        
        source_guid, content = ContextPreprocessor.extract_guid_and_content(context_data)
        
        # Current implementation only goes 2 levels deep, so this shouldn't find the GUID
        assert source_guid is None
        assert content == context_data

    def test_extract_guid_and_content_precedence_order(self):
        """Test that extraction follows correct precedence order."""
        # Standard format should take precedence over chunked format
        context_data = {
            "source_guid": "standard-guid-666",
            "content": "standard content",
            "chunk_info": {"chunk_index": 0}  # This suggests chunked format but content field exists
        }
        
        source_guid, content = ContextPreprocessor.extract_guid_and_content(context_data)
        
        assert source_guid == "standard-guid-666"
        assert content == "standard content"  # Should use content field, not entire dict

    def test_extract_guid_and_content_chunked_vs_direct(self):
        """Test precedence between chunked format and direct source_guid."""
        # Chunked format should take precedence over direct source_guid
        context_data = {
            "source_guid": "precedence-guid-777",
            "chunk_info": {"chunk_index": 0},
            "data": "chunked content data",
            "other_field": "other value"
        }
        
        source_guid, content = ContextPreprocessor.extract_guid_and_content(context_data)
        
        assert source_guid == "precedence-guid-777"
        # Should be treated as chunked format, returning filtered dict
        expected_content = {
            "chunk_info": {"chunk_index": 0},
            "data": "chunked content data",
            "other_field": "other value"
        }
        assert content == expected_content

    @patch('agent_actions.processors.prompt_processor.context_preprocessor.apply_remove_collection')
    def test_prepare_context_calls_apply_remove_collection(self, mock_apply_remove_collection):
        """Test that prepare_context calls apply_remove_collection with correct arguments."""
        context_data = {"test": "data"}
        agent_config = {"remove_collection": ["field1", "field2"]}
        expected_result = {"processed": "data"}
        
        mock_apply_remove_collection.return_value = expected_result
        
        result = ContextPreprocessor.prepare_context(context_data, agent_config)
        
        mock_apply_remove_collection.assert_called_once_with(context_data, agent_config)
        assert result == expected_result

    def test_prepare_context_with_none_inputs(self):
        """Test prepare_context with None inputs."""
        # This should raise an AttributeError since agent_config is None
        with pytest.raises(AttributeError, match="'NoneType' object has no attribute 'get'"):
            ContextPreprocessor.prepare_context(None, None)

    @patch('agent_actions.processors.prompt_processor.context_preprocessor.apply_remove_collection')
    def test_prepare_context_with_empty_config(self, mock_apply_remove_collection):
        """Test prepare_context with empty agent config."""
        context_data = {"test": "data"}
        agent_config = {}
        
        mock_apply_remove_collection.return_value = context_data
        
        result = ContextPreprocessor.prepare_context(context_data, agent_config)
        
        mock_apply_remove_collection.assert_called_once_with(context_data, agent_config)
        assert result == context_data

    def test_context_preprocessor_is_static(self):
        """Test that ContextPreprocessor methods are static and don't require instantiation."""
        # Should be able to call methods without instantiating the class
        context_data = {"source_guid": "static-test-guid", "content": "static content"}
        
        # Test extract_guid_and_content
        source_guid, content = ContextPreprocessor.extract_guid_and_content(context_data)
        assert source_guid == "static-test-guid"
        assert content == "static content"
        
        # Test that we can't instantiate the class accidentally calls static methods
        # (This is more of a design verification)
        preprocessor = ContextPreprocessor()
        source_guid2, content2 = preprocessor.extract_guid_and_content(context_data)
        assert source_guid2 == source_guid
        assert content2 == content

    def test_edge_case_source_guid_empty_string(self):
        """Test handling of empty string source_guid."""
        context_data = {
            "source_guid": "",
            "content": "content with empty guid"
        }
        
        source_guid, content = ContextPreprocessor.extract_guid_and_content(context_data)
        
        assert source_guid == ""
        assert content == "content with empty guid"

    def test_edge_case_source_guid_none_value(self):
        """Test handling of None source_guid value."""
        context_data = {
            "source_guid": None,
            "content": "content with None guid"
        }
        
        source_guid, content = ContextPreprocessor.extract_guid_and_content(context_data)
        
        assert source_guid is None
        assert content == "content with None guid"

    def test_edge_case_chunk_info_none_value(self):
        """Test handling of None chunk_info value."""
        context_data = {
            "source_guid": "chunk-guid-with-none",
            "chunk_info": None,
            "data": "some data"
        }
        
        source_guid, content = ContextPreprocessor.extract_guid_and_content(context_data)
        
        # Should be treated as chunked format since chunk_info key exists
        assert source_guid == "chunk-guid-with-none"
        expected_content = {
            "chunk_info": None,
            "data": "some data"
        }
        assert content == expected_content

    def test_real_world_chunked_example(self):
        """Test with a realistic chunked record example."""
        context_data = {
            "source_guid": "doc-123-chunk-5",
            "chunk_info": {
                "chunk_index": 5,
                "total_chunks": 10,
                "chunk_size": 2048,
                "overlap": 100,
                "start_pos": 10240,
                "end_pos": 12288
            },
            "text": "This is the actual text content of the chunk...",
            "metadata": {
                "document_type": "pdf",
                "page_number": 3,
                "extraction_method": "ocr"
            },
            "embeddings": [0.1, 0.2, 0.3],  # Vector embeddings
            "target_id": "should-be-filtered",
            "record_index": 42,
            "chunk_index": 99  # Different from chunk_info.chunk_index
        }
        
        source_guid, content = ContextPreprocessor.extract_guid_and_content(context_data)
        
        assert source_guid == "doc-123-chunk-5"
        
        # Verify all content except internal metadata is preserved
        expected_content = {
            "chunk_info": {
                "chunk_index": 5,
                "total_chunks": 10,
                "chunk_size": 2048,
                "overlap": 100,
                "start_pos": 10240,
                "end_pos": 12288
            },
            "text": "This is the actual text content of the chunk...",
            "metadata": {
                "document_type": "pdf",
                "page_number": 3,
                "extraction_method": "ocr"
            },
            "embeddings": [0.1, 0.2, 0.3]
        }
        assert content == expected_content
        
        # Verify internal metadata was filtered out
        assert "target_id" not in content
        assert "record_index" not in content
        assert "chunk_index" not in content  # Root level chunk_index should be filtered

    def test_backward_compatibility_with_existing_code(self):
        """Test that new chunked logic doesn't break existing code patterns."""
        # Test various existing patterns that should continue to work
        
        # Pattern 1: Simple dict with source_guid
        data1 = {"source_guid": "simple-guid"}
        guid1, content1 = ContextPreprocessor.extract_guid_and_content(data1)
        assert guid1 == "simple-guid"
        assert content1 == data1
        
        # Pattern 2: Standard format
        data2 = {"source_guid": "std-guid", "content": "std-content"}
        guid2, content2 = ContextPreprocessor.extract_guid_and_content(data2)
        assert guid2 == "std-guid"
        assert content2 == "std-content"
        
        # Pattern 3: Nested structure
        data3 = {"item": {"source_guid": "nested-guid", "data": "nested"}}
        guid3, content3 = ContextPreprocessor.extract_guid_and_content(data3)
        assert guid3 == "nested-guid"
        assert content3 == data3
        
        # Pattern 4: List with nested structure
        data4 = [{"item": {"source_guid": "list-nested-guid"}}]
        guid4, content4 = ContextPreprocessor.extract_guid_and_content(data4)
        assert guid4 == "list-nested-guid"
        assert content4 == data4