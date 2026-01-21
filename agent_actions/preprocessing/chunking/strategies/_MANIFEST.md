# Strategies Manifest

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `chunking_strategies.py` | Module | Chunking strategies for field-level text processing. | `preprocessing` |
| `ChunkingStrategy` | Class | Abstract base class for text chunking strategies. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `split_text_into_chunks` | Method | Split text content into smaller chunks according to the strategy. | - |
| `TiktokenChunkingStrategy` | Class | Token-based chunking strategy using tiktoken tokenizer. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `split_text_into_chunks` | Method | Split text into chunks based on token count using tiktoken tokenizer. | - |
| `CharBasedChunkingStrategy` | Class | Character-based chunking strategy that splits on character boundaries. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `split_text_into_chunks` | Method | Split text into chunks based on character count. | - |
| `SpacyChunkingStrategy` | Class | Semantic chunking strategy using spaCy sentence boundaries. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `split_text_into_chunks` | Method | Split text into chunks based on spaCy sentence boundaries. | - |
| `fallback_strategies.py` | Module | Fallback strategies for handling edge cases in field chunking. | `preprocessing` |
| `FieldChunkingError` | Class | Raised when field chunking operations fail. | - |
| `FallbackStrategy` | Class | Abstract base class for fallback strategies. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `handle_oversized_field` | Method | Handle field value that exceeds maximum size limit. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `handle_excessive_chunk_count` | Method | Handle field that generates more chunks than allowed limit. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `handle_chunking_error` | Method | Handle errors that occur during field chunking process. | - |
| `PreserveOriginalStrategy` | Class | Fallback strategy that preserves original content in all cases. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `handle_oversized_field` | Method | Preserve the full original field value without any modification. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `handle_excessive_chunk_count` | Method | Preserve all chunks even if they exceed the maximum allowed count. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `handle_chunking_error` | Method | Preserve the original record with error metadata attached. | - |
| `TruncateStrategy` | Class | Fallback strategy that truncates content to fit within specified limits. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `handle_oversized_field` | Method | Truncate field value to the specified maximum size limit. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `handle_excessive_chunk_count` | Method | Limit chunk list to maximum allowed count by truncating excess chunks. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `handle_chunking_error` | Method | Skip the record entirely when chunking error occurs. | - |
| `SkipStrategy` | Class | Fallback strategy that skips problematic content entirely. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `handle_oversized_field` | Method | Skip oversized field by returning empty string. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `handle_excessive_chunk_count` | Method | Skip field with excessive chunks by returning empty list. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `handle_chunking_error` | Method | Skip the record entirely when chunking error occurs. | - |
| `ErrorStrategy` | Class | Fallback strategy that raises errors instead of handling issues gracefully. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `handle_oversized_field` | Method | Raise exception when field exceeds maximum allowed size. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `handle_excessive_chunk_count` | Method | Raise exception when chunk count exceeds maximum allowed limit. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `handle_chunking_error` | Method | Re-raise chunking error with detailed context information. | - |
| `metadata_strategies.py` | Module | Metadata creation strategies for chunk information. | `preprocessing` |
| `MetadataContext` | Class | Context information for metadata creation. | - |
| `MetadataStrategy` | Class | Abstract base class for chunk metadata creation. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `create_metadata` | Method | Create metadata for a chunk. | - |
| `BasicMetadataStrategy` | Class | Basic metadata strategy that creates minimal chunk information. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `create_metadata` | Method | Create basic metadata with only essential chunk information. | - |
| `EnhancedMetadataStrategy` | Class | Enhanced metadata strategy with configurable additional fields. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `create_metadata` | Method | Create enhanced metadata with configurable additional fields. | - |
| `validation.py` | Module | Configuration validation utilities for field chunking. | `preprocessing` |
| `FieldChunkingValidationError` | Class | Raised when field chunking configuration is invalid. | - |
| `ConfigValidator` | Class | Validator for field chunking configuration. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate_field_analyzer_config` | Method | Validate FieldAnalyzer configuration. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `validate_field_chunker_config` | Method | Validate FieldChunker configuration. | - |
