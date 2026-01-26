# Chunking Manifest

## Sub-Modules

| Sub-Module | Description |
|------------|-------------|
| [strategies](strategies/_MANIFEST.md) | Chunking/fallback/metadata strategy implementations and configuration validators. |

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `__init__.py` | Module | Package docstring; exposes the chunking helpers for higher-level preprocessing consumers. | `preprocessing` |
| `errors.py` | Module | `FieldChunkingError` / `FieldChunkingValidationError` used by chunking flows and fallback strategies. | `preprocessing`, `processing` |
| `field_chunking.py` | Module | `FieldAnalyzer`, `FieldChunker`, `FieldAnalysisResult`, and metadata/fallback helpers that decide when/how to split long text fields. | `preprocessing`, `staging`, `processing`, `logging` |
