# Context Manifest

## Overview

Context helpers for building rich guard/filter contexts and normalizing
`context_scope` directives across workflows.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `normalizer.py` | Module | Expands `context_scope` directives in-place, mutating agent configs during preprocessing. | `validation`, `filtering` |
| `normalize_context_scope` | Function | Expands versioned references (e.g., `generate_distractors.*`) per directive registry while preserving dict directives. Calls `split_optional_observe` first, and expands the references under `optional` as it expands `observe`. | `prompt_generation`, `validation` |
| `normalize_all_agent_configs` | Function | Walks execution order, builds version-name maps, and normalizes `context_scope` in-place (overwrites raw with expanded form). | `preprocessing`, `validation` |
| `split_optional_observe` | Function | The one reader of both optional `observe` forms (`a.b?` and `{field: a.b, optional: true, default: x}`): leaves the plain reference in `observe` and `a.b: x` under `optional`, which a workflow does not write by hand and `DIRECTIVE_REGISTRY` does not list. Refuses an optional wildcard, a `?` anywhere but the end, a malformed mapping, and an optional form under `passthrough` or `drop`. Idempotent; called by the `ActionConfig`/`DefaultsConfig` validators, by `deep_merge_context_scope` and by `normalize_context_scope`. | `validation`, `preprocessing` |
| `observe_entry_reference` | Function | The plain reference one observe entry names, in either form, refusing nothing; for readers of a file still being written (the LSP indexer, the load's deferred-value check). | `validation` |
