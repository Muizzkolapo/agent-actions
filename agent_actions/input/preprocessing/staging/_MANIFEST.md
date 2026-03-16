# Staging Manifest

## Sub-Modules

| Sub-Module | Description |
|------------|-------------|
| (none) | Initial-stage logic lives at this level. |

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `__init__.py` | Module | Module docstring describing the staging helpers. | `preprocessing` |
| `initial_pipeline.py` | Module | `process_initial_stage` entry point plus validation, source saving, mode-specific preparation helpers, and storage-backend requirements for first-stage target writes. Delegates workflow root discovery to `utils.path_utils.derive_workflow_root`. | `processing`, `output`, `logging`, `utils.path_utils` |

## Design Notes

### CSV/XML double I/O in `_prepare_batch_data` / `_prepare_online_data`

FileReader reads every input file first and populates `ctx.content`, but CSV and XML loaders
re-read the file directly via `file_path` because FileReader returns pre-parsed types they
can't use (`list[list]` for CSV, `(tree, root)` for XML). XLSX uses `ctx.content` directly
since FileReader already returns `list[dict]` via pandas.

This means CSV/XML files are read twice (once wasted). A follow-up could skip FileReader
entirely for these file types.
