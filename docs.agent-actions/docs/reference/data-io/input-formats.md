---
title: Input Formats
sidebar_position: 2
---

# Input Formats

Agent Actions accepts multiple input formats. Put the files in `agent_io/staging/` before you run your workflow.

## Supported Formats

| Format | Extension | Use Case |
|--------|-----------|----------|
| JSON | `.json` | Structured data, API responses |
| CSV | `.csv` | Tabular data, spreadsheets |
| TSV | `.tsv` | Tab-separated tabular data |
| Excel | `.xlsx` | Spreadsheet data |
| Text | `.txt` | Plain text documents |
| Markdown | `.md` | Documentation, formatted text |
| HTML | `.html` | Web content |
| PDF | `.pdf` | PDF documents |
| Word | `.docx` | Word documents |

An `.xml` file is refused as first-stage input with this error: `XML first-stage input is not supported; convert to CSV or JSON.`

## JSON Input

A JSON file holds a list of records: one array, with one object for each record.
Each element becomes one record.

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

Some editors and Windows tools save a file with a UTF-8 byte order mark. Such a file
is read without the mark. Its records stage as they would without the mark.

A file that holds one record is the same list, with one element in it. A lone
object at the top level is refused at staging. To correct the file, wrap the object:
`{...}` becomes `[{...}]`. The wrapped file stages the record that it always did.

A record is always an object. Thus a bare value is refused, whether it is the whole
document or a row in a document. If you wrap the bare value, nothing changes. The
refusal names the row that it stopped on, if there is one.

A record may nest to any depth. These parts all read and write a nested field
without a depth limit:

- staging
- the `source_guid` of the record
- the store
- retries
- a tool action that observes the field
- an LLM action that observes the field

This is also true past the approximately 1000 levels at which the JSON codec of
Python 3.11 stops. The request carries the field as JSON. A prompt can render the
field with `{{ source.field | tojson }}` at any depth.

A prompt that prints such a field with a bare `{{ source.field }}` cannot render it
at any depth. Jinja prints a list or an object with the Python `str()`. `str()` stops
at the recursion limit of the interpreter (1000 by default). That record fails, with a
reason that names the field, its depth and the limit. The other records continue. This
is true under `run_mode: batch` and under online mode. Use `| tojson`, or flatten the
field in a tool action first.

## CSV/Tabular Input

Each row becomes a separate record. The header row defines the field names.

```csv
id,title,content,category
1,First Doc,Content here...,technical
2,Second Doc,More content...,general
```

A quoted cell may hold line breaks. The record keeps them exactly as written.
A file saved with a UTF-8 byte order mark (as the Excel "CSV UTF-8" format does) is
read without the mark. Thus the name of the first column is only its header. A `.tsv`
file is read in the same way, split on tabs.

## Excel Input

The same rule applies to `.xlsx` through the sheet, not through the file. A sheet
is a list of records. Each row becomes one record, and the header row names the
fields. A sheet with one row is one record, not a record of its own shape.

## Text Documents

A `.txt`, `.md`, `.html`, `.pdf` or `.docx` file is read as text. The
[`chunk_config`](./chunking.md) of the action splits the text into chunks. Each chunk
becomes one record with a single field, `content`, that holds the text of the chunk:

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

The check that runs before any record is sent renders the first chunk. Thus a
reference to a field that a chunk does not have, for example `source.page_content`,
stops the run at that check. The error names `source.content`. An action downstream of
the first action that reads such a field is also stopped at that check (see
[Accessing Source Data](#accessing-source-data)).

## Staging Checks

Before the first action processes any file, these events occur for every staged file that the action will process:

1. The file is read.
2. The records of the file are prepared.
3. The checks of the first stage are applied to the file.

The checks of the first stage are:

- The document rule (a JSON file is an array of objects).
- Reserved field names (not checked for CSV and TSV columns).
- A value for every [seed chosen per record](../context/seed-data#choosing-a-seed-file-per-record) in every action.
- A render of the first record against the prompt.

A file that fails stops the run at that point. The error names the file and the record. Nothing of any file is stored or sent:

```
Seed 'syllabus' in action 'label_page': record value 'snowflak' for 'source.exam' is not in the file map. Known values: dbt, snowflake. (staging/b_pages.json, record 1)
```

The pass covers every file that the run would process. Thus a `file_limit` or `record_limit` does not hide a bad file beyond the limit. A file that cannot be read or parsed is not a refusal. The run reads the file again and reports it as a lost file. The check prepares records with no store. Thus a refused run leaves the store as it found it.

## Accessing Source Data

Refer to source fields in prompts with `{{ source.field }}`:

```yaml
prompt: |
  Analyze this content: {{ source.content }}
  From: {{ source.url }}
  Author: {{ source.metadata.author }}
```

### Checked Before Anything Runs

Every action reads the `source` namespace of the staged row that its record came from.
No action adds a field to that namespace. Thus, when the first action stages a file, two
groups of fields are checked against the rows of that file:

- The fields that an action downstream of the first action reads from `source`.
- The fields that the guard of the first action reads.

This check occurs before any record is stored or sent. The results are:

- An `observe` of a field that no row of the file holds stops the run. A prompt
  reference that every render reads has the same result. The error names the action,
  the field and the file. If the run did not stop, each of these reads would fail every
  record from that file. `{% if source.x %}` also reads `x`.
- A field that only some rows hold is not refused. Those rows run as usual.
- When the walk stages more than one file, another file may hold the field. Thus the
  read is logged as a warning, not refused. Files that are all text documents are the
  exception. All their records hold only `content`, so the read is still refused.
- These reads are logged as a warning, and the run continues:
  - A `passthrough` (it omits the field, as for the first action).
  - A guard on any action, the first action included. `source.x IS NULL` passes a
    record without `x`, and a comparison filters it.
  - A prompt reference under an `if` body or a loop.
  - A prompt reference on the right of `and`/`or`.
  - A prompt reference bound with `{% set %}` or `{% with %}` (read only where the name
    is used).
  - A prompt reference behind `| default(...)`, `is defined`, a conditional expression
    or `source.get('x', ...)`.
- An `observe` or a prompt read of a field that the guard of the same action reads is
  also a warning. The reason is that the guard first decides what occurs to a record
  without the field.

An API source is checked in the same way, against the rows that it fetched. An empty
staging folder stages nothing and checks nothing.

### Nested Fields

Use dot notation to get nested objects:

```yaml
prompt: |
  Author: {{ source.metadata.author }}
  Date: {{ source.metadata.date }}
```

### Iteration

Loop over the arrays in the source data:

```yaml
prompt: |
  Process these items:
  {% for item in source.items %}
  - {{ item.name }}: {{ item.value }}
  {% endfor %}
```

## Best Practices

1. **Use consistent structure**: All input files should have the same field structure.
2. **Include metadata**: Add tracking fields, for example `id`, `source` and `timestamp`.
3. **Analyze schemas**: Before you run the workflow, use `agac schema -a my_workflow` to check field dependencies.

## See Also

- [Output Format](./output-format.md) — How outputs are structured
- [Field References](../context/field-references.md) — Reference syntax details
- [Chunking](./chunking.md) — Split large documents
