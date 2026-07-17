"""write_target refuses to persist schema-echo dicts as record namespaces.

A resume / carry-forward record can reach the storage boundary with its action
namespace set to the compiled JSON Schema (the Ollama ``format`` shape) instead
of LLM output, bypassing the in-flight ``_reject_schema_echo_items`` guard. The
persistence gate replaces such a namespace with the parse-error sentinel and
records FAILED/PARSE_ERROR so the failure is queryable on the next read.
"""

import pytest

from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

SCHEMA_ECHO = {
    "title": "InlineSchema",
    "type": "object",
    "properties": {"distractor_explanation_1": {"type": "string"}},
    "required": [],
    "additionalProperties": False,
}


def _record(source_guid, namespace_value, action="explain_distractor_1"):
    return {
        "_state": "processed",
        "target_id": f"t-{source_guid}",
        "source_guid": source_guid,
        "content": {action: namespace_value},
    }


class TestSchemaEchoGate:
    @pytest.fixture
    def backend(self, tmp_path):
        db_path = tmp_path / "agent_io" / "test.db"
        b = SQLiteBackend(str(db_path), "test_workflow")
        b.initialize()
        yield b
        b.close()

    def test_clean_record_passes_through_unchanged(self, backend):
        """Non-echo namespace is written verbatim — the gate is a no-op for it."""
        clean = {"distractor_explanation_1": "the real explanation"}
        backend.write_target("explain_distractor_1", "f.json", [_record("sg-clean", clean)])

        rows = backend._read_target_raw("explain_distractor_1", "f.json")
        assert rows[0]["content"]["explain_distractor_1"] == clean
        assert backend.get_disposition("explain_distractor_1", record_id="sg-clean") == []

    def test_schema_echo_replaced_with_parse_error_sentinel(self, backend):
        """A namespace matching is_schema_echo is replaced before it reaches storage."""
        backend.write_target("explain_distractor_1", "f.json", [_record("sg-echo", SCHEMA_ECHO)])

        ns = backend._read_target_raw("explain_distractor_1", "f.json")[0]["content"][
            "explain_distractor_1"
        ]
        assert "_parse_error" in ns  # converted to a typed failure
        assert "raw_response" in ns  # mirrors helpers._reject_schema_echo_items
        assert "title" not in ns and "properties" not in ns  # the schema dict is gone

    def test_schema_echo_writes_failed_parse_error_disposition(self, backend):
        """The gated record gets DISPOSITION_FAILED with reason=PARSE_ERROR."""
        backend.write_target("explain_distractor_1", "f.json", [_record("sg-echo", SCHEMA_ECHO)])

        disps = backend.get_disposition("explain_distractor_1", record_id="sg-echo")
        assert any(d["disposition"] == "failed" and d["reason"] == "parse_error" for d in disps)

    def test_schema_echo_without_source_guid_is_still_gated(self, backend):
        """Echo namespace is replaced even with no source_guid; disposition write is skipped."""
        rec = {"_state": "processed", "content": {"explain_distractor_1": SCHEMA_ECHO}}
        backend.write_target("explain_distractor_1", "f.json", [rec])

        ns = backend._read_target_raw("explain_distractor_1", "f.json")[0]["content"][
            "explain_distractor_1"
        ]
        assert "_parse_error" in ns
        assert backend.get_disposition("explain_distractor_1") == []  # nothing to key it on

    def test_full_mode_record_without_action_namespace_is_ignored(self, backend):
        """A record whose content lacks the action namespace passes through untouched."""
        rec = {
            "_state": "processed",
            "source_guid": "sg-other",
            "content": {"some_other_action": {"x": 1}},
        }
        backend.write_target("explain_distractor_1", "f.json", [rec])

        rows = backend._read_target_raw("explain_distractor_1", "f.json")
        assert rows[0]["content"] == {"some_other_action": {"x": 1}}
        assert backend.get_disposition("explain_distractor_1", record_id="sg-other") == []

    def test_echo_after_prior_success_ends_failed_parse_error(self, backend):
        """A stale prior SUCCESS is cleared when the gate writes FAILED/PARSE_ERROR.

        set_disposition deletes any prior disposition for (action, record), so the
        record ends unambiguously failed — a downstream reader never sees the stale
        success alongside the new failure.
        """
        backend.set_disposition("explain_distractor_1", "sg-echo", "success")
        backend.write_target("explain_distractor_1", "f.json", [_record("sg-echo", SCHEMA_ECHO)])

        disps = backend.get_disposition("explain_distractor_1", record_id="sg-echo")
        kinds = {(d["disposition"], d["reason"]) for d in disps}
        assert ("failed", "parse_error") in kinds  # the gate's disposition
        assert ("success", None) not in kinds  # the stale success was cleared

    def test_gate_fires_for_any_action_name(self, backend):
        """The gate keys off content shape, not a hardcoded action name — a schema-echo
        under a different action is gated identically (kills a hardcoded-name cheat)."""
        backend.write_target(
            "some_other_action",
            "f.json",
            [_record("sg-other", SCHEMA_ECHO, action="some_other_action")],
        )

        ns = backend._read_target_raw("some_other_action", "f.json")[0]["content"][
            "some_other_action"
        ]
        assert "_parse_error" in ns
        disps = backend.get_disposition("some_other_action", record_id="sg-other")
        assert any(d["disposition"] == "failed" and d["reason"] == "parse_error" for d in disps)
