# Input Loading Manifest

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `base_base_loader.py` | Module | Base class for content loaders. | `configuration`, `response_processing`, `utilities` |
| `BaseLoader` | Class | Abstract base class for all content loaders with async support. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `supports_async` | Method | Return True if this loader supports async operations. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_processing_mode` | Method | Return AUTO processing mode to let system choose. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `load_file` | Method | Safely load a file's content with retry logic. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `load_file_async` | Method | Safely load a file's content asynchronously with retry logic. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `process` | Method | Load and parse content from a file or in-memory input. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `process_async` | Method | Async version of process method. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `load_data` | Method | Implementation of IDataLoader interface. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `load_data_async` | Method | Async implementation of IDataLoader interface. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `supports_filetype` | Method | Return True if this loader can handle the given file extension. | - |
| `data_loaders_base_loader.py` | Module | Compatibility shim for base_loader. | `input_loading` |
| `extractors_source_data_loader.py` | Module | Module for loading source data. | `configuration`, `errors`, `state_management` |
| `SourceDataLoader` | Class | Handles loading source data (Single Responsibility). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `supports_async` | Method | Return True as this loader supports async operations. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_processing_mode` | Method | Return AUTO processing mode to let system choose. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `load_source_data` | Method | Load source data from the source directory. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `save_source_data` | Method | Save source data to the source directory. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `load_source_content` | Method | Load specific content from source file by source_guid. | - |
| `file_reader.py` | Module | Module for reading data loading and processing. | `errors`, `utilities` |
| `FileReader` | Class | File reader for various file formats. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `read` | Method | Read file based on file type. | - |
| `json_loader.py` | Module | JSON content loader implementation. | `errors`, `input_loading` |
| `JsonLoader` | Class | Loader for JSON content. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `process` | Method | Load and return raw JSON content from a file or memory. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `supports_filetype` | Method | Return True if the file extension is supported. | - |
| `tabular_loader.py` | Module | Tabular content loader implementation. | `errors`, `input_loading` |
| `TabularLoader` | Class | Loader for tabular content like CSV and Excel. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `process` | Method | Load and return tabular content from a CSV/TSV file or in-memory content. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `supports_filetype` | Method | Return True if the file extension is supported. | - |
| `template_yaml_loader.py` | Module | Custom YAML loader for handling template syntax in old workflow files. | - |
| `TemplateYamlLoader` | Class | Custom YAML loader that can handle template syntax. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `load_template_yaml` | Method | Load YAML file with template syntax preprocessing. | - |
| `text_loader.py` | Module | Text content loader implementation. | `errors`, `input_loading` |
| `TextLoader` | Class | Loader for text-based content like TXT, MD, PDF, DOCX, and HTML. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `process` | Method | Load and return text content from a file or in-memory content. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `supports_filetype` | Method | Return True if the file extension is supported. | - |
| `udf_loader.py` | Module | UDF Discovery and Validation Module. | `errors`, `utilities` |
| `discover_udfs` | Function | Discover and register all UDFs in the user code directory. | - |
| `validate_udf_references` | Function | Validate that all 'impl' references in config exist in the UDF registry. | - |
| `xml_loader.py` | Module | XML content loader implementation. | `errors`, `input_loading` |
| `XmlLoader` | Class | Loader for XML content. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `process` | Method | Load and return XML root element from a file or in-memory content. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `process_xml_element` | Method | Process an XML element into a dictionary. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `supports_filetype` | Method | Return True if the file extension is supported. | - |
