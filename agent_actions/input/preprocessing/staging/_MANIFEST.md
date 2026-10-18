# Staging Manifest

## Sub-Modules

| Sub-Module | Description |
|------------|-------------|
| (none) | Initial-stage logic lives at this level. |

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `__init__.py` | Module | Module docstring describing the staging helpers. | `preprocessing` |
| `initial_pipeline.py` | Module | `process_initial_stage` entry point plus validation, source saving, mode-specific preparation helpers, re-stamping a staged record whose content another row already claimed under a DIFFERENT relative_path this run — so it keeps its own identity rather than being dropped on write — while a claim under the SAME relative_path (two actions sharing one staged file) is left alone, and storage-backend requirements for first-stage target writes. In batch mode a staged file is named by `batch_file_identity`; the input owning a nested file's basename is a file directly under the staging root that the walk processes (`_staged_at_the_top`, the runner's `should_skip_item` with the start node's `file_type_filter`, which `InitialStageContext` carries) and that stores under that name. An online first-stage write clears that file's checkpoint rows, under the `.json` name it stores the file under, and is followed by the SUCCESS and PASSTHROUGH dispositions collection held back, as `pipeline.py` does; like it, it writes a file in which nothing succeeded, then raises, only where `stored_answers_stand` says the answers stored for it no longer stand. `_read_staged_file` reads a staged `.csv`/`.tsv` with `TabularLoader` into rows (anything else with `FileReader`), the loader preparation reads it with, so the template check sees the records the run envelopes. The reserved-name check (`validate_staging_field_names`) is not applied to a delimited file: it always skipped one, read as lists of cells, and a CSV column named like a namespace stages as it did. The template check renders the first record of a record format (`.json`, `.csv`, `.tsv`, `.xlsx`) as staging envelopes it, and of a text format (`.txt`, `.md`, `.html`, `.pdf`, `.docx`) the first chunk `_text_chunk_payloads` makes, `{"content": <chunk>}`, the one both run modes stage; a missing `source` field there is refused with a message naming `source.content`. The template check ahead of preparation (`_validate_staged_data`) and both run modes' preparation read the run's workflow metadata, with the file as `source_file`, and the context `ProcessingPipeline._build_pipeline_context` builds (version, action indices, dependency configs), so a prompt reading `workflow.*` or `version.*` renders in the check as it does for the records. In a repair, the online write notes what it changed in the file for the actions below (`repair_lineage.note_rewritten_by_repair`), so a first action that splits a repaired record has its new rows named below it. | `processing`, `output`, `logging`, `llm.batch`, `workflow` |
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
time (e.g., `source.content` resolves to the wrong data).

The guard runs at two convergence points:
1. **Staging file load** — `process_initial_stage()` calls it before any processing
2. **Prompt context build** — `SourceNamespaceBuilder.build()` in `scope_builder.py` calls it
   as a belt-and-suspenders check, catching data that entered through storage reads,
   batch resume, or FILE mode source resolution

The reserved names come from `SPECIAL_NAMESPACES` in `utils/constants.py`.

### Zero-success failure check (`initial_pipeline.py`)

Delegates to `CollectionStats.terminal_failure()` (in
`processing/result_collector.py`), and writes the file before raising only where
`stored_answers_stand` says the answers stored for it no longer stand. See
`workflow/_MANIFEST.md` design note for full rationale on why `stats.success == 0` is
used instead of `not output`, and for that exception.
