# Context Manifest

## Overview

Context helpers for building rich guard/filter contexts, loading historical
node data, and normalizing `context_scope` directives across workflows.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `context_preprocessor.py` | Module | Utility for extracting canonical GUID/content pairs from raw context objects passed between agents. | `cli.utils`, `processing` |
| `ContextPreprocessor` | Class | Stateless helper that normalizes nested context payloads (supports chunked records and legacy wrappers). | `processing` |
| `historical.py` | Module | Lineage-aware reader that loads historical node outputs, matches ancestry/parallel records, and exposes log-friendly diagnostics. | `cli.utils`, `logging`, `lineage` |
| `HistoricalDataRequest` | Dataclass | Carries action name, lineage, guid, file paths, and ancestry ids used by the loader to trace upstream values. | `lineage`, `logging` |
| `HistoricalNodeDataLoader` | Class | Main loader that locates target files by node id, reads JSON targets, and applies multi-strategy matching (lineage, parent, root, GUID). | `lineage`, `processing`, `logging` |
| `normalizer.py` | Module | Expands `context_scope` directives in-place, mutating agent configs during preprocessing. | `validation`, `filtering` |
| `normalize_context_scope` | Function | Expands versioned references (e.g., `generate_distractors.*`) per directive registry while preserving dict directives. | `prompt_generation`, `validation` |
| `normalize_all_agent_configs` | Function | Walks execution order, builds version-name maps, and normalizes `context_scope` in-place (overwrites raw with expanded form). | `preprocessing`, `validation` |
