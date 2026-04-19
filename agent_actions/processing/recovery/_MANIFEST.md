# Recovery Manifest

## Overview

Retry/reprompt tracking utilities that help processors recover from transient
failures and gather metrics for documentation.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `critique.py` | Module | LLM critique for stubborn validation failures — builds critique prompts, formats combined feedback, invokes critique LLM. | `critique`, `reprompting` |
| `reprompt.py` | Module | Tracks reprompt attempts and transitions when validation errors occur. | `reprompting`, `validation` |
| `response_validator.py` | Module | Shared `ResponseValidator` protocol (`UdfValidator`, `SchemaValidator`, `ComposedValidator`) and `build_validation_feedback()`. | `validation`, `schema` |
| `retry.py` | Module | Retry helpers with backoff used across processing pipelines. | `retry`, `logging` |
| `validation.py` | Module | Validates that retry/reprompt policies are well-formed before runs. | `validation` |
