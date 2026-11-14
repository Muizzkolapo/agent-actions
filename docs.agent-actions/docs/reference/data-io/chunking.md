---
title: Chunking
sidebar_position: 2
---

# Chunking

Chunking splits large text documents (`.txt`, `.md`, `.html`, `.pdf`, `.docx`) into smaller pieces that fit in the context limits of the LLM. The records of JSON, CSV, TSV and Excel files are not chunked. Agent Actions supports multiple chunking strategies. Each strategy is optimized for different use cases.

## Configuration

Configure chunking at the project level in `agent_actions.yml`:

```yaml
default_agent_config:
  chunk_config:
    chunk_size: 4000
    chunk_overlap: 500
    split_method: tiktoken
```

### Configuration Fields

| Field | Default | Description |
|-------|---------|-------------|
| `chunk_size` | 300 | The maximum size of each chunk (tokens or characters) |
| `chunk_overlap` | 10 | The overlap between consecutive chunks |
| `split_method` | `tiktoken` | The chunking strategy: `tiktoken`, `chars`, `spacy` or the name of a custom split function (see below) |
| `tokenizer_model` | `cl100k_base` | The tokenizer that measures the chunk size |

`chunk_config` takes only these four keys. Any other key is refused at load, and the error names the field that it resembles. You can also write each of these keys as a separate key on an action, in `defaults:` or in `default_agent_config:`.

Settings merge by name, not by block. Thus a block that omits a name keeps the value that a wider level set for that name. The nearest level has priority. In one level, the block has priority over a key beside it:

```
default_agent_config key  <  default_agent_config block  <  defaults: key
  <  defaults: block  <  action key  <  action block
```

For `tiktoken` and `chars` splits, an overlap at or above the chunk size is refused at load, not at the split. The reason is that merging by name can pair a nearer size with a wider overlap.

The defaults are tuned for the short-document benchmarks of the framework. The examples below show larger values (4000 / 8000), tuned for OpenAI-class context windows. For production workloads on long documents, start with these larger values.

### Per-Action Override

Override the chunking for specific actions:

```yaml
actions:
  - name: process_large_docs
    chunk_config:
      chunk_size: 8000
      chunk_overlap: 1000
      split_method: chars
```

## Split Methods

### tiktoken (Default)

Token-based chunking with the tokenizer of OpenAI:

```yaml
chunk_config:
  chunk_size: 4000
  chunk_overlap: 500
  split_method: tiktoken
```

**When to use:** OpenAI models, precise token control, optimization for context limits.

### chars

Character-based splitting:

```yaml
chunk_config:
  chunk_size: 8000
  chunk_overlap: 1000
  split_method: chars
```

**When to use:** Non-OpenAI models, simple text processing, predictable chunk sizes.

### spacy

Semantic chunking with spaCy NLP. It splits at sentence boundaries:

```yaml
chunk_config:
  chunk_size: 4000
  chunk_overlap: 500
  split_method: spacy
```

**When to use:** Sentences that must stay complete, natural language content, quality that is more important than speed.

### Custom split function

Any other `split_method` value names a Python module and a function of that name in the `tools/` folder (or in the folder that `TOOLS_PATH` names). The function takes `(text, chunk_size, overlap, tokenizer_model)` and returns a list of strings.

## Overlap

Overlap makes sure that context is not lost at chunk boundaries. Overlapping sections occur in both adjacent chunks.

### Recommended Overlap

| Content Type | Recommended Overlap |
|--------------|---------------------|
| Technical docs | 10-20% of chunk size |
| Narrative text | 15-25% of chunk size |
| Code | 5-10% of chunk size |
| Structured data | Minimal or none |

## Examples

### Large Document Processing

```yaml
# agent_config/{workflow}.yml — chunking belongs in the workflow's defaults block.
# `default_agent_config:` is a key of agent_actions.yml, and a workflow file that
# carries it is refused.
name: chapter_summaries
description: "Summarise a long document in chunks"

defaults:
  chunk_config:
    chunk_size: 4000
    chunk_overlap: 500
    split_method: tiktoken

actions:
  - name: summarize_chapters
    intent: "Summarise each chunk of a long document"
    prompt: |
      Summarize this section:
      {{ source.content }}
    schema: chapter_summary
    context_scope:
      observe: [source.content]
```

### Downstream Aggregation

When you need to combine the results from all chunks:

```yaml
actions:
  - name: process_chunks
    granularity: record  # Process each chunk

  - name: aggregate_results
    kind: tool
    impl: aggregate_results
    granularity: file    # Combine all chunks (tool actions only)
    dependencies: [process_chunks]
```

## Best Practices

1. **Match split method to model**: Use `tiktoken` for OpenAI models. Use `chars` for other models.
2. **Account for prompt size**: Leave space in the chunk size for your prompt template.
3. **Test boundaries**: Run `agac run -a <workflow> --file-limit 1`. Then read the records of the first action with `agac records -w <workflow> -a <action>` to see each chunk.

## Disabling Chunking

To process a document as one piece, set a `chunk_size` larger than the document. If you omit `chunk_config`, chunking is not disabled. The defaults above apply.
