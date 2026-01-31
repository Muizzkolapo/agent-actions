# Error Formatters Manifest

## Overview

Custom formatters that render HTTP/API errors, authentication issues, and YAML/
configuration errors with consistent context for CLI output.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `api.py` | Module | Formats API responses and HTTP errors. | `logging`, `errors` |
| `authentication.py` | Module | Formats authentication/credential errors. | `logging`, `security` |
| `base.py` | Module | Base formatter helpers (message templating, context formatting). | `logging`, `errors` |
| `configuration.py` | Module | Formats configuration/schema validation failures. | `configuration`, `logging` |
| `file.py` | Module | Formats file-related errors (IO, permission). | `file_io`, `logging` |
| `function.py` | Module | Formats errors arising from UDF/tool function calls. | `utils.udf_management`, `logging` |
| `generic.py` | Module | Generic formatter used as the default when no specific formatter is configured. | `logging` |
| `model.py` | Module | Formats model-specific error details (token usage, rate limits). | `llm.providers`, `logging` |
| `template.py` | Module | Formats template rendering issues with namespace diagnostics, fuzzy field suggestions, and actionable hints. | `prompt_generation`, `logging` |
| `yaml.py` | Module | Formats YAML parsing errors with line/column details. | `yaml`, `logging` |
