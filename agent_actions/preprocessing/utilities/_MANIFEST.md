# Utilities Manifest

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `source_path_manager.py` | Module | Module for managing source paths and files. | `cli` |
| `SourcePathManager` | Class | Manages source paths and file operations (Single Responsibility Principle). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_source_path` | Method | Get the source path for a given file path. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `ensure_source_directory` | Method | Ensure the source directory exists. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `load_source_content` | Method | Load source content based on the input documentation's source_guid. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `save_source_content` | Method | Save content to source file. | - |
