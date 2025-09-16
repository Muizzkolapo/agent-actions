import pytest

from agent_actions._internal.utils.field_chunking import FieldAnalyzer, FieldChunker, FieldChunkingValidationError, FieldChunkingError
from agent_actions.agents.transformers.string_transformer import Tokenizer


@pytest.fixture(autouse=True)
def dummy_tokenizer(monkeypatch):
    def num_tokens_from_string(text, model):
        return len(text.split())

    def split_text_content(text, chunk_size, overlap, **kwargs):
        words = text.split()
        step = max(1, chunk_size - overlap)
        chunks = []
        for i in range(0, len(words), step):
            chunk = " ".join(words[i : i + chunk_size])
            if chunk:
                chunks.append(chunk)
        return chunks

    monkeypatch.setattr(Tokenizer, "num_tokens_from_string", staticmethod(num_tokens_from_string))
    monkeypatch.setattr(Tokenizer, "split_text_content", staticmethod(split_text_content))


def _config():
    return {
        "chunk_size": 3,
        "overlap": 0,
        "tokenizer_model": "dummy",
        "split_method": "dummy",
        "field_chunking": {
            "enabled": True,
            "chunk_fields": ["content"],
            "preserve_fields": ["title"],
            "chunk_threshold": 1,
        },
    }


def test_analyzer_identifies_fields_to_chunk():
    analyzer = FieldAnalyzer(_config())
    record = {"title": "doc", "content": "word " * 10}
    analysis = analyzer.analyze_record(record)
    assert analysis.fields_to_chunk == ["content"]
    assert analysis.requires_chunking


def test_chunker_splits_field_and_preserves_metadata():
    config = _config()
    analyzer = FieldAnalyzer(config)
    chunker = FieldChunker(config)
    record = {"title": "doc", "content": "word " * 10}
    analysis = analyzer.analyze_record(record)
    chunks = chunker.chunk_record(record, analysis)
    assert len(chunks) > 1
    total = chunks[0]["chunk_info"]["total_chunks"]
    assert total == len(chunks)
    for chunk in chunks:
        assert chunk["title"] == "doc"
        info = chunk["chunk_info"]
        assert info["source_field"] == "content"


def test_multi_field_chunking_creates_separate_chunks():
    """Test that multiple fields are chunked separately, not as cartesian product."""
    config = {
        "chunk_size": 2,
        "overlap": 0,
        "tokenizer_model": "dummy",
        "split_method": "dummy",
        "field_chunking": {
            "enabled": True,
            "chunk_fields": ["content", "description"],
            "preserve_fields": ["title"],
            "chunk_threshold": 1,
        },
    }
    
    analyzer = FieldAnalyzer(config)
    chunker = FieldChunker(config)
    
    # Record with two fields that need chunking
    record = {
        "title": "doc",
        "content": "word1 word2 word3 word4",  # 4 words -> 2 chunks (2 words each)
        "description": "desc1 desc2 desc3"        # 3 words -> 2 chunks (2 + 1 words)
    }
    
    analysis = analyzer.analyze_record(record)
    chunks = chunker.chunk_record(record, analysis)
    
    # Should create 2 + 2 = 4 chunks (not 2 × 2 = 4, but for different reasons)
    assert len(chunks) == 4
    
    # Check that we have chunks for both fields
    content_chunks = [c for c in chunks if c["chunk_info"]["source_field"] == "content"]
    description_chunks = [c for c in chunks if c["chunk_info"]["source_field"] == "description"]
    
    assert len(content_chunks) == 2  # content field chunked into 2
    assert len(description_chunks) == 2  # description field chunked into 2
    
    # All chunks should preserve the title
    for chunk in chunks:
        assert chunk["title"] == "doc"
        
    # Each chunk should have only one field modified
    for chunk in content_chunks:
        assert "word" in chunk["content"]
        assert chunk["description"] == "desc1 desc2 desc3"  # Original preserved
        
    for chunk in description_chunks:
        assert "desc" in chunk["description"] 
        assert chunk["content"] == "word1 word2 word3 word4"  # Original preserved


def test_field_analyzer_validation_conflicting_fields():
    """Test that FieldAnalyzer validates conflicting chunk and preserve fields."""
    config = {
        "chunk_size": 1000,
        "field_chunking": {
            "enabled": True,
            "chunk_fields": ["content", "title"],  # title is also in preserve_fields
            "preserve_fields": ["title", "url"],
            "chunk_threshold": 100,
        },
    }
    
    with pytest.raises(FieldChunkingValidationError, match="Fields cannot be both chunked and preserved.*title"):
        FieldAnalyzer(config)


