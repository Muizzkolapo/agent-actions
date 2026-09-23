---
title: Input Formats
sidebar_position: 2
---

# Input Formats

Agent Actions accepts multiple input formats. Place files in `agent_io/staging/` before running your workflow.

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
| PDF | `.pdf` | PDF documents |
| Word | `.docx` | Word documents |

## JSON Input

A JSON file holds a list of records — one array, one object per record. Each
element becomes one record.

```json
[
  {
    "page_content": "The text content to process...",
    "url": "https://source.example.com/doc",
    "metadata": {
      "author": "John Doe",
      "date": "2024-01-15"
    }
  }
]
```

A file holding one record is that same list with one element in it. A lone
object at the top level is refused at staging, and the fix is to wrap it: `{...}`
becomes `[{...}]`, which stages the record it always did.

A record is always an object, so a bare value is refused whether it is the whole
document or a row inside one — wrapping it changes nothing. The refusal names the
row it stopped on when there is one.

## CSV/Tabular Input

Each row becomes a separate record. Header row defines field names.

```csv
id,title,content,category
1,First Doc,Content here...,technical
2,Second Doc,More content...,general
```

## Excel Input

The same rule reaches `.xlsx` through the sheet rather than the file: a sheet is
a list of records, each row becomes one record, and the header row names the
fields. A one-row sheet is one record, not a record of its own shape.

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

1. **Use consistent structure**: All input files should have the same field structure
2. **Include metadata**: Add tracking fields like `id`, `source`, `timestamp`
3. **Analyze schemas**: Use `agac schema -a my_workflow` to check field dependencies before running

## See Also

- [Output Format](./output-format.md) — How outputs are structured
- [Field References](../context/field-references.md) — Reference syntax details
- [Chunking](./chunking.md) — Split large documents
