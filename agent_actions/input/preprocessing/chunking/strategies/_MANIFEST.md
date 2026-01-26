# Chunking Strategies Manifest

## Sub-Modules

| Sub-Module | Description |
|------------|-------------|
| (none) | Strategy helpers live at this level. |

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `__init__.py` | Module | Re-exports chunking/fallback/metadata strategies and config validator for convenient imports. | `field_chunking`, `preprocessing` |
| `chunking_strategies.py` | Module | `ChunkingStrategy` base class plus `Tiktoken`, `CharBased`, and `Spacy` implementations used by `FieldChunker`. | `field_chunking`, `transformation` |
| `fallback_strategies.py` | Module | `FallbackStrategy` interface with `PreserveOriginal`, `Truncate`, `Skip`, and `Error` behaviors for oversize/excess cases. | `chunking`, `processing` |
| `metadata_strategies.py` | Module | `MetadataStrategy` base plus `BasicMetadataStrategy`, `EnhancedMetadataStrategy`, and supporting `MetadataContext`. | `chunking`, `logging` |
| `validation.py` | Module | `ConfigValidator` that sanity-checks chunker/analyzer configurations before runtime. | `chunking`, `configuration` |
