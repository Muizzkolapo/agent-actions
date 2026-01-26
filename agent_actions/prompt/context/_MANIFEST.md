# Prompt Context Manifest

## Overview

Context helpers build the field-context used by prompts and guards, with static
loaders for cataloging prompts at documentation time.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `builder.py` | Module | `ContextBuilder` helpers that resolve field references into prompt context data. | `preprocessing`, `validation` |
| `scope.py` | Module | `ContextScopeProcessor` that normalizes context_scope, tracks dependencies, and loads historical fields. | `preprocessing`, `validation` |
| `static_loader.py` | Module | Static prompt loader used during docs generation to read prompt store files. | `tooling.docs`, `file_io` |
