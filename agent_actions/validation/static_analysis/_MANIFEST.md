# Static Analysis Manifest

## Overview

Static analyzers scan workflows for field references, schema mismatches, and
dependency graph issues before running.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `analyzer.py` | Module | Static analyzer that walks agent configs and reports invalid field usage. | `validation`, `preprocessing` |
