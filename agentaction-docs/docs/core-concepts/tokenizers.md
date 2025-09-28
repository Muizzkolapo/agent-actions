---
title: Custom Tokenizers
description: Bring Your Own Tokenizer (BYOT) for text chunking and processing
sidebar_position: 5
---

# Custom Tokenizers

Tokenizers in Agent Actions are responsible for **chunking large text** into smaller pieces that can be processed by LLMs. While the framework provides built-in tokenizers, the **Bring Your Own Tokenizer (BYOT)** feature allows you to implement custom text splitting logic tailored to your specific needs.

## Overview

When processing large documents, Agent Actions must split text into manageable chunks that fit within model context limits. Tokenizers handle this critical task by:

- **Breaking down text** into smaller, processable segments
- **Managing overlap** between chunks to maintain context
- **Respecting token limits** for specific LLM models
- **Preserving structure** and meaning when possible

## Built-in Tokenizers

Agent Actions includes three built-in tokenization methods:

### 1. TikToken (Default)
Uses OpenAI's tiktoken library for precise token counting:

```yaml
agents:
  - name: "text_processor"
    split_method: "tiktoken"
    tokenizer_model: "cl100k_base"  # GPT-4 tokenizer
    chunk_size: 1000
    overlap: 200
```

**Best for**: OpenAI models (GPT-3.5, GPT-4) where precise token counting matters.

### 2. Character-Based
Simple character counting for basic splitting:

```yaml
agents:
  - name: "text_processor"
    split_method: "chars"
    chunk_size: 4000  # Character count
    overlap: 400
```

**Best for**: Quick prototyping or when exact token counts aren't critical.

### 3. SpaCy NLP
Uses spaCy for sentence-aware splitting:

```yaml
agents:
  - name: "text_processor"
    split_method: "spacy"
    chunk_size: 1000
    overlap: 200
```

**Best for**: Maintaining sentence boundaries and linguistic structure.

## Understanding split_method vs tokenizer_model

When configuring text chunking, it's important to understand the distinction between these two parameters:

### `split_method` - How to Split Text

Determines the **strategy** for dividing text into chunks:

- **`"tiktoken"`** - Splits by token boundaries (may break mid-sentence)
- **`"chars"`** - Splits by character count
- **`"spacy"`** - Splits respecting sentence boundaries
- **`"your_custom_method"`** - Uses your custom splitting logic

### `tokenizer_model` - How to Measure Tokens

Determines the **measurement standard** for counting tokens:

- **`"cl100k_base"`** - GPT-4, GPT-3.5-turbo, text-embedding-3
- **`"p50k_base"`** - text-davinci-003, code-davinci-002
- **`"r50k_base"`** - GPT-3 (davinci, curie, etc.)

### How They Work Together

These parameters work in tandem during the chunking process:

**Example Configuration:**
```yaml
chunk_config:
  chunk_size: 100                    # Maximum 100 tokens per chunk
  overlap: 20                        # 20 tokens overlap
  split_method: "spacy"              # HOW: Split on sentence boundaries
  tokenizer_model: "cl100k_base"     # MEASURE: Count tokens using GPT-4 method
```

**Process:**
1. `split_method: "spacy"` breaks text into sentences
2. `tokenizer_model: "cl100k_base"` counts tokens in each sentence
3. When token count reaches `chunk_size` (100), a new chunk is created
4. `overlap` (20 tokens) is maintained between chunks

### Why Both Are Needed

Consider this example with spaCy:

```python
# spaCy splits into sentences
sentences = ["First sentence here.", "Second sentence here.", "Third sentence."]

# But uses tiktoken to measure them
encoding = tiktoken.get_encoding("cl100k_base")
tokens_sent1 = len(encoding.encode(sentences[0]))  # 4 tokens
tokens_sent2 = len(encoding.encode(sentences[1]))  # 4 tokens
tokens_sent3 = len(encoding.encode(sentences[2]))  # 3 tokens

# Decision based on TOKENS, not characters
if tokens_sent1 + tokens_sent2 > chunk_size:
    # Split into separate chunks
```

