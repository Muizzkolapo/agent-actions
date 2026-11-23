# SQLite Backend Mixins

Plain mixin classes, one per concern, that `SQLiteBackend` (in `../sqlite_backend.py`) composes. `SQLiteBackend` keeps its name, module and import path, its table DDL, connection, storage format check and `close()`; the table-level methods live here. Nothing outside `sqlite_backend.py` should import these modules.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `__init__.py` | Module | Package marker; exports nothing. | — |
| `common.py` | Module | `logger` (named `agent_actions.storage.backends.sqlite_backend`, so log records keep the logger name they had before the split), `_SQL_MAX_PARAMS` (IN-list chunk size under SQLite's 999-parameter default), and `SQLiteHost`, the attributes the mixins use from `SQLiteBackend` — a `StorageBackend` subclass for the type checker only, `object` at runtime. | `logging`, `storage.backend` |
| `codec.py` | Module | `SQLitePayloadCodecMixin`: zlib payload columns against per-`(scope, "<table>.<column>")` dictionaries in `prompt_trace_dictionary` (`_compress`, `_forget_dictionary`, `_dictionary`, `_inflate`), and their readers (`decompress_trace_text`, `payload_text`, `decode_payload` — the last two raise `SerializationError` naming the row). Base of every mixin below except metadata. | `zlib`, `utils.deep_json`, `errors.processing` |
| `SQLitePayloadCodecMixin` | Class | Payload compression and decoding; also holds the dictionary-key constants (`_TARGET_DATA`, `_SOURCE_DATA`, `_CHECKPOINT_DATA`, `_SNAPSHOT`, `_SOURCE_SCOPE`, `_TRACE_TEXT_COLUMNS`). | — |
| `metadata.py` | Module | `SQLiteMetadataMixin`: `workflow_metadata` key/value reads, writes and literal-prefix (LIKE-escaped) listing and deletion. | — |
| `SQLiteMetadataMixin` | Class | `workflow_metadata` access. | — |
| `source_data.py` | Module | `SQLiteSourceDataMixin`: `write_source` (fails loud on a blank `source_guid`, fills `repeat_of_source_guid`, `''` when the row repeats nothing, and fails loud on a value that is not a non-empty string), `read_source`, `claim_source_guid_for_run`, `list_source_files`, `source_files_for_records`, `source_guids_among`, `records_share_a_repeat_chain`, `clear_source_data`. | `errors.validation`, `utils.deep_json` |
| `SQLiteSourceDataMixin` | Class | `source_data` access. | — |
| `target_data.py` | Module | `SQLiteTargetDataMixin`: `_write_target_raw` (deletes the file's checkpoint rows in the same transaction), `_read_target_raw(_batch)`, `list_target_files`, `has_target_rows`, `has_target_file`, `preview_target`, `delete_target`, `delete_target_files`. | `storage.backend`, `utils.deep_json` |
| `SQLiteTargetDataMixin` | Class | `target_data` access. | — |
| `dispositions.py` | Module | `SQLiteDispositionMixin`: `set_disposition(s_batch)`, `get_disposition`, `actions_with_dispositions`, `has_disposition`, `get_terminal_record_ids`, `clear_dispositions_batch`, `clear_disposition`. | `storage.backend`, `record` |
| `SQLiteDispositionMixin` | Class | `record_disposition` access. | — |
| `checkpoints.py` | Module | `SQLiteCheckpointMixin`: `save_checkpoint_records`, `read_checkpoint_records`, `clear_checkpoint_records`. | `errors.validation`, `utils.deep_json` |
| `SQLiteCheckpointMixin` | Class | `checkpoint_output` access. | — |
| `prompt_traces.py` | Module | `SQLitePromptTraceMixin`: `write_prompt_trace`, `update_prompt_trace_response`, `get_prompt_traces`, `get_prompt_trace_summary`, `preview_prompt_traces`, `clear_prompt_traces`; trace fields over `_MAX_TRACE_FIELD_SIZE` are replaced by a marker. | `logging` |
| `SQLitePromptTraceMixin` | Class | `prompt_trace` access. | — |
| `maintenance.py` | Module | `SQLiteMaintenanceMixin`: `get_storage_stats`, `perform_maintenance` (WAL checkpoint, stale-disposition cleanup, trace retention, source TTL, VACUUM past `_VACUUM_FREE_FRACTION`), `scan_data`. | `config` |
| `SQLiteMaintenanceMixin` | Class | Store-wide statistics, maintenance and scanning. | — |

## Project Surface

| Symbol | File | Interaction | Config Key |
|--------|------|-------------|------------|
| `SQLiteSourceDataMixin.write_source()` | `agent_io/store/{workflow_name}.db` | Writes | — |
| `SQLiteSourceDataMixin.read_source()` | `agent_io/store/{workflow_name}.db` | Reads | — |
| `SQLiteTargetDataMixin._write_target_raw()` | `agent_io/store/{workflow_name}.db` | Writes | — |
| `SQLiteTargetDataMixin._read_target_raw()` | `agent_io/store/{workflow_name}.db` | Reads | — |
| `SQLiteMetadataMixin._save_metadata_raw()` | `agent_io/store/{workflow_name}.db` | Writes | — |
| `SQLiteDispositionMixin.set_disposition()` | `agent_io/store/{workflow_name}.db` | Writes | — |
| `SQLiteCheckpointMixin.save_checkpoint_records()` | `agent_io/store/{workflow_name}.db` | Writes | — |
| `SQLitePromptTraceMixin.write_prompt_trace()` | `agent_io/store/{workflow_name}.db` | Writes | — |
| `SQLiteMaintenanceMixin.perform_maintenance()` | `agent_io/store/{workflow_name}.db` | Writes | — |

## Dependencies

| Package | Direction | Why |
|---------|-----------|-----|
| `storage.backend` | outbound | Disposition constants, `batch_file_names_key`, and `StorageBackend` for typing |
| `utils` | outbound | `deep_json` encodes and decodes payload rows |
| `errors` | outbound | `SerializationError`, `DataValidationError` |
| `record` | outbound | `GUARD_SKIP` reason read by `get_terminal_record_ids` |
| `logging` | outbound | `DIAGNOSTIC` marks trace-truncation and missing-trace notices |
| `config` | outbound | `StorageDefaults` for maintenance retention defaults |
| `storage.backends.sqlite_backend` | inbound | `SQLiteBackend` composes every mixin here |
