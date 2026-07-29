"""FILE tool output is schema-validated per record, not as the result envelope.

A FILE tool returns a FileUDFResult envelope (outputs=[{source_index, data}]).
Schema validation must inspect each record's ``data``, not the envelope keys —
otherwise every FILE tool with a schema is reported as an empty object.
"""

import logging

import pytest

from agent_actions.errors import SchemaValidationError
from agent_actions.processing.helpers import _validate_llm_output_schema
from agent_actions.utils.udf_management.registry import FileUDFResult

_SCHEMA = {
    "name": "dedup_by_concept",
    "properties": {"concept_label": {"type": "string"}, "key": {"type": "string"}},
}


def _tool_config(mode: str) -> dict:
    return {
        "agent_type": "dedup_by_concept",
        "kind": "tool",
        "schema": _SCHEMA,
        "reprompt": {"on_schema_mismatch": mode},
    }


def test_conforming_records_do_not_raise_in_reject_mode():
    result = FileUDFResult(
        outputs=[
            {"source_index": 0, "data": {"concept_label": "geometry", "key": "g1"}},
            {"source_index": 1, "data": {"concept_label": "algebra", "key": "a1"}},
        ]
    )
    # Envelope must be unwrapped: the records conform, so no mismatch is raised.
    out = _validate_llm_output_schema(result, _tool_config("reject"), "dedup_by_concept")
    assert out is result


def test_conforming_records_emit_no_schema_warning(caplog):
    result = FileUDFResult(
        outputs=[{"source_index": 0, "data": {"concept_label": "geometry", "key": "g1"}}]
    )
    with caplog.at_level(logging.WARNING, logger="agent_actions.processing.helpers"):
        _validate_llm_output_schema(result, _tool_config("warn"), "dedup_by_concept")
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "Empty object" not in joined
    assert "declared fields" not in joined


def test_records_missing_required_field_still_flagged():
    # The guard must still catch genuinely non-conforming records after unwrapping.
    schema = {**_SCHEMA, "required": ["concept_label", "key"]}
    config = {
        "agent_type": "dedup_by_concept",
        "kind": "tool",
        "schema": schema,
        "reprompt": {"on_schema_mismatch": "reject"},
    }
    result = FileUDFResult(outputs=[{"source_index": 0, "data": {"concept_label": "geometry"}}])
    with pytest.raises(SchemaValidationError):
        _validate_llm_output_schema(result, config, "dedup_by_concept")