**Why this matters:**
- ✅ **Accurate**: Matches what the LLM actually counts
- ✅ **Prevents errors**: Won't exceed model context limits
- ✅ **Universal**: Works regardless of splitting method
- ✅ **Best practice**: Industry standard for chunking

### Common Combinations

#### Sentence-Aware with Accurate Counting (Recommended)
```yaml
split_method: "spacy"
tokenizer_model: "cl100k_base"
```
**Result**: Chunks respect sentence boundaries with accurate token counting

#### Pure Token-Based Splitting
```yaml
split_method: "tiktoken"
tokenizer_model: "cl100k_base"
```
**Result**: Splits purely by tokens (may break mid-sentence)

#### Character-Based (No Token Counting)
```yaml
split_method: "chars"
chunk_size: 4000  # Characters, not tokens
```
**Result**: Simple character-based splitting (no `tokenizer_model` needed)

#### Custom Logic with Accurate Counting
```yaml
split_method: "semantic_chunker"  # Your custom tokenizer
tokenizer_model: "cl100k_base"
```
**Result**: Your custom splitting logic with accurate token measurement

**Complete configuration example:**
```yaml
actions:
  - name: process_documents
    schema: extracted_facts
    chunk_config:
      chunk_size: 100
      overlap: 20
      tokenizer_model: "cl100k_base"
      split_method: "semantic_chunker"  # Must match filename in tools/
    prompt: "Analyze: {input}"
```

:::info Prerequisites
Place your custom tokenizer file in the `tools/` directory at your project root:
```
your-project/
├── tools/
│   └── semantic_chunker.py  # Your custom tokenizer
├── workflow.yaml
└── schemas/
```
:::

:::tip Key Takeaway
- **`split_method`** = Splitting strategy (HOW to divide text)
- **`tokenizer_model`** = Measurement standard (HOW to count tokens)
- You can mix and match any `split_method` with any `tokenizer_model`
- Exception: `"chars"` split method doesn't use `tokenizer_model`
:::

## Bring Your Own Tokenizer (BYOT)

### How BYOT Works

The BYOT system allows you to create custom tokenizers by:

1. **Creating a Python module** in your project's `tools/` directory
2. **Implementing the required function signature**
3. **Configuring your agent** to use the custom tokenizer

The system automatically loads your custom tokenizer using Python's `importlib` mechanism.

:::info Module Discovery
The module name must match the function name. For example, if you create `tools/semantic_chunker.py`, it must contain a function named `semantic_chunker`.
:::

### Required Function Signature

All custom tokenizers must implement this exact signature:

```python
def your_tokenizer_name(
    text: str,
    chunk_size: int,
    overlap: int,
    tokenizer_model: str
) -> List[str]:
    """
    Custom tokenizer function.

    Args:
        text: The input text to split
        chunk_size: Maximum tokens/characters per chunk
        overlap: Number of tokens/characters to overlap between chunks
        tokenizer_model: Model identifier for token counting (e.g., "cl100k_base")

    Returns:
        List of text chunks
    """
    pass
```

### Example Implementation

Here's a complete example of a semantic-aware chunker:

