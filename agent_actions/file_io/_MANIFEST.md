# File Io Manifest

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `file_handler.py` | Module | Shared file and directory operations utilities. | - |
| `FileHandler` | Class | A class for handling file and directory operations. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `find_file_in_directory` | Method | Recursively searches for a file in a directory. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `find_specific_folder` | Method | Search for a specific folder within a directory specified by the parent folder name. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `find_agent_folder` | Method | Searches for a specific folder within the base directory. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_agent_paths` | Method | Returns the agent configuration directory, IO directory, and sample output path. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `find_config_file` | Method | Recursively searches for a configuration file in the base directory and its parents. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_folder_after_agent_config` | Method | Extracts the folder name immediately following 'agent_config' in a path. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_folder` | Method | Gets the folder name and full path for an agent's configuration. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_all_agent_paths` | Method | Gets all agent configuration file paths within the base directory. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_file_info` | Method | Gets information about a file in the staging directory. | - |
| `file_writer.py` | Module | Shared file writing utilities. | `errors`, `utilities` |
| `FileWriter` | Class | File writer utility for writing data to various file formats. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `write_staging` | Method | Write data to staging file in appropriate format. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `write_target` | Method | Write data to target file in JSON format. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `write_source` | Method | Write data to source file in JSON format. | - |
| `unified_source_data_saver.py` | Module | Unified source data saving across batch and online modes. | - |
| `SourceSaveMode` | Class | Source data save modes. | - |
| `UnifiedSourceDataSaver` | Class | Unified source data saver with configurable deduplication and locking. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `save_source_items` | Method | Save source data with optional deduplication and locking. | - |
| `get_source_data_saver` | Function | Get UnifiedSourceDataSaver instance with mode-specific defaults. | - |
