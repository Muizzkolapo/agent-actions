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
| `file_reader.py` | Module | Convenience reader for PDFs, DOCX, HTML, Excel, XML, Markdown, and other user-facing file types with rich error handling. | `processors`, `logging` |
| `json.py` | Module | `JsonLoader` that parses JSON strings or files via `process(content, file_path)`, returning parsed dicts/lists with structured error reporting. | `errors`, `json` |
| `source_data.py` | Module | `SourceDataLoader` that loads/saves source data via storage backend (`read_source`/`write_source`), requiring a `StorageBackend` at init. | `config.interfaces`, `errors`, `storage.backend` |
| `tabular.py` | Module | `TabularLoader` for CSV/TSV content; reads via `csv.DictReader` and wraps parsing errors in `AgentActionsError`. | `errors`, `logging` |
| `text.py` | Module | `TextLoader` for plain text/markdown/HTML content with the same fallback/validation pattern as other loaders. | `errors` |
| `udf.py` | Module | Discovers user-defined functions (UDFs) under `user_code` by importing discovered modules and validating `impl` references. | `utils.module_loader`, `utils.udf_management`, `errors` |
| `xml.py` | Module | `XmlLoader` that parses XML text into `ElementTree` roots, exposes helper for turning elements to dicts, and surfaces parse metadata. | `errors`, `xml` |
| `data_source.py` | Module | `DataSourceType` enum, `DataSourceConfig` model, and resolver that maps `data_source` config values to concrete directories (staging, local, API). | `config`, `errors`, `pydantic` |
