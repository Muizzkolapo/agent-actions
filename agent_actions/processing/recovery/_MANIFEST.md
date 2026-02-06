# Recovery Manifest

## Overview

Retry/reprompt tracking utilities that help processors recover from transient
failures and gather metrics for documentation.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `reprompt.py` | Module | Tracks reprompt attempts and transitions when validation errors occur. | `reprompting`, `validation` |
| `retry.py` | Module | Retry helpers with backoff used across processing pipelines. | `retry`, `logging` |
| `validation.py` | Module | Validates that retry/reprompt policies are well-formed before runs. | `validation` |