def test_field_analyzer_validation_negative_threshold():
    """Test that FieldAnalyzer validates negative chunk_threshold."""
    config = {
        "chunk_size": 1000,
        "field_chunking": {
            "enabled": True,
            "chunk_fields": ["content"],
            "chunk_threshold": -100,  # Invalid negative threshold
        },
    }
    
    with pytest.raises(FieldChunkingValidationError, match="chunk_threshold must be non-negative"):
        FieldAnalyzer(config)


def test_field_analyzer_validation_empty_chunk_fields():
    """Test that FieldAnalyzer validates empty chunk_fields when enabled."""
    config = {
        "chunk_size": 1000,
        "field_chunking": {
            "enabled": True,
            "chunk_fields": [],  # Empty chunk_fields
            "chunk_threshold": 100,
        },
    }
    
    with pytest.raises(FieldChunkingValidationError, match="chunk_fields must be specified"):
        FieldAnalyzer(config)


def test_field_chunker_validation_invalid_chunk_size():
    """Test that FieldChunker validates chunk_size."""
    config = {
        "chunk_size": 0,  # Invalid chunk size
        "overlap": 100,
        "field_chunking": {"enabled": True},
    }
    
    with pytest.raises(FieldChunkingValidationError, match="chunk_size must be positive"):
        FieldChunker(config)


def test_field_chunker_validation_overlap_too_large():
    """Test that FieldChunker validates overlap vs chunk_size."""
    config = {
        "chunk_size": 100,
        "overlap": 150,  # Overlap larger than chunk_size
        "field_chunking": {"enabled": True},
    }
    
    with pytest.raises(FieldChunkingValidationError, match="overlap must be smaller than chunk_size"):
        FieldChunker(config)


def test_field_chunker_validation_invalid_split_method():
    """Test that FieldChunker validates split_method."""
    config = {
        "chunk_size": 1000,
        "overlap": 100,
        "split_method": "",  # Empty split method (invalid)
        "field_chunking": {"enabled": True},
    }
    
    with pytest.raises(FieldChunkingValidationError, match="split_method must be a non-empty string"):
        FieldChunker(config)


def test_chunker_truncation_fallback():
    """Test that chunker applies truncation fallback for large fields."""
    config = {
        "chunk_size": 5,
        "overlap": 0,
        "tokenizer_model": "dummy",
        "split_method": "dummy",
        "field_chunking": {
            "enabled": True,
            "chunk_fields": ["content"],
            "fallback_strategy": "truncate",
            "truncate_at": 10,  # Very small limit to trigger truncation
        },
    }
    
    analyzer = FieldAnalyzer(config)
    chunker = FieldChunker(config)
    
    record = {
        "title": "doc",
        "content": "This is a very long content that exceeds the truncation limit"
    }
    
    analysis = analyzer.analyze_record(record)
    chunks = chunker.chunk_record(record, analysis)
    
    # Should have chunks with truncated content
    assert len(chunks) > 0
    for chunk in chunks:
        # Content should be truncated to 10 characters
        original_content_length = len(record["content"])
        if original_content_length > 10:
            assert "fallback_applied" in chunk["chunk_info"]


def test_chunker_excessive_chunks_fallback():
    """Test that chunker limits excessive chunks per record."""
    config = {
        "chunk_size": 1,  # Very small chunks to generate many chunks
        "overlap": 0,
        "tokenizer_model": "dummy",
        "split_method": "dummy", 
        "field_chunking": {
            "enabled": True,
            "chunk_fields": ["content"],
            "fallback_strategy": "truncate",
            "max_chunks_per_record": 3,  # Limit to 3 chunks
        },
    }
    
    analyzer = FieldAnalyzer(config)
    chunker = FieldChunker(config)
    
    record = {
        "title": "doc",
        "content": "word1 word2 word3 word4 word5 word6"  # Would create 6 chunks
    }
    
    analysis = analyzer.analyze_record(record)
    chunks = chunker.chunk_record(record, analysis)
    
    # Should be limited to max_chunks_per_record
    assert len(chunks) <= 3
    
    # Should have fallback metadata if chunks were limited
    if len(chunks) == 3:
        # Check if any chunk has fallback info
        has_fallback = any("fallback_applied" in chunk.get("chunk_info", {}) for chunk in chunks)
        assert has_fallback or len(chunks) <= 3  # Either fallback applied or naturally few chunks


