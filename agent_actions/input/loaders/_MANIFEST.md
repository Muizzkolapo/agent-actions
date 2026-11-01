# Loaders Manifest

## Overview

Input loaders convert raw files (JSON, XML, CSV, text, etc.) into structured data
while providing retry, async, and error-handling helpers used across batch + online
processing.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `base.py` | Module | Abstract loader base with retry/async helpers plus the `BaseLoader`/`IDataLoader` plumbing for derived loaders. | `config.interfaces`, `processing.error_handling` |
| `retry` | Function | File operation retry decorator used by `BaseLoader.load_file`/`load_file_async`. | `processing.error_handling` |
| `BaseLoader` | Class | Generic loader with `load_file(_async)`, `process(_async)`, and `supports_filetype` contracts. | `config.interfaces`, `typing` |
| `file_reader.py` | Module | Convenience reader for PDFs, DOCX, HTML, Excel, XML, Markdown, and other user-facing file types with rich error handling. JSON is parsed with `utils.deep_json.loads`, so a record nested past the JSON decoder's recursion limit stages. JSON is read as `utf-8-sig`, so a byte order mark is not part of the document. CSV is read with `newline=""` and `utf-8-sig`, as `TabularLoader` reads it. | `processors`, `logging` |
| `json.py` | Module | `JsonLoader` that parses JSON strings or files via `process(content, file_path)`, returning parsed dicts/lists with structured error reporting. Parses with `utils.deep_json.loads`, so nesting depth is not limited by the JSON decoder's recursion. A leading byte order mark, read from a file or handed in a string, is dropped first, as `FileReader` drops it. | `errors`, `json` |
| `source_data.py` | Module | `SourceDataLoader` that loads source data via storage backend (`read_source`), requiring a `StorageBackend` at init. | `config.interfaces`, `errors`, `storage.backend` |
| `tabular.py` | Module | `TabularLoader` for CSV/TSV content; reads the file with `newline=""` and `utf-8-sig` through `csv.DictReader`, so a quoted cell keeps its line breaks and a byte order mark is not part of the first column name, and wraps parsing errors in `AgentActionsError`. | `errors`, `logging` |
| `udf.py` | Module | Discovers user-defined functions (UDFs) under `user_code` by importing only modules that declare a tool-registering decorator (`udf_tool`/`expectation_check`) and validating `impl` references. `expectation_check` files register project-defined expectation types into `agent_actions.expectations.registry` as an import side effect, before preflight validates `type:` names. Given a `skipped` list (as `agac run` passes it), a file that fails to import is appended to it and dropped with whatever it registered, and discovery goes on; without one (`validate-udfs`, `list-udfs`) it raises `UDFLoadError`. | `utils.module_loader`, `utils.udf_management`, `errors` |
| `xml.py` | Module | `XmlLoader` that parses XML text into `ElementTree` roots, exposes helper for turning elements to dicts, and surfaces parse metadata. | `errors`, `xml` |
| `data_source.py` | Module | `DataSourceType` enum, `DataSourceConfig` model, and resolver that maps `data_source` config values to concrete directories (staging, local, API). | `config`, `errors`, `pydantic` |
