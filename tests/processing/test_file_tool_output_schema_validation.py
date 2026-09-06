"""FILE tool output is schema-validated per record, not as the result envelope.

A FILE tool returns a FileUDFResult envelope (outputs=[{source_index, data}]).
Schema validation must inspect each record's ``data``, not the envelope keys —
otherwise every FILE tool with a schema is reported as an empty object.
"""

_SCHEMA = {
    "name": "dedup_by_concept",
    "properties": {"concept_label": {"type": "string"}, "key": {"type": "string"}},
}