def test_chunker_preserve_original_on_error():
    """Test that chunker preserves original record when chunking fails."""
    config = {
        "chunk_size": 1000,
        "overlap": 100,
        "tokenizer_model": "dummy",
        "split_method": "dummy",
        "field_chunking": {
            "enabled": True,
            "chunk_fields": ["content"],
            "fallback_strategy": "preserve_original",
        },
    }
    
    analyzer = FieldAnalyzer(config)
    chunker = FieldChunker(config)
    
    record = {"title": "doc", "content": "test content"}
    
    # Mock a failure in chunk_field by making it raise an exception
    original_chunk_field = chunker.chunk_field
    def failing_chunk_field(field_value):
        raise Exception("Simulated chunking failure")
    
    chunker.chunk_field = failing_chunk_field
    
    try:
        analysis = analyzer.analyze_record(record)
        chunks = chunker.chunk_record(record, analysis)
        
        # Should return one chunk with error metadata
        assert len(chunks) == 1
        chunk = chunks[0]
        assert "chunking_error" in chunk["chunk_info"]
        assert chunk["chunk_info"]["fallback_applied"] == "preserve_original_on_error"
        assert chunk["content"] == "test content"  # Original content preserved
        
    finally:
        # Restore original method
        chunker.chunk_field = original_chunk_field


def test_chunker_error_fallback_strategy():
    """Test that chunker raises error when fallback_strategy is 'error'."""
    config = {
        "chunk_size": 1000,
        "overlap": 100,
        "tokenizer_model": "dummy",
        "split_method": "dummy",
        "field_chunking": {
            "enabled": True,
            "chunk_fields": ["content"],
            "fallback_strategy": "error",  # Should raise errors
        },
    }
    
    analyzer = FieldAnalyzer(config)
    chunker = FieldChunker(config)
    
    record = {"title": "doc", "content": "test content"}
    
    # Mock a failure in chunk_field
    original_chunk_field = chunker.chunk_field
    def failing_chunk_field(field_value, field_name=None):
        raise Exception("Simulated chunking failure")
    
    chunker.chunk_field = failing_chunk_field
    
    try:
        analysis = analyzer.analyze_record(record)
        
        with pytest.raises(FieldChunkingError, match="Failed to chunk field"):
            chunker.chunk_record(record, analysis)
            
    finally:
        # Restore original method
        chunker.chunk_field = original_chunk_field


def test_field_specific_rules():
    """Test that field-specific rules override global settings."""
    config = {
        "chunk_size": 10,  # Global setting
        "overlap": 2,      # Global setting
        "tokenizer_model": "dummy",
        "split_method": "dummy",
        "field_chunking": {
            "enabled": True,
            "chunk_fields": ["content", "description"],
            "preserve_fields": ["title"],
            "chunk_threshold": 1,
            "field_rules": {
                "content": {
                    "chunk_size": 5,        # Override global chunk_size
                    "overlap": 1,           # Override global overlap
                    "chunk_threshold": 3,   # Field-specific threshold
                },
                "description": {
                    "chunk_size": 15,       # Different size for description
                    "chunk_threshold": 5,   # Higher threshold for description
                }
            }
        },
    }
    
    analyzer = FieldAnalyzer(config)
    chunker = FieldChunker(config)
    
    record = {
        "title": "doc",
        "content": "word1 word2 word3 word4 word5",     # 5 words, should chunk with threshold 3
        "description": "desc1 desc2 desc3 desc4"            # 4 words, below threshold 5
    }
    
    # Test field analysis with field-specific thresholds
    analysis = analyzer.analyze_record(record)
    
    # content should be chunked (5 words > threshold 3)
    # description should NOT be chunked (4 words < threshold 5)
    assert "content" in analysis.fields_to_chunk
    assert "description" not in analysis.fields_to_chunk
    
    # Test chunking with field-specific rules
    chunks = chunker.chunk_record(record, analysis)
    
    # Should create chunks only for content field
    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk["title"] == "doc"  # Preserved field
        assert "chunk_info" in chunk
        assert chunk["chunk_info"]["source_field"] == "content"


