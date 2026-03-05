# Preprocessing Manifest

## Overview

Preprocessing orchestrates chunking, chunk metadata, guard filtering, field resolution,
and the transformation pipeline that normalizes, stages, and passes inputs to
Agent Actions workflows.

## Sub-Modules

| Sub-Module | Description |
|------------|-------------|
| [chunking](chunking/_MANIFEST.md) | Analyzes long text fields, splits them into chunks, and applies fallback/metadata strategies. |
| [field_resolution](field_resolution/_MANIFEST.md) | Parses/resolves field references, builds evaluation contexts, and validates configurations for guards/prompts. |
| [filtering](filtering/_MANIFEST.md) | Guard filter/batch filtering utilities that evaluate WHERE/conditional clauses with caching and metrics. |
| [parsing](parsing/_MANIFEST.md) | WHERE clause parser, AST nodes, and operator registry helpers for guard evaluation. |
| [processing](processing/_MANIFEST.md) | DataProcessor wrapper registered via DI that runs transforms and splits side outputs. |
| [staging](staging/_MANIFEST.md) | Initial-stage pipeline helpers that prepare source data, create directories, and dispatch to processors. |
| [transformation](transformation/_MANIFEST.md) | Transformers and string helpers that normalize structured/unstructured responses. |

## Modules

(No top-level modules — all functionality is organized in sub-modules above.)
