# Chunking Manifest

## Sub-Modules

| Sub-Module | Description |
|------------|-------------|
| [strategies](strategies/_MANIFEST.md) | Strategy classes for field chunking operations. |

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `field_chunking.py` | Module | Utility classes for field-level chunking of structured data. | `preprocessing` |
| `FieldChunkingValidationError` | Class | Raised when field chunking configuration is invalid. | - |
| `FieldChunkingError` | Class | Raised when field chunking operations fail. | - |
| `FieldAnalysisResult` | Class | Result from analysing a record for chunking needs. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `requires_chunking` | Method | Return True if any fields require chunking. | - |
| `AnalyzerConfig` | Class | Configuration for field analyzer. | - |
| `FieldAnalyzer` | Class | Analyse structured records to determine which fields need chunking. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `analyze_record` | Method | Analyze a record to determine which fields need chunking. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `should_chunk_field` | Method | Determine if a field should be chunked based on token count and rules. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `detect_text_fields` | Method | Automatically detect text fields based on content size. | - |
| `ChunkMetadataParams` | Class | Parameters for creating chunk metadata. | - |
| `ChunkerConfig` | Class | Configuration for field chunker. | - |
| `FieldChunker` | Class | Chunk specific fields within structured records. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `chunk_record` | Method | Chunk a record by processing each field separately (not cartesian product). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `chunk_field` | Method | Chunk a specific field value using field-specific or global rules. | - |
