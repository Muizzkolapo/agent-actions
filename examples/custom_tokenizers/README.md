# Custom Tokenizer Examples

This directory contains example implementations of custom tokenizers for Agent Actions using the **Bring Your Own Tokenizer (BYOT)** feature.

## 📁 Files

### `semantic_chunker.py`
A production-ready custom tokenizer that:
- Respects sentence boundaries
- Uses tiktoken for accurate token counting
- Handles overlap intelligently
- Includes fallback for when tiktoken isn't available

### `test_semantic_chunker.py`
Test script to verify the tokenizer works correctly before deploying it.

## 🚀 Quick Start

### 1. Test the Tokenizer

```bash
cd examples/custom_tokenizers
python test_semantic_chunker.py
```

You should see output like:
```
🧪 Testing Semantic Chunker

============================================================
TEST 1: Basic Chunking
============================================================
Original text length: 234 characters
Number of chunks: 3
...
✅ All tests passed!
```

### 2. Use in Your Project

Copy `semantic_chunker.py` to your project's `tools/` directory:

```bash
# From your project root
mkdir -p tools
cp examples/custom_tokenizers/semantic_chunker.py tools/
```

### 3. Configure Your Workflow

Update your workflow YAML:

```yaml
# workflow.yaml
actions:
  - name: process_documents
    chunk_config:
      chunk_size: 100
      overlap: 20
      tokenizer_model: "cl100k_base"
      split_method: "semantic_chunker"  # Must match filename
    prompt: "Analyze: {input}"
```

### 4. Run Your Workflow

```bash
agent-actions run your-agent
```

## 📝 Creating Your Own Tokenizer

### Required Function Signature

```python
def your_tokenizer_name(
    text: str,
    chunk_size: int,
    overlap: int,
    tokenizer_model: str
) -> List[str]:
    """Your custom chunking logic."""
    # Implementation here
    return chunks
```

### Key Requirements

1. **Module name = Function name**: If your file is `custom_splitter.py`, the function must be `custom_splitter()`
2. **Location**: Place in `tools/` directory of your project
3. **Return type**: Must return `List[str]` (list of text chunks)
4. **Parameters**: Must accept exactly 4 parameters as shown above

### Example Structure

```
your-project/
├── tools/
│   ├── semantic_chunker.py       # Your custom tokenizer
│   ├── legal_chunker.py           # Another custom tokenizer
│   └── code_aware_chunker.py      # Yet another one
├── workflow.yaml
└── schemas/
```

## 🎯 Use Cases

### When to Use Custom Tokenizers

1. **Domain-Specific Content**: Legal documents, medical records, code
2. **Special Structure**: Markdown, XML, JSON with nested content
3. **Language Requirements**: Non-English text with different sentence rules
4. **Quality Requirements**: Need semantic coherence or topic boundaries

### When to Use Built-in Tokenizers

1. **General text**: Use `spacy` for sentence boundaries
2. **OpenAI models**: Use `tiktoken` for precise token counting
3. **Quick prototyping**: Use `chars` for character-based splitting

## 📚 More Examples

### Legal Document Chunker

```python
def legal_chunker(text: str, chunk_size: int, overlap: int, tokenizer_model: str) -> List[str]:
    """Chunk legal documents preserving section structure."""
    import re
    # Split on legal section markers
    sections = re.split(r'\n(?=\d+\.|Article|Section|\([a-z]\))', text)
    # Implement chunking logic that respects legal structure
    pass
```

### Code-Aware Chunker

```python
def code_chunker(text: str, chunk_size: int, overlap: int, tokenizer_model: str) -> List[str]:
    """Chunk code preserving function boundaries."""
    # Detect code blocks
    # Ensure functions aren't split mid-definition
    # Handle different programming languages
    pass
```

## 🐛 Troubleshooting

### Error: "Could not import custom split_method module"
- Check that filename matches function name
- Ensure file is in `tools/` directory at project root
- Verify no syntax errors in your Python file

### Error: "Could not find custom split_method function"
- Function name must match module name exactly
- Function must be defined at module level (not in a class)
- Check function signature matches required format

### Runtime Errors
- Add error handling and logging to your tokenizer
- Test independently with `test_semantic_chunker.py` pattern
- Use fallback logic for when dependencies fail

## 📖 Documentation

See [Custom Tokenizers Documentation](../../agentaction-docs/docs/core-concepts/tokenizers.md) for complete details on:
- Built-in tokenizers
- BYOT feature
- Best practices
- Field chunking for structured data

## 💡 Tips

1. **Always test independently** before using in production
2. **Handle errors gracefully** with fallback logic
3. **Use tiktoken** when possible for accurate token counting
4. **Document your chunking logic** for team members
5. **Consider edge cases**: empty text, very short/long text, special characters