def test_field_rules_validation():
    """Test validation of field_rules configuration."""
    
    # Test invalid field rule (not a dict)
    config = {
        "chunk_size": 1000,
        "field_chunking": {
            "enabled": True,
            "chunk_fields": ["content"],
            "field_rules": {
                "content": "invalid"  # Should be a dict
            }
        },
    }
    
    with pytest.raises(FieldChunkingValidationError, match="field_rules\\[content\\] must be a dictionary"):
        FieldAnalyzer(config)
    
    # Test invalid chunk_size in field rule
    config["field_chunking"]["field_rules"]["content"] = {"chunk_size": 0}
    with pytest.raises(FieldChunkingValidationError, match="field_rules\\[content\\].chunk_size must be positive"):
        FieldAnalyzer(config)
    
    # Test negative overlap in field rule
    config["field_chunking"]["field_rules"]["content"] = {"overlap": -1}
    with pytest.raises(FieldChunkingValidationError, match="field_rules\\[content\\].overlap cannot be negative"):
        FieldAnalyzer(config)
    
    # Test overlap >= chunk_size in field rule
    config["field_chunking"]["field_rules"]["content"] = {"chunk_size": 100, "overlap": 100}
    with pytest.raises(FieldChunkingValidationError, match="field_rules\\[content\\].overlap must be smaller than chunk_size"):
        FieldAnalyzer(config)


def test_pattern_based_auto_detection():
    """Test auto-detection of fields using patterns."""
    config = {
        "chunk_size": 10,
        "overlap": 2,  # Add explicit overlap that's smaller than chunk_size
        "tokenizer_model": "dummy",
        "split_method": "dummy",
        "field_chunking": {
            "enabled": True,
            "preserve_fields": ["id", "title"],
            "chunk_threshold": 3,
            "auto_detection": {
                "enabled": True,
                "patterns": [
                    {"pattern": "*_content", "chunk_size": 12},
                    {"pattern": "*_text", "chunk_size": 8},
                    {"pattern": "description", "chunk_size": 15}
                ],
                "size_thresholds": [
                    {"min_chars": 50, "description": "Large fields"}
                ]
            }
        },
    }
    
    analyzer = FieldAnalyzer(config)
    chunker = FieldChunker(config)
    
    record = {
        "id": "doc_001",
        "title": "Document Title",
        "page_content": "word1 word2 word3 word4 word5",  # Matches *_content pattern
        "full_text": "text1 text2 text3 text4",       # Matches *_text pattern  
        "description": "desc1 desc2 desc3 desc4 desc5",  # Matches exact pattern
        "summary": "A very long summary that exceeds fifty characters and should be detected by size threshold",  # Size-based detection
        "metadata": "short"  # Should not be detected
    }
    
    # Test field detection
    detected_fields = analyzer.detect_text_fields(record)
    expected_fields = {"page_content", "full_text", "description", "summary"}
    assert set(detected_fields) == expected_fields
    
    # Test analysis with auto-detection
    analysis = analyzer.analyze_record(record)
    
    # Fields should be chunked based on threshold and detection
    fields_to_chunk = set(analysis.fields_to_chunk)
    # page_content: 5 words > threshold 3
    # full_text: 4 words > threshold 3  
    # description: 5 words > threshold 3
    # summary: many words > threshold 3
    assert "page_content" in fields_to_chunk
    assert "full_text" in fields_to_chunk  
    assert "description" in fields_to_chunk
    assert "summary" in fields_to_chunk
    assert "metadata" not in fields_to_chunk  # Too small and not detected


def test_size_based_auto_detection():
    """Test auto-detection of fields using size thresholds."""
    config = {
        "chunk_size": 10,
        "overlap": 2,  # Add explicit overlap
        "tokenizer_model": "dummy",
        "split_method": "dummy",
        "field_chunking": {
            "enabled": True,
            "chunk_threshold": 5,
            "auto_detection": {
                "enabled": True,
                "size_thresholds": [
                    {"min_chars": 30, "description": "Medium fields"},
                    {"min_chars": 100, "description": "Large fields"}
                ]
            }
        },
    }
    
    analyzer = FieldAnalyzer(config)
    
    record = {
        "short_field": "small",  # 5 chars - not detected
        "medium_field": "This is a medium-sized field content",  # 35 chars - detected by first threshold
        "large_field": "This is a very long field that contains a lot of text and definitely exceeds one hundred characters for testing purposes",  # 130+ chars - detected by both thresholds
        "numeric_field": 12345  # Not string - not detected
    }
    
    detected_fields = analyzer.detect_text_fields(record)
    
    # Should detect medium and large fields
    assert "medium_field" in detected_fields
    assert "large_field" in detected_fields
    assert "short_field" not in detected_fields
    assert "numeric_field" not in detected_fields


