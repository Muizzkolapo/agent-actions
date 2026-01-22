---
title: Input Formats
sidebar_position: 2
---

# Input Formats

What format should your data be in? Agent Actions accepts multiple input formats, so you can work with data in its native form rather than converting everything upfront. Place files in the `agent_io/staging/` directory before running your agentic workflow—this is your starting point for all input data.

## Supported Formats

| Format | Extension | Use Case |
|--------|-----------|----------|
| JSON | `.json` | Structured data, API responses |
| CSV | `.csv` | Tabular data, spreadsheets |
| TSV | `.tsv` | Tab-separated tabular data |
| Excel | `.xlsx` | Spreadsheet data |
| XML | `.xml` | Structured markup data |
| Text | `.txt` | Plain text documents |
| Markdown | `.md` | Documentation, formatted text |
| HTML | `.html` | Web content |

## JSON Input

JSON is the most common format for structured data. Each file becomes one record in your agentic workflow:

```json
{
  "page_content": "The text content to process...",
  "url": "https://source.example.com/doc",
  "metadata": {
    "author": "John Doe",
    "date": "2024-01-15"
  }
}
```

### JSON Arrays

You might wonder: what if you have multiple records in a single file? A file containing an array creates multiple records:

```json
[
  {"id": 1, "content": "First document..."},
  {"id": 2, "content": "Second document..."},
  {"id": 3, "content": "Third document..."}
]
```

Each array element becomes a separate record in the agentic workflow.

## CSV/Tabular Input

Tabular data works naturally with Agent Actions. Think of each row as a record flowing through your agentic workflow:

```csv
id,title,content,category
1,First Doc,Content here...,technical
2,Second Doc,More content...,general
```

- Each row becomes a separate record
- Header row defines field names
- Fields are accessible by column name

## Accessing Source Data

Reference source fields in prompts using `{{ source.field }}`:

```yaml
prompt: |
  Analyze this content: {{ source.page_content }}
  From: {{ source.url }}
  Author: {{ source.metadata.author }}
```

### Nested Fields

Access nested objects with dot notation:

```yaml
prompt: |
  Author: {{ source.metadata.author }}
  Date: {{ source.metadata.date }}
```

### Iteration

Loop over arrays in source data:

```yaml
prompt: |
  Process these items:
  {% for item in source.items %}
  - {{ item.name }}: {{ item.value }}
  {% endfor %}
```

## Best Practices

### 1. Use Consistent Structure

Here is an important limitation to keep in mind: all input files should have the same field structure. If fields are inconsistent, your prompts may fail when referencing missing fields:

```json
// Good: Consistent structure
{"id": "doc1", "content": "...", "category": "tech"}
{"id": "doc2", "content": "...", "category": "general"}

// Avoid: Inconsistent fields
{"id": "doc1", "text": "..."}
{"id": "doc2", "content": "...", "type": "..."}
```

### 2. Include Metadata

Add metadata fields for tracking:

```json
{
  "id": "unique_identifier",
  "content": "main content",
  "metadata": {
    "source": "origin_system",
    "timestamp": "2024-01-15T10:30:00Z",
    "version": "1.0"
  }
}
```

### 3. Validate Before Running

Consider what happens when your input data has issues: the agentic workflow might fail partway through, wasting API calls. Catch problems early by validating before execution:

```bash
agac run -a my_workflow --validate-only
```

## See Also

- [Output Format](./output-format.md) — How outputs are structured
- [Field References](../context/field-references.md) — Reference syntax details
- [Chunking](./chunking.md) — Split large documents
