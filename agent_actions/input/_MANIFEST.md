# Input Manifest

## Overview

Input package centralizes context helpers, file loaders, and preprocessing pipelines
for the Agent Actions workflow (context scope normalization, guard evaluation,
and chunking/lineage support).

## Sub-Modules

| Sub-Module | Description |
|------------|-------------|
| [context](context/_MANIFEST.md) | Context normalization, historical node retrieval, and context_scope expansion helpers. |
| [loaders](loaders/_MANIFEST.md) | File loaders for JSON/XML/text/tabular/UDF discovery and asynchronous base classes. |
| [preprocessing](preprocessing/_MANIFEST.md) | Chunking, filter parsing, field resolution, stage bootstrapping, and transformation helper packages. |
