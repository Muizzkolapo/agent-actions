"""save_checkpoint_records refuses to persist a schema-echo namespace as output.

The checkpoint table is the resume / carry-forward source read back interchangeably
with target data (disposition_gate reads both). A namespace shaped like the compiled
JSON Schema (the Ollama ``format`` shape) must be replaced with the parse-error
sentinel and recorded FAILED/PARSE_ERROR before it is checkpointed — symmetric with
the ``write_target`` gate on the target-data seam.
"""

import pytest

from agent_actions.output.response.vendor_compilation import compile_unified_schema
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
from agent_actions.utils.schema_echo import is_schema_echo


def _compiled_schema():
    """The real title-present compiled shape, identical to the corrupt rows."""
    compiled = compile_unified_schema(
        {"name": "InlineSchema", "fields": [{"id": "distractor_explanation_1", "type": "string"}]},
        "ollama_cloud",
    )
    assert is_schema_echo(compiled), "fixture must be a real schema-echo shape"
    return compiled


def _record(source_guid, namespace_value, action="explain_distractor_1"):
    return {
        "_state": "processed",
        "source_guid": source_guid,
        "content": {action: namespace_value},
    }


class TestCheckpointSchemaEchoGate:
    @pytest.fixture
    def backend(self, tmp_path):
        db_path = tmp_path / "agent_io" / "test.db"
        b = SQLiteBackend(str(db_path), "test_workflow")
        b.initialize()
        yield b
        b.close()

    def test_schema_echo_replaced_with_parse_error_sentinel(self, backend):
        """A checkpointed namespace matching is_schema_echo is replaced before storage."""
        backend.save_checkpoint_records(
            "explain_distractor_1", "output.json", [_record("sg-echo", _compiled_schema())]
        )

        ns = backend.read_checkpoint_records("explain_distractor_1", "output.json")[0]["content"][
            "explain_distractor_1"
        ]
        assert "_parse_error" in ns  # converted to a typed failure
        assert "raw_response" in ns  # mirrors the write_target gate
        assert "title" not in ns and "properties" not in ns  # the schema dict is gone

    def test_schema_echo_writes_failed_parse_error_disposition(self, backend):
        """The gated checkpoint record gets DISPOSITION_FAILED with reason=PARSE_ERROR."""
        backend.save_checkpoint_records(
            "explain_distractor_1", "output.json", [_record("sg-echo", _compiled_schema())]
        )

        disps = backend.get_disposition("explain_distractor_1", record_id="sg-echo")
        assert any(d["disposition"] == "failed" and d["reason"] == "parse_error" for d in disps)

    def test_clean_record_passes_through_unchanged(self, backend):
        """A non-echo namespace is checkpointed verbatim — the gate is a no-op for it."""
        clean = {"distractor_explanation_1": "the real explanation"}
        backend.save_checkpoint_records(
            "explain_distractor_1", "output.json", [_record("sg-clean", clean)]
        )

        ns = backend.read_checkpoint_records("explain_distractor_1", "output.json")[0]["content"][
            "explain_distractor_1"
        ]
        assert ns == clean
        assert backend.get_disposition("explain_distractor_1", record_id="sg-clean") == []

    def test_record_without_action_namespace_is_ignored(self, backend):
        """A record whose content lacks the action namespace is checkpointed untouched."""
        rec = {
            "_state": "processed",
            "source_guid": "sg-other",
            "content": {"some_other_action": {"x": 1}},
        }
        backend.save_checkpoint_records("explain_distractor_1", "output.json", [rec])

        stored = backend.read_checkpoint_records("explain_distractor_1", "output.json")[0]
        assert stored["content"] == {"some_other_action": {"x": 1}}
        assert backend.get_disposition("explain_distractor_1", record_id="sg-other") == []

    def test_gate_fires_for_any_action_name(self, backend):
        """The gate keys off content shape, not a hardcoded action name."""
        backend.save_checkpoint_records(
            "some_other_action",
            "output.json",
            [_record("sg-other", _compiled_schema(), action="some_other_action")],
        )

        ns = backend.read_checkpoint_records("some_other_action", "output.json")[0]["content"][
            "some_other_action"
        ]
        assert "_parse_error" in ns
        disps = backend.get_disposition("some_other_action", record_id="sg-other")
        assert any(d["disposition"] == "failed" and d["reason"] == "parse_error" for d in disps)
