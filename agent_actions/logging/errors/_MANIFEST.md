# Errors Manifest

## Overview

Utilities that convert application errors into user-facing log records, formatters,
and translation helpers for CLI/agent reporting.

## Sub-Modules

| Sub-Module | Description |
|------------|-------------|
| [formatters](formatters/_MANIFEST.md) | Custom formatters for CLI/stderr logging. |
| [services](services/_MANIFEST.md) | Helper services that emit structured error events. |

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `docs_links.py` | Module | The documentation pages that error messages link to: one constant per link, built from one site root. No other module names the docs site, so each link a formatter prints is a constant here. | `errors`, `logging` |
| `translator.py` | Module | Maps internal errors to higher-level user-facing messages (used by CLI); the root cause's text is masked by registered value (`redact_known_secrets`), never by the key-name rules, which would mangle a message that names a config key. | `errors`, `logging` |
| `user_error.py` | Module | Definitions of user-facing error types and helper constructors. `format_for_cli` shows the context's `agent` (the workflow) as `Agent:`, its `action_name` as `Action:` and its `origin` (where an included action comes from) as `Origin:`, for every error that carries one; a priority field whose value is `None` or blank is not shown. A Problem of several lines is followed by a blank line before the context lines. | `errors`, `logging` |
