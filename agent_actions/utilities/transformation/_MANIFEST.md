# Transformation Manifest

## Sub-Modules

| Sub-Module | Description |
|------------|-------------|
| [strategies](strategies/_MANIFEST.md) | Passthrough transformation strategies. |

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `passthrough_transformer.py` | Module | Passthrough Transformation Service. | `utilities` |
| `PassthroughTransformer` | Class | Orchestrates passthrough transformations using Strategy Pattern. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `transform_with_passthrough` | Method | Apply context_scope.passthrough logic to generated data. | - |
