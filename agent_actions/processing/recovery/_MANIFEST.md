# Recovery Manifest

## Overview

Transport-layer retry tracking and the shared response validators processors
use to judge an LLM response.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `response_validator.py` | Module | Shared `ResponseValidator` protocol (`UdfValidator`, `SchemaValidator`, `ComposedValidator`) and `build_validation_feedback()`. | `validation`, `schema` |
| `retry.py` | Module | Retry helpers with backoff used across processing pipelines. | `retry`, `logging` |
