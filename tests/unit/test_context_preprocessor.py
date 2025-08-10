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

    def test_extract_guid_and_content_nested_format(self):
        """Test extraction from nested format {"uuid": {"source_guid": "...", ...}}."""
        context_data = {
            "uuid-123": {
                "source_guid": "test-guid-123",
                "page_content": "This is test content",
                "title": "Test Title",
                "metadata": {"type": "test"}
            }
        }
        
        source_guid, content = ContextPreprocessor.extract_guid_and_content(context_data)
        
        assert source_guid == "test-guid-123"
        # Should exclude metadata fields
        expected_content = {
            "page_content": "This is test content",
            "title": "Test Title",
            "metadata": {"type": "test"}
        }
        assert content == expected_content

    def test_extract_guid_and_content_nested_with_chunk_info(self):
        """Test extraction from nested format with chunk_info."""
        context_data = {
            "uuid-456": {
                "source_guid": "chunked-guid-456",
                "chunk_info": {
                    "chunk_index": 0,
                    "total_chunks": 3
                },
                "page_content": "Chunked content",
                "target_id": "target-123",  # Should be filtered out
                "record_index": 5,  # Should be filtered out
                "chunk_index": 2  # Should be filtered out
            }
        }
        
        source_guid, content = ContextPreprocessor.extract_guid_and_content(context_data)
        
        assert source_guid == "chunked-guid-456"
        expected_content = {
            "chunk_info": {
                "chunk_index": 0,
                "total_chunks": 3
            },
            "page_content": "Chunked content"
        }
        assert content == expected_content
        assert "target_id" not in content
        assert "record_index" not in content
        assert "chunk_index" not in content

    def test_extract_guid_and_content_no_nested_structure(self):
        """Test extraction when there's no nested structure with source_guid."""
        context_data = {
            "field1": "value1",
            "field2": "value2"
        }
        
        source_guid, content = ContextPreprocessor.extract_guid_and_content(context_data)
        
        assert source_guid is None
        assert content == context_data

    def test_extract_guid_and_content_empty_dict(self):
        """Test extraction with empty dict."""
        context_data = {}
        
        source_guid, content = ContextPreprocessor.extract_guid_and_content(context_data)
        
        assert source_guid is None
        assert content == {}

    def test_extract_guid_and_content_list_input(self):
        """Test extraction with list input (not supported in simplified version)."""
        context_data = [{"item": "value"}]
        
        source_guid, content = ContextPreprocessor.extract_guid_and_content(context_data)
        
        assert source_guid is None
        assert content == context_data

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
        # Returns the inner record without metadata fields
        assert content == {
            "nested_data": "some nested content"
        }

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
        # Returns the inner record that matched without metadata
        if source_guid == "first-guid-333":
            assert content == {"data": "first data"}
        else:
            assert content == {"data": "second data"}

    def test_extract_guid_and_content_none_input(self):
        """Test extraction with None input."""
        source_guid, content = ContextPreprocessor.extract_guid_and_content(None)
        
        assert source_guid is None
        assert content is None

    def test_extract_guid_and_content_string_input(self):
        """Test extraction with string input."""
        context_data = "just a string"
        
        source_guid, content = ContextPreprocessor.extract_guid_and_content(context_data)
        
        assert source_guid is None
        assert content == "just a string"


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
        # Use nested format that the preprocessor now expects
        context_data = {
            "uuid": {
                "source_guid": "static-test-guid", 
                "content": "static content"
            }
        }
        
        # Test extract_guid_and_content
        source_guid, content = ContextPreprocessor.extract_guid_and_content(context_data)
        assert source_guid == "static-test-guid"
        assert content == {"content": "static content"}
        
        # Test that we can instantiate the class and call static methods
        # (This is more of a design verification)
        preprocessor = ContextPreprocessor()
        source_guid2, content2 = preprocessor.extract_guid_and_content(context_data)
        assert source_guid2 == source_guid
        assert content2 == content

    def test_edge_case_source_guid_empty_string(self):
        """Test handling of empty string source_guid in nested structure."""
        context_data = {
            "uuid": {
                "source_guid": "",
                "content": "content with empty guid"
            }
        }
        
        source_guid, content = ContextPreprocessor.extract_guid_and_content(context_data)
        
        assert source_guid == ""
        assert content == {"content": "content with empty guid"}

    def test_edge_case_source_guid_none_value(self):
        """Test handling of None source_guid value in nested structure."""
        context_data = {
            "uuid": {
                "source_guid": None,
                "content": "content with None guid"
            }
        }
        
        source_guid, content = ContextPreprocessor.extract_guid_and_content(context_data)
        
        assert source_guid is None
        assert content == {"content": "content with None guid"}

    def test_real_world_chunked_example(self):
        """Test with a realistic nested chunked record example."""
        context_data = {
            "doc-123-chunk-5": {
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


    def test_extract_guid_and_content_real_world_nested_chunked_record(self):
        """Test real-world nested chunked record from user's source file structure."""
        context_data = {
            "fd722fad-79ae-55d3-87cc-637e8706050c": {
                "id": "a9c812df-4c66-4f47-ae7b-899548405375",
                "topic": "Designing and Implementing a Microsoft Azure AI Solution",
                "doc_name": "Microsoft Certified: Azure AI Engineer Associate AI-102",
                "url": "https://docs.azure.cn/en-us/ai-services/speech-service/get-started-speech-to-text",
                "title": "Speech to text quickstart - Azure AI services _ Azure Docs",
                "page_content": "Very long content that was chunked...",
                "chunk_info": {
                    "source_field": "page_content",
                    "chunk_index": 1,
                    "total_chunks": 3,
                    "fallback_applied": "preserved_large_page_content"
                },
                "source_guid": "fd722fad-79ae-55d3-87cc-637e8706050c",
                "target_id": "6aec4532-ebdd-4bdd-bf06-33c183376d9f", 
                "record_index": 0,
                "chunk_index": 0
            }
        }
        
        source_guid, content = ContextPreprocessor.extract_guid_and_content(context_data)
        
        assert source_guid == "fd722fad-79ae-55d3-87cc-637e8706050c"
        # Should return the inner record with metadata filtered out
        expected_content = {
            "id": "a9c812df-4c66-4f47-ae7b-899548405375",
            "topic": "Designing and Implementing a Microsoft Azure AI Solution",
            "doc_name": "Microsoft Certified: Azure AI Engineer Associate AI-102", 
            "url": "https://docs.azure.cn/en-us/ai-services/speech-service/get-started-speech-to-text",
            "title": "Speech to text quickstart - Azure AI services _ Azure Docs",
            "page_content": "Very long content that was chunked...",
            "chunk_info": {
                "source_field": "page_content",
                "chunk_index": 1,
                "total_chunks": 3,
                "fallback_applied": "preserved_large_page_content"
            }
        }
        assert content == expected_content
        # Verify metadata fields were filtered out
        assert "source_guid" not in content
        assert "target_id" not in content
        assert "record_index" not in content
        assert "chunk_index" not in content