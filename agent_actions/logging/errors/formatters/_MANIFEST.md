# Error Formatters Manifest

## Overview

Custom formatters that render HTTP/API errors, authentication issues, and YAML/
configuration errors with consistent context for CLI output.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `api.py` | Module | Formats API responses and HTTP errors. Its message-word match does not claim a `PreFlightValidationError`. | `logging`, `errors` |
| `authentication.py` | Module | Formats authentication/credential errors. Its message-word match does not claim a `PreFlightValidationError`, so a refusal for an unset key variable keeps its own words. | `logging`, `security` |
| `base.py` | Module | Base formatter helpers (message templating, context formatting). `_is_preflight_refusal` tells a formatter that matches message words to leave a `PreFlightValidationError` alone. `_workflow_and_action` gives the `agent` (the workflow), `action_name` (the action) and `origin` (the branch an included action comes from) a context names, leaving out a `None` or blank value, for a formatter that builds its own context. | `logging`, `errors` |
| `configuration.py` | Module | Formats configuration/schema validation failures. A `PreFlightValidationError` keeps its own message and hint whatever words it contains. An error whose text mentions schema validation shows a `SchemaValidationError`'s report, or else its own message, and the hint it carries as the fix; the generic "configuration format is invalid" text is only for an error with no message. The "Invalid configuration" title names the agent only when the context has one, and the missing environment variable error and the missing required fields error keep the `agent` and `action_name` they were given. The missing required fields error never takes the agent as the action, and its problem text does not repeat the action shown on the `Action:` line; when the error lists no field, the problem text is the error's own message. | `configuration`, `logging` |
| `file.py` | Module | Formats file-related errors (IO, permission). Its message-word match does not claim a `PreFlightValidationError`. A failed file operation shows the `hint` its error carries in `context`, else the permissions-and-paths catch-all. | `file_io`, `logging` |
| `function.py` | Module | Formats errors arising from UDF/tool function calls. Its message-word match does not claim a `PreFlightValidationError`. A function not found keeps the `agent` and `action_name` it was given, so the action that names the function shows on the `Action:` line. | `utils.udf_management`, `logging` |
| `generic.py` | Module | Generic formatter used as the default when no specific formatter is configured. | `logging` |
| `model.py` | Module | Formats model-specific error details (token usage, rate limits). Its message-word match does not claim a `PreFlightValidationError`. | `llm.providers`, `logging` |
| `template.py` | Module | Formats template rendering issues with namespace diagnostics, fuzzy field suggestions, and actionable hints. Keeps the `agent` (the workflow) and `action_name` (the action whose template failed) it was given; the title names the agent only when the context has one. | `prompt_generation`, `logging` |
| `udf_load.py` | Module | Formats UDF discovery import failures with module, file, and dependency install hint. Keeps the `agent` and `action_name` it was given. | `utils.udf_management`, `logging` |
| `yaml.py` | Module | Formats YAML parsing errors with line/column details. Keeps the `agent` and `action_name` it was given. Names the fix for a bare `?` inside an inline list or mapping: quote the optional observe entry. | `yaml`, `logging` |
