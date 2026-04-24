# Transformation Manifest

## Overview

Passthrough transformation helpers that merge context_scope or precomputed fields
into generated data and ensure outputs remain structured.

## Sub-Modules

| Sub-Module | Description |
|------------|-------------|
| [strategies](strategies/_MANIFEST.md) | Strategy implementations (precomputed/context_scope/no-op/default) used by the transformer. |

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `passthrough.py` | Module | `PassthroughTransformer` orchestrates context_scope.passthrough + structured vs unstructured data using the strategy list. Wraps strategy output via `RecordEnvelope.build()`. | `field_management`, `record.envelope` |
| `PassthroughTransformer` | Class | Applies the first matching strategy (which returns flat action output dicts), wraps each via `RecordEnvelope.build()` to namespace and preserve upstream, and ensures each item has required IDs/metadata. | `field_management`, `record.envelope` |
