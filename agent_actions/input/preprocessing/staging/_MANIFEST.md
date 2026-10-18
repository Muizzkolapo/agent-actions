# Staging Manifest

## Sub-Modules

| Sub-Module | Description |
|------------|-------------|
| (none) | Initial-stage logic lives at this level. |

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `__init__.py` | Module | Module docstring describing the staging helpers. | `preprocessing` |
| `initial_pipeline.py` | Module | `process_initial_stage` entry point plus validation, source saving, mode-specific preparation helpers, re-stamping a staged record whose content another row already claimed under a DIFFERENT relative_path this run — so it keeps its own identity rather than being dropped on write — while a claim under the SAME relative_path (two actions sharing one staged file) is left alone, and storage-backend requirements for first-stage target writes. In batch mode a staged file is named by `batch_file_identity`; the input owning a nested file's basename is a file directly under the staging root that the walk processes (`_staged_at_the_top`, the runner's `should_skip_item` with the start node's `file_type_filter`, which `InitialStageContext` carries) and that stores under that name. An online first-stage write clears that file's checkpoint rows, under the `.json` name it stores the file under, and is followed by the SUCCESS and PASSTHROUGH dispositions collection held back, as `pipeline.py` does; like it, it writes a file in which nothing succeeded, then raises, only where `stored_answers_stand` says the answers stored for it no longer stand. `_read_staged_file` reads a staged `.csv`/`.tsv` with `TabularLoader` into rows (anything else with `FileReader`), the loader preparation reads it with, so the template check sees the records the run envelopes. The reserved-name check (`validate_staging_field_names`) is not applied to a delimited file: it always skipped one, read as lists of cells, and a CSV column named like a namespace stages as it did. The template check (`_validate_staged_data`) renders the first record as the run prepared it, whatever the format (a text format's first chunk is `{"content": <chunk>}`, and a prompt that reads a `source` field there is refused with a message naming `source.content`, `_text_chunk_hint`), after preparation and after the seed-selector row check, so a row no seed covers is refused with its location first; the reads of the actions below the first are then checked against the same rows (`validate_source_reads_below`), refused only where `_rows_hold_every_staged_source` finds the rows conclusive — the walk (`staged_input_fingerprint`, with the start node's `file_type_filter`) stages this file alone, or only text files, whose records all hold `content` alone — and warned of otherwise; it and both run modes' preparation read the run's workflow metadata, with the file as `source_file`, and the context `ProcessingPipeline._build_pipeline_context` builds (version, action indices, dependency configs), so a prompt reading `workflow.*` or `version.*` renders in the check as it does for the records. In a repair, the online write notes what it changed in the file for the actions below (`repair_lineage.note_rewritten_by_repair`), so a first action that splits a repaired record has its new rows named below it. | `processing`, `output`, `logging`, `llm.batch`, `workflow` |
| `field_validation.py` | Module | `validate_staging_field_names` — rejects staging records whose field names collide with reserved prompt-context namespaces (`source`, `version`, `workflow`, etc.). Called at two points: staging file load (initial_pipeline) and prompt context build (scope_builder). `validate_seed_selectors` — at staging file load, refuses a row that no file of a selected seed (`context_scope.seed.*.select_by`) covers, for every row and every action of the workflow, naming the file and the record. `validate_source_reads_below` — at staging file load, checks each `source.<field>` an action below the first stage (reached through `dependencies`, a version merge's by the versions' `version_base_name`) reads in `context_scope.observe`, `passthrough`, its prompt or its guard against the fields the file's prepared rows hold (their union), and refuses an `observe` or a prompt read every render makes (`_source_fields_every_render_reads`: not under an `if` body or a loop, a `default`, a test or a conditional expression; an `if`'s test and a loop's iterable count) that no row holds, naming the action, the field and the file, with the text-chunk hint for a text format or the fields the rows hold otherwise. Below the first stage a record's `source` is its staged row and no action adds to it, so these rows are all it can read. When the rows are not conclusive (the walk stages other files that may hold the field), or the read may not fail a record (a `passthrough` leaves the field out, a guard can test for it with `IS NULL`, a hedged prompt read or `source.get(...)` has a default), it logs a warning instead. References come from `ReferenceExtractor`, the prompt resolved as the seed check resolves it. | `utils.constants`, `errors`, `prompt.context.seed_entry`, `prompt.context.scope_builder`, `processing.source_resolution`, `validation.static_analyzer`, `validation.preflight`, `validation.prompt_required_field_validator` |

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

### Source reads below the first stage (`field_validation.py`)

The first stage's template check renders its first record (#1518, #1522). The actions
below it read `source` too, from the staged row their record came from (by
`source_guid`, then `parent_source_guid`, then the namespace the record carries — all
copies of the staged row), so their reads are checked against the same prepared rows,
before any is stored or sent. Refused: an `observe`, or a prompt read every render
makes, of a field no row of the file holds, which would fail every record from it.
Warned: the same read when another staged file may hold the field; a `passthrough`,
which only leaves the field out; a guard, which can test for the field (`IS NULL`
passes a record without it); and a prompt read under an `if` body or a loop, a
`default`, a test, a conditional expression or `.get()`. A bare `{% if source.x %}`
reads `x` and fails without it, so its test is refused like any read. An empty staging folder stages nothing, so nothing is checked; an
API source stages its fetched rows and is checked against them. A record reaching an
action from another workflow resolves `source` from itself, and only actions below this
first stage are checked.

### Zero-success failure check (`initial_pipeline.py`)

Delegates to `CollectionStats.terminal_failure()` (in
`processing/result_collector.py`), and writes the file before raising only where
`stored_answers_stand` says the answers stored for it no longer stand. See
`workflow/_MANIFEST.md` design note for full rationale on why `stats.success == 0` is
used instead of `not output`, and for that exception.
