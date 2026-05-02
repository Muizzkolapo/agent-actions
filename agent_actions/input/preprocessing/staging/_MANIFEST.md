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
| `field_validation.py` | Module | `validate_staging_field_names` — rejects staging records whose field names collide with reserved prompt-context namespaces (`source`, `version`, `workflow`, etc.). Called at two points: staging file load (initial_pipeline) and prompt context build (scope_builder). | `utils.constants`, `errors` |

## Design Notes

### CSV/XML double I/O in `_prepare_batch_data` / `_prepare_online_data`

FileReader reads every input file first and populates `ctx.content`, but CSV and XML loaders
re-read the file directly via `file_path` because FileReader returns pre-parsed types they
can't use (`list[list]` for CSV, `(tree, root)` for XML). XLSX uses `ctx.content` directly
since FileReader already returns `list[dict]` via pandas.

This means CSV/XML files are read twice (once wasted). A follow-up could skip FileReader
entirely for these file types.

### Reserved namespace collision guard (`field_validation.py`)

Staging records can have arbitrary user-defined field names. The framework reserves
certain top-level names (`source`, `version`, `workflow`, `seed`, etc.) as prompt-context
namespaces. If a staging field collides, the value is silently mis-routed at prompt-build
time (e.g., `source.page_content` resolves to the wrong data).

The guard runs at two convergence points:
1. **Staging file load** — `process_initial_stage()` calls it before any processing
2. **Prompt context build** — `_load_source_namespace()` in `scope_builder.py` calls it
   as a belt-and-suspenders check, catching data that entered through storage reads,
   batch resume, or FILE mode source resolution

The reserved names come from `SPECIAL_NAMESPACES` in `utils/constants.py`.

### Zero-success failure check (`initial_pipeline.py`)

Mirrors the check in `workflow/pipeline.py`. See `workflow/_MANIFEST.md` design note for
full rationale on why `stats.success == 0` is used instead of `not output`.
