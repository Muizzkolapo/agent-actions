# Staging Manifest

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `staging_content.py` | Module | Module for staging content loading and processing. | `input_loading`, `preprocessing`, `prompt_generation`, `utilities` |
| `StagingContentLoader` | Class | Loads and processes different types of content. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `process_chunks` | Method | Process text chunks. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `process_json_content` | Method | Process JSON content with field chunking support. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `process_tabular_content` | Method | Process tabular content with field chunking support. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `process_xml_content` | Method | Process XML content with field chunking support. | - |
| `staging_loader.py` | Module | Module for staging data loading and processing. | `errors`, `file_io`, `input_loading`, `llm_invocation`, `preprocessing`, `prompt_generation`, `utilities`, `validation` |
| `StagingContext` | Class | Context for staging data processing. | - |
| `DataPreparationContext` | Class | Context for data preparation. | - |
| `BatchProcessingContext` | Class | Context for batch mode processing. | - |
| `generate_staging` | Function | Processes a file by splitting its content into chunks or looping through its objects/rows, | - |
