# Input Manifest

## Overview

Input package centralizes context helpers, file loaders, and preprocessing pipelines
for the Agent Actions workflow (context scope normalization, guard evaluation,
and chunking/lineage support).

## Sub-Modules

| Sub-Module | Description |
|------------|-------------|
| [context](context/_MANIFEST.md) | Context normalization, historical node retrieval, and context_scope expansion helpers. |
| [loaders](loaders/_MANIFEST.md) | File loaders for JSON/XML/text/tabular/UDF discovery and asynchronous base classes. |
| [preprocessing](preprocessing/_MANIFEST.md) | Chunking, filter parsing, field resolution, stage bootstrapping, and transformation helper packages. |

## Project Surface

> How this module interacts with the user's project files.

| Symbol | User File | Interaction | Config Key |
|--------|-----------|-------------|------------|
| `resolve_start_node_data_source()` | `agent_io/staging/` | Reads | `data_source` |
| `resolve_start_node_data_source()` | `{local_folder}/` | Reads | `data_source.folder` |
| `FileReader.read()` | `agent_io/staging/*.json` | Reads | — |
| `FileReader.read()` | `agent_io/staging/*.csv` | Reads | — |
| `FileReader.read()` | `agent_io/staging/*.xml` | Reads | — |
| `FileReader.read()` | `agent_io/staging/*.pdf` | Reads | — |
| `FileReader.read()` | `agent_io/staging/*.docx` | Reads | — |
| `FileReader.read()` | `agent_io/staging/*.xlsx` | Reads | — |
| `JsonLoader.process()` | `agent_io/staging/*.json` | Reads | — |
| `TabularLoader.process()` | `agent_io/staging/*.csv` | Reads | — |
| `XmlLoader.process()` | `agent_io/staging/*.xml` | Reads | — |
| `SourceDataLoader.load_source_data()` | `agent_io/target/{workflow}.db` | Reads | — |
| `SourceDataLoader.save_source_data()` | `agent_io/target/{workflow}.db` | Writes | — |
| `discover_udfs()` | `user_code/**/*.py` | Reads | — |
| `validate_udf_references()` | `agent_config/{workflow}.yml` | Validates | `impl` |
| `normalize_all_agent_configs()` | `agent_config/{workflow}.yml` | Transforms | `context_scope` |
| `HistoricalNodeDataLoader.load_historical_node_data()` | `agent_io/target/{workflow}.db` | Reads | — |
| `process_initial_stage()` | `agent_io/staging/*` | Reads | `run_mode`, `record_limit` |
| `Tokenizer.split_text_content()` | `agent_io/staging/*.txt` | Transforms | `chunk_config.chunk_size`, `chunk_config.overlap` |
| `GuardFilter.evaluate()` | `agent_config/{workflow}.yml` | Validates | `where_clause` |
| `GuardEvaluator.evaluate()` | `agent_config/{workflow}.yml` | Validates | `guards` |

**Internal only**: `ContextPreprocessor.extract_guid_and_content()` — extracts metadata from inter-node context payloads, no direct project file surface. `_expand_list_directive()` — internal helper for `normalize_context_scope()`.

**Examples** — see this module in action:
- [`examples/product_listing_enrichment/agent_workflow/product_listing_enrichment/agent_io/staging/`](../../examples/product_listing_enrichment/agent_workflow/product_listing_enrichment/agent_io/staging/) — staging input files read by `FileReader` and loaders
- [`examples/book_catalog_enrichment/agent_workflow/book_catalog_enrichment/agent_io/staging/`](../../examples/book_catalog_enrichment/agent_workflow/book_catalog_enrichment/agent_io/staging/) — staging directory resolved by `resolve_start_node_data_source()`
- [`examples/support_resolution/agent_workflow/support_resolution/agent_io/staging/`](../../examples/support_resolution/agent_workflow/support_resolution/agent_io/staging/) — staging input files demonstrating multi-format loading
