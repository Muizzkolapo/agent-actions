# Error Formatters Manifest

## Overview

Custom formatters that render HTTP/API errors, authentication issues, and YAML/
configuration errors with consistent context for CLI output.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `api.py` | Module | Formats API responses and HTTP errors. Its message-word match does not claim a `PreFlightValidationError`. | `logging`, `errors` |
| `authentication.py` | Module | Formats authentication/credential errors. Its message-word match does not claim a `PreFlightValidationError`, so a refusal for an unset key variable keeps its own words. | `logging`, `security` |
| `base.py` | Module | Base formatter helpers (message templating, context formatting). `_is_preflight_refusal` tells a formatter that matches message words to leave a `PreFlightValidationError` alone. | `logging`, `errors` |
| `configuration.py` | Module | Formats configuration/schema validation failures. A `PreFlightValidationError` keeps its own message and hint whatever words it contains. An error whose text mentions schema validation shows a `SchemaValidationError`'s report, or else its own message, and the hint it carries as the fix; the generic "configuration format is invalid" text is only for an error with no message. | `configuration`, `logging` |
| `file.py` | Module | Formats file-related errors (IO, permission). Its message-word match does not claim a `PreFlightValidationError`. | `file_io`, `logging` |
| `function.py` | Module | Formats errors arising from UDF/tool function calls. Its message-word match does not claim a `PreFlightValidationError`. | `utils.udf_management`, `logging` |
| `generic.py` | Module | Generic formatter used as the default when no specific formatter is configured. | `logging` |
| `model.py` | Module | Formats model-specific error details (token usage, rate limits). Its message-word match does not claim a `PreFlightValidationError`. | `llm.providers`, `logging` |
| `template.py` | Module | Formats template rendering issues with namespace diagnostics, fuzzy field suggestions, and actionable hints. | `prompt_generation`, `logging` |
| `udf_load.py` | Module | Formats UDF discovery import failures with module, file, and dependency install hint. | `utils.udf_management`, `logging` |
| `yaml.py` | Module | Formats YAML parsing errors with line/column details. | `yaml`, `logging` |
