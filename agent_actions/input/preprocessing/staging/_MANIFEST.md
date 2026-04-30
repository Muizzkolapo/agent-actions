# Staging Manifest

## Sub-Modules

| Sub-Module | Description |
|------------|-------------|
| (none) | Initial-stage logic lives at this level. |

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `__init__.py` | Module | Module docstring describing the staging helpers. | `preprocessing` |
| `initial_pipeline.py` | Module | `process_initial_stage` entry point plus validation, source saving, mode-specific preparation helpers, and storage-backend requirements for first-stage target writes. Delegates workflow root discovery to `utils.path_utils.derive_workflow_root`. Uses `_to_source_table_row` to flatten admitted (hoisted) records back to canonical raw shape before persisting to `source_data`. | `processing`, `output`, `logging`, `utils.path_utils`, `record.envelope` |

## Design Notes

### CSV/XML double I/O in `_prepare_batch_data` / `_prepare_online_data`

FileReader reads every input file first and populates `ctx.content`, but CSV and XML loaders
re-read the file directly via `file_path` because FileReader returns pre-parsed types they
can't use (`list[list]` for CSV, `(tree, root)` for XML). XLSX uses `ctx.content` directly
since FileReader already returns `list[dict]` via pandas.

This means CSV/XML files are read twice (once wasted). A follow-up could skip FileReader
entirely for these file types.

### Zero-success failure check (`initial_pipeline.py`)

Mirrors the check in `workflow/pipeline.py`. See `workflow/_MANIFEST.md` design note for
full rationale on why `stats.success == 0` is used instead of `not output`.

### Source-table flattening (`_to_source_table_row`)

After `RecordEnvelope.admit_staging_row` hoists raw fields into `record["source"]`, the
record envelope shape is no longer the canonical "flat row" shape that the `source_data`
table is built around. `_save_source_data` calls `_to_source_table_row` to flatten an
admitted record back to its raw shape before persisting -- otherwise the `source_data`
table would have a single nested `source` column instead of per-field columns. This
isolates envelope shape from storage shape: bus reads from `record["source"]`, while
`source_data` keeps its original flat schema.