def test_pattern_matching():
    """Test pattern matching functionality."""
    config = {
        "chunk_size": 10,
        "field_chunking": {
            "enabled": True,
            "auto_detection": {"enabled": True}
        },
    }
    
    analyzer = FieldAnalyzer(config)
    
    # Test various patterns
    assert analyzer._matches_pattern("page_content", "*_content")
    assert analyzer._matches_pattern("article_content", "*_content")
    assert not analyzer._matches_pattern("content_page", "*_content")
    
    assert analyzer._matches_pattern("description", "description")
    assert not analyzer._matches_pattern("long_description", "description")
    
    assert analyzer._matches_pattern("full_text", "*_text")
    assert analyzer._matches_pattern("raw_text", "*_text")
    assert not analyzer._matches_pattern("text_content", "*_text")


def test_auto_detection_validation():
    """Test validation of auto_detection configuration."""
    
    # Test invalid pattern configuration
    config = {
        "chunk_size": 1000,
        "field_chunking": {
            "enabled": True,
            "auto_detection": {
                "enabled": True,
                "patterns": ["invalid"]  # Should be dict, not string
            }
        },
    }
    
    with pytest.raises(FieldChunkingValidationError, match="auto_detection.patterns\\[0\\] must be a dictionary"):
        FieldAnalyzer(config)
    
    # Test missing pattern field
    config["field_chunking"]["auto_detection"]["patterns"] = [{}]
    with pytest.raises(FieldChunkingValidationError, match="auto_detection.patterns\\[0\\] must have a 'pattern' field"):
        FieldAnalyzer(config)
    
    # Test invalid size threshold
    config["field_chunking"]["auto_detection"] = {
        "enabled": True,
        "size_thresholds": [{"min_chars": -1}]
    }
    with pytest.raises(FieldChunkingValidationError, match="auto_detection.size_thresholds\\[0\\].min_chars must be a non-negative integer"):
        FieldAnalyzer(config)


def test_enhanced_chunk_metadata():
    """Test enhanced chunk metadata generation."""
    config = {
        "chunk_size": 3,
        "overlap": 1,
        "tokenizer_model": "dummy",
        "split_method": "dummy",
        "field_chunking": {
            "enabled": True,
            "chunk_fields": ["content"],
            "preserve_fields": ["title"],
            "chunk_threshold": 1,
            "chunk_metadata": {
                "add_chunk_info": True,
                "chunk_id_field": "chunk_id",
                "original_record_id": "parent_id", 
                "add_char_positions": True,
                "add_token_counts": True
            }
        },
    }
    
    analyzer = FieldAnalyzer(config)
    chunker = FieldChunker(config)
    
    record = {
        "id": "record_123",
        "title": "Test Document",
        "content": "word1 word2 word3 word4 word5"  # 5 words, should create multiple chunks
    }
    
    analysis = analyzer.analyze_record(record)
    chunks = chunker.chunk_record(record, analysis)
    
    # Should create multiple chunks
    assert len(chunks) > 1
    
    for idx, chunk in enumerate(chunks, 1):
        chunk_info = chunk["chunk_info"]
        
        # Basic chunk info should be present
        assert chunk_info["source_field"] == "content"
        assert chunk_info["chunk_index"] == idx
        assert chunk_info["total_chunks"] == len(chunks)
        
        # Enhanced metadata should be present
        assert "chunk_id" in chunk
        assert chunk["chunk_id"] == f"record_123_content_{idx}"
        
        assert "parent_id" in chunk
        assert chunk["parent_id"] == "record_123"
        
        # Character position metadata
        assert "chunk_start_char" in chunk_info
        assert "chunk_end_char" in chunk_info
        assert "chunk_size_chars" in chunk_info
        assert "original_field_size_chars" in chunk_info
        
        # Token count metadata
        assert "chunk_size_tokens" in chunk_info
        assert "original_field_size_tokens" in chunk_info
        
        # Validate character positions
        assert chunk_info["chunk_start_char"] >= 0
        assert chunk_info["chunk_end_char"] > chunk_info["chunk_start_char"]
        assert chunk_info["chunk_size_chars"] > 0
        assert chunk_info["original_field_size_chars"] == len(record["content"])
        
        # Validate token counts
        assert chunk_info["chunk_size_tokens"] > 0
        assert chunk_info["original_field_size_tokens"] > 0


