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
| `translator.py` | Module | Maps internal errors to higher-level user-facing messages (used by CLI). | `errors`, `logging` |
| `user_error.py` | Module | Definitions of user-facing error types and helper constructors. | `errors`, `logging` |
