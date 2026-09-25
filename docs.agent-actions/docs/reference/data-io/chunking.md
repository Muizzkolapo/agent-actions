---
title: Chunking
sidebar_position: 2
---

# Chunking

Chunking splits large documents into smaller pieces that fit within LLM context limits. Agent Actions supports multiple chunking strategies optimized for different use cases.

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
| `chunk_size` | 300 | Maximum size per chunk (tokens or characters) |
| `chunk_overlap` | 10 | Overlap between consecutive chunks |
| `split_method` | `tiktoken` | Chunking strategy: `tiktoken`, `chars`, or `spacy` |
| `tokenizer_model` | `cl100k_base` | Tokenizer used to measure chunk size |

These four are the only keys `chunk_config` takes; anything else is refused at load, naming the field it resembles. Each can also be written as a key of its own on an action, in `defaults:`, or in `default_agent_config:`.

Settings merge by name, not by block, so a block that omits a name keeps whatever a wider level set for it. Nearest wins, and within a level the block wins over a key beside it:

```
default_agent_config key  <  default_agent_config block  <  defaults: key
  <  defaults: block  <  action key  <  action block
```

An overlap at or above the chunk size it would be split with is refused at load rather than at the split, since merging by name can pair a nearer size with a wider overlap.

The defaults are tuned for the framework's own short-document benchmarks. The examples below show larger values (4000 / 8000) tuned for OpenAI-class context windows — start there for production workloads on long documents.

### Per-Action Override

Override chunking for specific actions:

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

Token-based chunking using OpenAI's tokenizer:

```yaml
chunk_config:
  chunk_size: 4000
  chunk_overlap: 500
  split_method: tiktoken
```

**When to use:** OpenAI models, precise token control, optimizing for context limits.

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

Semantic chunking using spaCy NLP—splits at sentence boundaries:

```yaml
chunk_config:
  chunk_size: 4000
  chunk_overlap: 500
  split_method: spacy
```

**When to use:** Preserving sentence integrity, natural language content, quality over speed.

## Overlap

Overlap ensures context is not lost at chunk boundaries. Overlapping sections appear in both adjacent chunks.

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
```

### Downstream Aggregation

When you need to combine results from all chunks:

```yaml
actions:
  - name: process_chunks
    granularity: record  # Process each chunk

  - name: aggregate_results
    granularity: file    # Combine all chunks
    dependencies: process_chunks
```

## Best Practices

1. **Match split method to model**: Use `tiktoken` for OpenAI models, `chars` for others
2. **Account for prompt size**: Leave room for your prompt template in the chunk size
3. **Test boundaries**: Use `agac run -a workflow --log-level DEBUG` to see how documents are split

## Disabling Chunking

To process documents whole, set a large `chunk_size` or omit `chunk_config` entirely.
