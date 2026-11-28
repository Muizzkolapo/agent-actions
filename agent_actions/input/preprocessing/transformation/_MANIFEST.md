# Transformation Manifest

## Sub-Modules

| Sub-Module | Description |
|------------|-------------|
| (none) | Transformation utilities live at this level. |

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `__init__.py` | Module | Module docstring for transformation helpers. | `preprocessing` |
| `transformer.py` | Module | `DataTransformer` utilities for normalizing lists, cloning schema fields, and flattening content lists. | `preprocessing`, `output` |
| `markdown_splitter.py` | Module | `split_method: markdown`: `split_markdown` splits at headings, then paragraphs, then sentences, packed to `chunk_size` with the heading path (`A > B`) prefixed and counted; plain text splits by paragraphs and sentences; a word over the size is cut by tokens (`_cut`), so a URL or a punctuation run stays under the size; a closing run of `#` ends a heading only after a space, so `## Using C#` keeps it. `count_tokens` counts offline (one token per six letters or digits of a word, one per other visible character), so no tokenizer download is needed. | `chunking` |
| `string_transformer.py` | Module | `StringProcessor` (UDF caller) and `Tokenizer` helpers for splitting text via Tiktoken/characters/markdown/spaCy/custom methods. | `chunking`, `processing`, `nlp` |
