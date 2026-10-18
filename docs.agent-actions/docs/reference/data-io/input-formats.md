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
    "content": "The text content to process...",
    "url": "https://source.example.com/doc",
    "metadata": {
      "author": "John Doe",
      "date": "2024-01-15"
    }
  }
]
```

A file saved with a UTF-8 byte order mark (as some editors and Windows tools write
it) is read without it, and its records stage as they would without the mark.

A file holding one record is that same list with one element in it. A lone
object at the top level is refused at staging, and the fix is to wrap it: `{...}`
becomes `[{...}]`, which stages the record it always did.

A record is always an object, so a bare value is refused whether it is the whole
document or a row inside one — wrapping it changes nothing. The refusal names the
row it stopped on when there is one.

A record may nest to any depth. Staging, the record's `source_guid`, the store,
retries, a tool action that observes the field and an LLM action that observes it
all read and write it without a depth limit, including past the roughly 1000 levels
at which Python 3.11's JSON codec stops. The request carries the field as JSON, and
a prompt can render it with `{{ source.field | tojson }}` at any depth.

A prompt that prints such a field with a bare `{{ source.field }}` cannot: Jinja
prints a list or object with Python's `str()`, which stops at the interpreter's
recursion limit (1000 by default). That record fails, with a reason naming the field,
how deep it is and the limit, and other records go on, under `run_mode: batch` as
under online. Use `| tojson`, or flatten the field in a tool action first.

## CSV/Tabular Input

Each row becomes a separate record. Header row defines field names.

```csv
id,title,content,category
1,First Doc,Content here...,technical
2,Second Doc,More content...,general
```

A quoted cell may hold line breaks, and the record keeps them exactly as written.
A file saved with a UTF-8 byte order mark (as Excel's "CSV UTF-8" does) is read
without it, so the first column is named by its header alone. A `.tsv` file is
read the same way, split on tabs.

## Excel Input

The same rule reaches `.xlsx` through the sheet rather than the file: a sheet is
a list of records, each row becomes one record, and the header row names the
fields. A one-row sheet is one record, not a record of its own shape.

## Text Documents

A `.txt`, `.md`, `.html`, `.pdf` or `.docx` file is read as text and split into
chunks by the action's [`chunk_config`](./chunking.md). Each chunk becomes one
record with a single field, `content`, holding the chunk's text:

```yaml
actions:
  - name: summarize
    intent: "Summarise each chunk"
    prompt: |
      Summarize this section:
      {{ source.content }}
    schema: { summary: string }
    context_scope:
      observe: [source.content]
```

The check that runs before any record is sent renders the first chunk, so a
reference to a field a chunk does not have, such as `source.page_content`, stops
the run there and names `source.content`. An action below the first that reads
such a field is stopped there too (see [Accessing Source Data](#accessing-source-data)).

## Accessing Source Data

Reference source fields in prompts using `{{ source.field }}`:

```yaml
prompt: |
  Analyze this content: {{ source.content }}
  From: {{ source.url }}
  Author: {{ source.metadata.author }}
```

### Checked Before Anything Runs

Every action reads the `source` namespace of the staged row its record came from;
no action adds a field to it. So when the first action stages a file, the fields an
action below it reads from `source` are checked against that file's rows, before any
record is stored or sent:

- An `observe`, or a prompt reference every render reads, of a field that no row
  of the file holds stops the run, naming the action, the field and the file. Each
  would otherwise fail every record from that file. `{% if source.x %}` reads `x` too.
- A field only some rows hold is not refused: those rows run as usual.
- When the walk stages more than one file, another file may hold the field, so the
  read is logged as a warning instead. Files that are all text documents are the
  exception: their records all hold only `content`, so the read is still refused.
- These are logged as a warning, and the run goes on: a `passthrough` (it leaves the
  field out, as for the first action), a guard (`source.x IS NULL` passes a record
  without `x`; a comparison filters it), and a prompt reference under an `if` body or
  a loop, on the right of `and`/`or`, bound with `{% set %}` or `{% with %}` (read only
  where the name is used), behind `| default(...)`, `is defined`, a conditional
  expression or `source.get('x', ...)`.
- An `observe` or prompt read of a field the action's own guard reads is a warning
  too: the guard decides first what a record without the field does.

An API source is checked against the rows it fetched, the same way. An empty
staging folder stages nothing and checks nothing.

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
