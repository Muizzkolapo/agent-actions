# Formatters Manifest

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `api_formatter.py` | Module | API and network error formatter. | - |
| `APIErrorFormatter` | Class | Handles API/network errors. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `can_handle` | Method | Detect API/network errors. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `format` | Method | Handle API/network errors. | - |
| `authentication_formatter.py` | Module | Authentication error formatter. | - |
| `AuthenticationErrorFormatter` | Class | Handles authentication errors. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `can_handle` | Method | Detect authentication errors. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `format` | Method | Handle authentication errors. | - |
| `configuration_formatter.py` | Module | Configuration error formatter. | - |
| `ConfigurationErrorFormatter` | Class | Handles configuration-related errors. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `can_handle` | Method | Detect configuration-related errors. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `format` | Method | Handle configuration errors. | - |
| `error_formatter_base.py` | Module | Base error formatter interface for Strategy Pattern. | - |
| `ErrorFormatter` | Class | Base error formatter strategy. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `can_handle` | Method | Determine if this formatter can handle the given error. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `format` | Method | Format the error into a user-friendly UserError. | - |
| `file_formatter.py` | Module | File operation error formatter. | - |
| `FileErrorFormatter` | Class | Handles file-related errors. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `can_handle` | Method | Detect file-related errors. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `format` | Method | Handle file-related errors. | - |
| `function_formatter.py` | Module | Function/UDF error formatter. | - |
| `FunctionNotFoundFormatter` | Class | Handles function/UDF not found errors with helpful suggestions. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `can_handle` | Method | Detect function not found errors. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `format` | Method | Format function not found errors with suggestions. | - |
| `generic_formatter.py` | Module | Generic/fallback error formatter. | - |
| `GenericErrorFormatter` | Class | Handles unknown/generic errors (fallback formatter). | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `can_handle` | Method | Always returns True - this is the fallback formatter. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `format` | Method | Handle unknown/generic errors. | - |
| `model_formatter.py` | Module | Model validation error formatter. | - |
| `ModelErrorFormatter` | Class | Handles model validation errors. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `can_handle` | Method | Detect model validation errors. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `format` | Method | Handle model validation errors. | - |
| `yaml_formatter.py` | Module | YAML syntax error formatter with code snippets. | - |
| `YAMLSyntaxErrorFormatter` | Class | Handles YAML syntax errors with industry-standard formatting. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `can_handle` | Method | Detect YAML syntax errors. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `format` | Method | Format YAML syntax errors with code snippet and visual indicators. | - |
