# Validation Utils Manifest

## Overview

Utility helpers for schema typing, agent configuration, and UDF validation used
across validator modules.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `agent_config_validation_utilities.py` | Module | Helpers for loading config YAML and injecting defaults before validation. | `configuration`, `validation` |
| `schema_type_validator.py` | Module | Validates that referenced schema types are present and well-formed. | `validation`, `schema` |