```python title="tools/semantic_chunker.py"
from typing import List
import tiktoken
import re

def semantic_chunker(
    text: str,
    chunk_size: int,
    overlap: int,
    tokenizer_model: str
) -> List[str]:
    """
    Split text using semantic similarity and sentence boundaries.

    This tokenizer:
    - Respects sentence boundaries
    - Maintains paragraph structure
    - Uses tiktoken for accurate token counting
    - Handles overlap intelligently
    """
    try:
        # Initialize the tokenizer
        encoding = tiktoken.get_encoding(tokenizer_model)
    except Exception:
        # Fallback to character counting if tiktoken fails
        return _fallback_character_split(text, chunk_size, overlap)

    # Split into sentences while preserving structure
    sentences = re.split(r'(?<=[.!?])\s+', text)

    chunks = []
    current_chunk = []
    current_tokens = 0

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue

        sentence_tokens = len(encoding.encode(sentence))

        # If adding this sentence exceeds chunk_size and we have content
        if current_tokens + sentence_tokens > chunk_size and current_chunk:
            # Finalize current chunk
            chunk_text = ' '.join(current_chunk)
            chunks.append(chunk_text)

            # Calculate overlap size (percentage of chunk_size)
            overlap_tokens = min(overlap, len(current_chunk))
            if overlap_tokens > 0:
                # Keep last few sentences for overlap
                overlap_sentences = current_chunk[-overlap_tokens:]
                current_chunk = overlap_sentences
                current_tokens = sum(len(encoding.encode(s)) for s in overlap_sentences)
            else:
                current_chunk = []
                current_tokens = 0

        # Add current sentence
        current_chunk.append(sentence)
        current_tokens += sentence_tokens

    # Add final chunk if it has content
    if current_chunk:
        chunks.append(' '.join(current_chunk))

    return chunks

def _fallback_character_split(text: str, chunk_size: int, overlap: int) -> List[str]:
    """Fallback to character-based splitting if tokenizer fails."""
    chunks = []
    start = 0

    while start < len(text):
        end = start + chunk_size
        if end >= len(text):
            chunks.append(text[start:])
            break

        # Try to break at word boundary
        while end > start and text[end] not in ' \n\t':
            end -= 1

        if end == start:  # No word boundary found
            end = start + chunk_size

        chunks.append(text[start:end])
        start = end - overlap

    return chunks
```

### Configuration

To use your custom tokenizer, specify it in your agent configuration:

```yaml title="workflow.yaml"
agents:
  - name: "document_processor"
    model_vendor: "openai"
    model_name: "gpt-4"
    prompt: "Analyze this text: {input}"
    output_schema: "analysis_schema"

    # Custom tokenizer configuration
    split_method: "semantic_chunker"  # Your module/function name
    chunk_size: 1000                 # Passed to your function
    overlap: 200                     # Passed to your function
    tokenizer_model: "cl100k_base"   # Passed to your function

    depends_on: []
```

:::tip File Organization
Place your tokenizer files in the `tools/` directory at your project root:
```
your-project/
├── tools/
│   ├── semantic_chunker.py
│   ├── legal_chunker.py
│   └── custom_tokenizer.py
├── workflow.yaml
└── schemas/
```
:::

## Use Cases for Custom Tokenizers

### 1. Domain-Specific Text
Create specialized tokenizers for specific content types:

```python title="tools/legal_chunker.py"
def legal_chunker(text: str, chunk_size: int, overlap: int, tokenizer_model: str) -> List[str]:
    """Chunk legal documents preserving section structure."""
    # Split on legal section markers
    sections = re.split(r'\n(?=\d+\.|\([a-z]\)|\(i+\))', text)
    # Implement legal-aware chunking logic
    pass
```

### 2. Code Documentation
Handle code blocks and documentation specially:

```python title="tools/code_chunker.py"
def code_chunker(text: str, chunk_size: int, overlap: int, tokenizer_model: str) -> List[str]:
    """Chunk code documentation preserving function boundaries."""
    # Detect code blocks and function definitions
    # Ensure code blocks aren't split mid-function
    pass
```

### 3. Multilingual Content
Custom handling for different languages:

```python title="tools/multilingual_chunker.py"
def multilingual_chunker(text: str, chunk_size: int, overlap: int, tokenizer_model: str) -> List[str]:
    """Chunk text with language-aware sentence detection."""
    import spacy
    # Use different spaCy models based on detected language
    pass
```

### 4. Structured Data
Handle JSON, XML, or other structured formats:

```python title="tools/structured_chunker.py"
def structured_chunker(text: str, chunk_size: int, overlap: int, tokenizer_model: str) -> List[str]:
    """Chunk structured data preserving object boundaries."""
    # Parse JSON/XML structure
    # Ensure objects aren't split across chunks
    pass
```

## Best Practices

### 1. Error Handling
Always include robust error handling:

```python
def robust_chunker(text: str, chunk_size: int, overlap: int, tokenizer_model: str) -> List[str]:
    try:
        # Your chunking logic
        return chunks
    except Exception as e:
        # Log the error
        print(f"Custom tokenizer error: {e}")
        # Return fallback simple split
        return [text[i:i+chunk_size] for i in range(0, len(text), chunk_size-overlap)]
```

### 2. Token Counting Accuracy
Use tiktoken for accurate token counting when possible:

```python
import tiktoken

def accurate_chunker(text: str, chunk_size: int, overlap: int, tokenizer_model: str) -> List[str]:
    try:
        encoding = tiktoken.get_encoding(tokenizer_model)
        # Use encoding.encode() for accurate token counts
    except:
        # Fallback to character estimation (rough: 4 chars ≈ 1 token)
        estimated_chars = chunk_size * 4
```

### 3. Preserve Context
Design overlap to maintain semantic continuity:

```python
def context_aware_chunker(text: str, chunk_size: int, overlap: int, tokenizer_model: str) -> List[str]:
    # Calculate overlap based on sentences or paragraphs, not just token count
    # Ensure each chunk has sufficient context to be meaningful
    pass
```

### 4. Performance Optimization
For large documents, optimize your chunking logic:

```python
def optimized_chunker(text: str, chunk_size: int, overlap: int, tokenizer_model: str) -> List[str]:
    # Pre-compile regex patterns
    # Cache tokenizer instances
    # Use efficient string operations
    pass
```

### 5. Testing Your Tokenizer
Create test cases for your custom tokenizer:

```python title="test_tokenizer.py"
def test_semantic_chunker():
    text = "First sentence. Second sentence. Third sentence."
    chunks = semantic_chunker(text, chunk_size=50, overlap=10, tokenizer_model="cl100k_base")

    assert len(chunks) > 0
    assert all(isinstance(chunk, str) for chunk in chunks)
    # Add more specific tests
```

## Troubleshooting

### Common Issues

**Import Error**: Module not found
```
ConfigurationError: Could not import custom split_method module 'my_tokenizer'
```
- Ensure the module file exists in `tools/` directory
- Check that the filename matches the function name
- Verify the `tools/` directory is in your project root

**Function Not Found**: Function doesn't exist in module
```
ConfigurationError: Could not find custom split_method function 'my_tokenizer' in its module
```
- Ensure the function name matches the module name
- Check that the function is defined at module level (not inside a class)

**Runtime Error**: Function execution failed
```
AgentActionsError: Error executing custom split_method 'my_tokenizer'
```
- Check your function for runtime errors
- Ensure all required dependencies are installed
- Add error handling and logging to debug

### Debugging Tips

1. **Add Logging**: Use print statements or logging to debug your tokenizer
2. **Test Independently**: Run your tokenizer function outside of Agent Actions
3. **Check Dependencies**: Ensure all required packages are installed
4. **Validate Inputs**: Handle edge cases like empty text or invalid parameters

## Field Chunking for Structured Data

When processing structured data (JSON, CSV, XML), you can chunk specific **fields within records** rather than entire files. This is useful when records contain large text fields that exceed token limits.

:::tip Field Names Are User-Specific
The examples below use field names like `page_content`, `description`, and `body`. **Replace these with your actual field names** from your JSON/CSV/XML data. The system works with any field names you specify.
:::

### Configuration Options

#### 1. Explicit Field List (Recommended)

Explicitly specify which fields to chunk. **Replace field names with your actual data fields.**

```yaml
actions:
  - name: extract_facts
    chunk_config:
      chunk_size: 100
      overlap: 20
      tokenizer_model: "cl100k_base"
      split_method: "spacy"
      field_chunking:
        enabled: true
        chunk_fields: ["page_content", "description"]  # Use YOUR field names here
        chunk_threshold: 50  # Only chunk if >50 tokens
```

**Example with different field names:**
```yaml
field_chunking:
  enabled: true
  chunk_fields: ["article_text", "summary", "full_content"]  # Your custom fields
```

#### 2. Auto-Detection (Size-Based)

Automatically detect and chunk any string field exceeding the token threshold:

```yaml
chunk_config:
  chunk_size: 100
  overlap: 20
  tokenizer_model: "cl100k_base"
  split_method: "spacy"
  field_chunking:
    enabled: true
    chunk_threshold: 50  # Chunk any string field with >50 tokens
    auto_detection:
      enabled: true
```

:::tip How Auto-Detection Works
Auto-detection finds **all string fields** in your data and chunks those exceeding `chunk_threshold`. No field name patterns needed - purely based on content size.
:::

**Example:** With `chunk_threshold: 50`, a record with:
- `title: "Short title"` (5 tokens) → Not chunked
- `page_content: "Long article..."` (500 tokens) → Chunked
- `description: "Medium length..."` (100 tokens) → Chunked

#### 3. Field-Specific Rules

Customize chunking per field:

```yaml
chunk_config:
  chunk_size: 100      # Global default
  overlap: 20
  split_method: "spacy"
  field_chunking:
    enabled: true
    chunk_fields: ["page_content", "description", "summary"]
    chunk_threshold: 50
    field_rules:
      page_content:
        chunk_size: 100
        overlap: 20
        split_method: "spacy"
        chunk_threshold: 100
      description:
        chunk_size: 200
        overlap: 50
        split_method: "tiktoken"
      summary:
        chunk_size: 50
        overlap: 10
        split_method: "chars"
```

#### 4. Preserve Fields

Exclude specific fields from chunking:

```yaml
chunk_config:
  chunk_size: 100
  overlap: 20
  split_method: "spacy"
  field_chunking:
    enabled: true
    chunk_fields: ["page_content", "title", "description"]
    preserve_fields: ["title"]  # Never chunk title
    chunk_threshold: 50
```

### Field Chunking Parameters

| Parameter | Purpose | Default |
|-----------|---------|---------|
| `enabled` | Enable field chunking | `false` |
| `chunk_fields` | Explicit list of fields to chunk | `[]` |
| `preserve_fields` | Fields to exclude from chunking | `[]` |
| `chunk_threshold` | Minimum tokens before chunking | `0` |
| `auto_detection.enabled` | Enable automatic detection of string fields | `false` |
| `field_rules` | Per-field custom settings | `{}` |

### Decision Logic

A field gets chunked if:
1. Field is a **string** AND
2. Field is in `chunk_fields` OR (`auto_detection.enabled` is true) AND
3. Field is NOT in `preserve_fields` AND
4. Field token count > `chunk_threshold`

:::info Size-Based Detection
Auto-detection is purely content-based. It considers all string fields and uses `chunk_threshold` to decide which need chunking. No field name patterns required.
:::

### Complete Example

```yaml
defaults:
  vendor: openai
  model: gpt-4o-mini
  json_mode: true

actions:
  - name: process_documents
    schema: extracted_facts
    reads: [id, url, page_content, metadata]
    writes: [facts]
    chunk_config:
      chunk_size: 100
      overlap: 20
      tokenizer_model: "cl100k_base"
      split_method: "spacy"
      field_chunking:
        enabled: true
        chunk_fields: ["page_content"]
        chunk_threshold: 50
        field_rules:
          page_content:
            chunk_size: 100
            overlap: 20
            split_method: "spacy"
    prompt: "Extract key facts from: {page_content}"
```

**Input Data Example:**
```json
{
  "id": 1,
  "url": "https://example.com",
  "page_content": "Very long text content that needs chunking...",
  "metadata": "Short metadata"
}
```

**Result:** The `page_content` field will be split using spaCy into multiple chunks, creating separate records for each chunk while preserving `id`, `url`, and `metadata` fields.

:::tip Finding Your Field Names
To see what fields are available in your data:
1. Check your JSON/CSV files directly
2. Look at the trace output when running your workflow
3. Use your data source documentation
:::

## Related Documentation

- **[Agents Guide](./agents.md)** - Learn about agent configuration and text processing
- **[Workflows](./workflows.md)** - Understand how tokenizers fit into DAG execution
- **[Schemas](./schemas.md)** - Design schemas for chunked text processing

## Examples Repository

For more examples and advanced tokenizer implementations, see the [Agent Actions Examples](https://github.com/agent-actions/examples) repository.