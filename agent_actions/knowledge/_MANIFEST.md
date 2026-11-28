# Knowledge Manifest

## Overview

Knowledge bases: named corpora in the `knowledge:` section of `agent_actions.yml` that a
retrieve entry searches. A base reads files, records of JSON, JSONL or CSV files, and
rows of a database query; it cuts them into chunks and indexes them in content-addressed
SQLite files under `.agac/knowledge/<base>/`. Indexes are built only on the run path
(`ensure_indexes`) and by `agac knowledge build | search`, never by a load.

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `api.py` | Module | What the run path and the retrieve step call. `KNOWN_METHODS`, `INDEX_FOR_METHOD` (`keyword`, `all_words`, `phrase` → `keyword`; `fuzzy` → `fuzzy`; `key` → `key`), `KnowledgeConfigError` (a `ConfigurationError`), `load_knowledge_config` (reads the config only), `knowledge_hash` (the digest the current sources would build; None when it cannot be computed, such as a database source with no snapshot; never connects, never builds), `ensure_indexes` (builds what is stale and returns the digest; a sandbox run with no database snapshot is refused) and `retrieve` (one search of a built digest: `matches`, `count`, `query`, `index`; a `where` value of None matches nothing; read-only, safe from many threads). | `errors` |
| `config.py` | Module | `KnowledgeBase` (strict, `extra="forbid"`): `sources` (a file glob, `StructuredSource` with `path`, `text`, `title`, `id`, `metadata`, or `DatabaseSource` with `connection`, `sql`, `text`, `title`, `id` (required), `metadata`; the SQL is checked by `refuse_a_statement_that_writes`), `index` (`keyword`, `fuzzy`; default `[keyword]`; `vector` is refused as later), `chunk_config` (the existing `ChunkConfig`, not inherited; `field` refused; overlap at most half the size; defaults `markdown`, 200, 0). `name` is set from the key. `metadata_fields` (what a `where:` may name) and `has_key` (every source sets `id:`). `parse_knowledge`, `load_knowledge`, `unknown_base_message` (with a suggestion). | `pydantic`, `config.schema` |
| `chunks.py` | Module | `scan` reads each source's bytes once and hashes them (`Scan.content_digest`: the base's settings without `index` and `name`, `CHUNKER_VERSION`, each file's path and hash, each snapshot's hash); `chunk` cuts the chunks from those bytes: text files (md, markdown, txt, html, pdf, docx) by the base's split method, with the heading path as title; a record or a row is one chunk; a JSONL file is split at `\n` only, so a string may hold U+2028 or U+0085. `matched_files` refuses a glob that matches nothing or leaves the project; a file over `MAX_FILE_BYTES`, a record with no text or no id value, and an id that names two records are refused by name. A file two globs match is read once; a file two sources read differently is refused naming both. A CSV value past the last column is left out. `CHUNKER_VERSION` is 2. A database source reads its snapshot (`input/loaders/database_source.py`) under `.agac/knowledge/<base>/snapshots/source-<n>/`; with none, it reads the query when it may connect and refuses otherwise. Only `scan(..., refresh=True)` (`agac knowledge build --refresh`) reads the query of an existing snapshot again; a run's `--refresh-input` does not reach it. | `config`, `connections`, `input.loaders` |
| `methods.py` | Module | The method registry (`METHODS`, `Method`: `name`, `index`, `compile`, `search`, `build`). Each method compiles its own query from the raw text: `keyword` (quoted terms, English `STOPWORDS` dropped, OR, at most `MAX_TERMS`), `all_words` (AND), `phrase` (one quoted phrase, stopwords kept), `fuzzy` (trigrams of each term of 3 or more characters, OR, at most `MAX_TRIGRAMS`), `key` (exact chunk id). A term with no letter or digit (`___`) is dropped by every compiler. `where` is in each search's SQL (`json_extract` on the chunk metadata, both sides cast to text, so `2` matches a CSV `"2"`), before the `candidates` limit. FTS5 tokenizers: `porter unicode61 remove_diacritics 2` and `trigram remove_diacritics 1`; title weight 2. `trigram_supported()` (cached) tells whether this SQLite builds the trigram index; `config.py` refuses `index: [fuzzy]` without it. | `sqlite3` |
| `index.py` | Module | `<kind>-<digest>.db` files (`index_digest`: format, kind settings, content digest); `set-<digest>.json` maps the digest of several kinds (`combined_digest`) to their files. `build_indexes` writes a temporary file and `os.replace`s it under `project_lock` (portalocker on `.agac/knowledge/.lock`); `locate` finds the files of a digest (a set file not written yet is not cached); `connection` opens one read-only connection per thread and file (a relative path is resolved); `prune` removes unnamed files and partial builds under the lock. | `chunks`, `methods`, `portalocker` |
| `search.py` | Module | `search`: each method with `candidates` and `where`, merged by `fused` (weighted reciprocal rank fusion, k = 60; order: fused score, best single rank, chunk id; one method keeps its own scores), then `max_per_origin`, `max_context_tokens` (offline token count; a best chunk over the limit gives no match and one warning per process and step) and `top_k`. The output keeps the frozen match keys (`MATCH_KEYS`). | `index`, `methods`, `input.preprocessing.transformation` |

## Project Surface

| Symbol | File | Interaction | Config Key |
|--------|------|-------------|------------|
| `load_knowledge_config()` | `agent_actions.yml` | Validates | `knowledge` |
| `scan()` | `knowledge/**` (any project path a source names) | Reads | `knowledge.<base>.sources` |
| `scan()` | `agent_actions.yml` | Reads | `connections` |
| `build_indexes()` | `.agac/knowledge/<base>/` | Writes | — |
| `retrieve()` | `.agac/knowledge/<base>/` | Reads | — |

## Dependencies

| Package | Direction | Why |
|---------|-----------|-----|
| `config` | outbound | `ChunkConfig`, `load_project_config` |
| `connections` | outbound | A database source opens a named connection read-only |
| `input` | outbound | The snapshot code and the read-only SQL check; the shared splitter and the offline token count |
| `cli` | inbound | `agac knowledge list \| build \| search` |
| `llm` / `workflow` | inbound | The retrieve step and the run path call `api` |

## Notes

- A digest names exactly the bytes indexed: the build cuts its chunks from the bytes the
  scan hashed. Adding a kind to `index:` does not change another kind's digest.
- Token counts are offline (`markdown_splitter.count_tokens`): `tiktoken` downloads its
  encoding on first use, which a sandbox run or CI with no network cannot do.
