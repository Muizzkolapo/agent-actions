# Changes

## Summary
- Introduced `FieldAnalyzer` and `FieldChunker` utilities to analyze structured records and split oversized text fields into chunks
- Enhanced `staging_loader` to apply configurable field-level chunking for JSON and CSV sources
- Exposed `FieldAnalysisResult` through `agent_actions.utils` for downstream modules
- Added `tests/unit/test_field_chunking.py` and updated `tests/conftest.py` to stub optional dependencies and use a real logger

## Testing
- `pytest tests/unit/test_field_chunking.py`
