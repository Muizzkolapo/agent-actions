# Prompt Context Manifest

## Overview

Context helpers build the field-context used by prompts and guards, with static
loaders for cataloging prompts at documentation time.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `builder.py` | Module | `ContextBuilder` helpers that resolve field references into prompt context data. | `preprocessing`, `validation` |
| `scope.py` | Module | `ContextScopeProcessor` that normalizes context_scope, expands versioned dependencies, loads historical fields, and provides namespace-aware file-mode observe filtering via `apply_observe_for_file_mode`. | `preprocessing`, `validation` |
| `static_loader.py` | Module | Static prompt loader used during docs generation to read prompt store files. | `tooling.docs`, `file_io` |
