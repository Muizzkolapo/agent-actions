# Transformation Manifest

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `data_transformer.py` | Module | Data transformation utilities for agent actions. | - |
| `DataTransformer` | Class | Utility class for data transformations. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `ensure_list` | Method | Ensure that the input data is returned as a list. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `remove_schema_objects` | Method | Removes specified keys from a dictionary without side effects. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `update_schema_objects` | Method | Updates data based on structure comparison without side effects. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `transform_structure` | Method | Transforms nested dictionary structure to flat list without side effects. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_content_by_source_guid` | Method | Retrieve content by source_guid without side effects. | - |
| `string_transformer.py` | Module | Module for String Processing Functions | `errors` |
| `StringProcessor` | Class | A class for processing strings, including placeholder replacement and function call processing. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `process_as_string` | Method | Ensures the input text is treated as a plain string. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `call_user_function` | Method | Dynamically loads and executes a user-defined function from the tools folder. | - |
| `Tokenizer` | Class | A class for handling tokenization of text. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `num_tokens_from_string` | Method | Returns the number of tokens in a text string. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `split_text_content` | Method | Split text into chunks of a specified size with a specified overlap. | - |