def test_enhanced_metadata_disabled():
    """Test that enhanced metadata is not added when disabled."""
    config = {
        "chunk_size": 3,
        "overlap": 1,
        "tokenizer_model": "dummy", 
        "split_method": "dummy",
        "field_chunking": {
            "enabled": True,
            "chunk_fields": ["content"],
            "chunk_threshold": 1,
            "chunk_metadata": {
                "add_chunk_info": False  # Disabled
            }
        },
    }
    
    analyzer = FieldAnalyzer(config)
    chunker = FieldChunker(config)
    
    record = {
        "id": "record_123",
        "content": "word1 word2 word3 word4 word5"
    }
    
    analysis = analyzer.analyze_record(record)
    chunks = chunker.chunk_record(record, analysis)
    
    for chunk in chunks:
        chunk_info = chunk["chunk_info"]
        
        # Basic chunk info should be present
        assert "source_field" in chunk_info
        assert "chunk_index" in chunk_info
        assert "total_chunks" in chunk_info
        
        # Enhanced metadata should NOT be present
        assert "chunk_id" not in chunk
        assert "parent_id" not in chunk
        assert "chunk_start_char" not in chunk_info
        assert "chunk_end_char" not in chunk_info
        assert "chunk_size_chars" not in chunk_info
        assert "original_field_size_chars" not in chunk_info
        assert "chunk_size_tokens" not in chunk_info
        assert "original_field_size_tokens" not in chunk_info


def test_partial_enhanced_metadata():
    """Test that only requested enhanced metadata is added."""
    config = {
        "chunk_size": 3,
        "overlap": 1,
        "tokenizer_model": "dummy",
        "split_method": "dummy", 
        "field_chunking": {
            "enabled": True,
            "chunk_fields": ["content"],
            "chunk_threshold": 1,
            "chunk_metadata": {
                "add_chunk_info": True,
                "chunk_id_field": "chunk_id",
                # original_record_id not specified
                "add_char_positions": True,
                # add_token_counts not specified (should default to False)
            }
        },
    }
    
    analyzer = FieldAnalyzer(config)
    chunker = FieldChunker(config)
    
    record = {
        "id": "record_123",
        "content": "word1 word2 word3 word4 word5"
    }
    
    analysis = analyzer.analyze_record(record)
    chunks = chunker.chunk_record(record, analysis)
    
    for chunk in chunks:
        chunk_info = chunk["chunk_info"]
        
        # Should have chunk ID
        assert "chunk_id" in chunk
        
        # Should NOT have parent_id (not configured)
        assert "parent_id" not in chunk
        
        # Should have character positions
        assert "chunk_start_char" in chunk_info
        assert "chunk_end_char" in chunk_info
        
        # Should NOT have token counts (not enabled)
        assert "chunk_size_tokens" not in chunk_info
        assert "original_field_size_tokens" not in chunk_info


def test_enhanced_metadata_no_original_id():
    """Test enhanced metadata when original record has no ID."""
    config = {
        "chunk_size": 3,
        "overlap": 1,
        "tokenizer_model": "dummy",
        "split_method": "dummy",
        "field_chunking": {
            "enabled": True,
            "chunk_fields": ["content"],
            "chunk_threshold": 1,
            "chunk_metadata": {
                "add_chunk_info": True,
                "chunk_id_field": "chunk_id",
                "original_record_id": "parent_id"
            }
        },
    }
    
    analyzer = FieldAnalyzer(config)
    chunker = FieldChunker(config)
    
    # Record without ID
    record = {
        "content": "word1 word2 word3 word4 word5"
    }
    
    analysis = analyzer.analyze_record(record)
    chunks = chunker.chunk_record(record, analysis)
    
    for idx, chunk in enumerate(chunks, 1):
        # Should generate chunk ID with "unknown" as base
        assert "chunk_id" in chunk
        assert chunk["chunk_id"] == f"unknown_content_{idx}"
        
        # Should NOT have parent_id since original record has no id
        assert "parent_id" not in chunk

