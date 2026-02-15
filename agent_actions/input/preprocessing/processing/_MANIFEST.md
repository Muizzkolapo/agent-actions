# Processing Manifest

## Sub-Modules

| Sub-Module | Description |
|------------|-------------|
| (none) | Processing is implemented directly in this package. |

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `__init__.py` | Module | Package docstring for the processing helpers. | `preprocessing` |
| `data_processor.py` | Module | `DataProcessor` class (registered via DI) that runs `transform_with_passthrough` and handles errors. | `processing`, `output`, `validation` |
