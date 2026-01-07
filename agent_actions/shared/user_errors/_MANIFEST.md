# User Errors Manifest

## Sub-Modules

| Sub-Module | Description |
|------------|-------------|
| [formatters](formatters/_MANIFEST.md) | Error formatter strategies. |
| [services](services/_MANIFEST.md) | Error formatting support services. |

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `error_translator.py` | Module | Error translation facade using formatter strategies. | `utilities` |
| `ErrorTranslator` | Class | Translates Python exceptions to user-friendly errors. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `translate` | Method | Main translation method - converts any exception to UserError. | - |
| `user_error.py` | Module | User-facing error data structure. | - |
| `UserError` | Class | Structured representation of a user-facing error. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `format_for_cli` | Method | Format error for CLI display. | - |
