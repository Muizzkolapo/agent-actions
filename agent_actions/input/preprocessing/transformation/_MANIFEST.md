# Transformation Manifest

## Sub-Modules

| Sub-Module | Description |
|------------|-------------|
| (none) | Transformation utilities live at this level. |

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `__init__.py` | Module | Module docstring for transformation helpers. | `preprocessing` |
| `transformer.py` | Module | `DataTransformer` utilities for normalizing lists, cloning schema fields, and flattening content lists. | `preprocessing`, `output` |
| `string_transformer.py` | Module | `StringProcessor` (placeholder marker handling, UDF caller) and `Tokenizer` helpers for splitting text via Tiktoken/characters/spaCy/custom methods. | `chunking`, `processing`, `nlp` |
