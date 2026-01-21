# Processing Manifest

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `data_processor.py` | Module | Module for processing generated data. | `configuration`, `errors`, `orchestration`, `utilities` |
| `ProcessItemRequest` | Class | Request parameters for processing a single item. | - |
| `DataProcessor` | Class | Handles post-processing of generated data (Single Responsibility). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `supports_async` | Method | Return True as this processor supports async operations. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_processing_mode` | Method | Return AUTO processing mode to let system choose. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `process_item` | Method | Process a generated data item with transformations. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `separate_side_output` | Method | Separate main output from side output. | - |
