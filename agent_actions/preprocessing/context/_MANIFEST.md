# Context Manifest

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `context_preprocessor.py` | Module | Module for preprocessing context data. | - |
| `ContextPreprocessor` | Class | Handles context data preprocessing (Single Responsibility). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `extract_guid_and_content` | Method | Extract source_guid and content from context data if available. | - |
| `historical_node_loader.py` | Module | Module for loading historical node data from target files using lineage tracking. | `cli` |
| `HistoricalDataRequest` | Class | Request parameters for loading historical node data. | - |
| `HistoricalNodeDataLoader` | Class | Loads historical node data from target directories using lineage tracking. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `load_historical_node_data` | Method | Load historical node data for a specific action from target files. | - |
