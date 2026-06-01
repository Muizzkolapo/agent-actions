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
    overlap: 500
    split_method: tiktoken
```

### Configuration Fields

| Field | Default | Description |
|-------|---------|-------------|
| `chunk_size` | 1000 | Maximum size per chunk (tokens or characters) |
| `overlap` | 200 | Overlap between consecutive chunks |
| `split_method` | `tiktoken` | Chunking strategy: `tiktoken`, `chars`, or `spacy` |

### Per-Action Override

Override chunking for specific actions:

```yaml
actions:
  - name: process_large_docs
    chunk_config:
      chunk_size: 8000
      overlap: 1000
      split_method: chars
```

## Split Methods

### tiktoken (Default)

Token-based chunking using OpenAI's tokenizer:

```yaml
chunk_config:
  chunk_size: 4000
  overlap: 500
  split_method: tiktoken
```

**When to use:** OpenAI models, precise token control, optimizing for context limits.

### chars

Character-based splitting:

```yaml
chunk_config:
  chunk_size: 8000
  overlap: 1000
  split_method: chars
```

**When to use:** Non-OpenAI models, simple text processing, predictable chunk sizes.

### spacy

Semantic chunking using spaCy NLP—splits at sentence boundaries:

```yaml
chunk_config:
  chunk_size: 4000
  overlap: 500
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
default_agent_config:
  chunk_config:
    chunk_size: 4000
    overlap: 500
    split_method: tiktoken

actions:
  - name: summarize_chapters
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
