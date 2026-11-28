"""An action corpus: one chunk for each record the `from:` action processed, as stored."""

from __future__ import annotations

import pytest

from agent_actions.errors import ConfigurationError
from agent_actions.knowledge.action_corpus import (
    CorpusSettings,
    corpus_records,
    processed_outputs,
)

LABEL = "link: retrieve 'similar' (link__similar)"
SETTINGS = CorpusSettings("summarize", ("summary", "keywords"), title="product", id="ticket_id")


def _row(guid, output, state="processed", **extra):
    return {"source_guid": guid, "_state": state, "content": {"summarize": output}, **extra}


def _output(ticket, summary="a summary", **extra):
    return {"ticket_id": ticket, "summary": summary, "keywords": ["billing"], **extra}


class TestTheRowsKept:
    def test_only_rows_the_action_processed_are_kept(self):
        rows = [
            _row("g1", _output("T-1")),
            _row("g2", _output("T-2"), state="failed"),
            _row("g3", _output("T-3"), state="exhausted"),
            _row("g4", None, state="guard_skipped"),
            _row("g5", _output("T-5"), state="guard_skipped"),
            _row("g6", _output("T-6"), state="cascade_skipped"),
            _row("g7", _output("T-7"), _tombstone=True),
            _row("g8", _output("T-8"), state="active"),
            {"source_guid": "g9", "_state": "processed", "content": {"other": {}}},
            _row("", _output("T-10")),
        ]

        kept = processed_outputs(rows, "summarize")

        assert [guid for guid, _ in kept] == ["g1"]


class TestTheChunks:
    def test_the_text_fields_are_joined_with_spaces_and_a_list_of_strings_too(self):
        outputs = [("g1", _output("T-1", summary="Charged twice", keywords=["billing", "refund"]))]

        (record,) = corpus_records(outputs, SETTINGS, LABEL)

        assert record.chunk.text == "Charged twice billing refund"
        assert record.chunk.body == record.chunk.text
        assert record.chunk.id == "T-1"
        assert record.chunk.origin == "summarize"

    def test_the_metadata_holds_the_other_output_fields_and_always_the_source_guid(self):
        outputs = [("g1", _output("T-1", product="app", severity=2))]

        (record,) = corpus_records(outputs, SETTINGS, LABEL)

        assert record.chunk.metadata == {
            "ticket_id": "T-1",
            "product": "app",
            "severity": 2,
            "source_guid": "g1",
        }
        assert record.chunk.title == "app"

    def test_with_no_id_field_a_record_is_named_by_its_source_guid(self):
        settings = CorpusSettings("summarize", ("summary",))

        (record,) = corpus_records([("g1", _output("T-1"))], settings, LABEL)

        assert record.chunk.id == "g1"
        assert record.chunk.title == ""

    def test_a_null_text_field_adds_nothing(self):
        (record,) = corpus_records(
            [("g1", _output("T-1", summary=None, keywords=None))], SETTINGS, LABEL
        )

        assert record.chunk.text == ""

    @pytest.mark.parametrize("value", [{"a": 1}, [{"a": 1}]])
    def test_an_object_in_a_text_field_fails_the_step_naming_the_field(self, value):
        with pytest.raises(ConfigurationError) as caught:
            corpus_records([("g1", _output("T-1", summary=value))], SETTINGS, LABEL)

        assert "text field 'summary' holds an object" in str(caught.value)
        assert LABEL in str(caught.value)

    def test_a_repeated_source_guid_fails_the_step_naming_it(self):
        outputs = [("g1", _output("T-1")), ("g1", _output("T-2"))]

        with pytest.raises(ConfigurationError) as caught:
            corpus_records(outputs, SETTINGS, LABEL)

        assert "more than one record with source_guid 'g1'" in str(caught.value)

    def test_a_repeated_id_value_fails_the_step_naming_it(self):
        outputs = [("g1", _output("T-1")), ("g2", _output("T-1"))]

        with pytest.raises(ConfigurationError) as caught:
            corpus_records(outputs, SETTINGS, LABEL)

        assert "id 'T-1' (ticket_id) names the records with source_guid 'g1' and 'g2'" in str(
            caught.value
        )

    def test_a_record_with_no_id_value_fails_the_step_naming_it(self):
        with pytest.raises(ConfigurationError) as caught:
            corpus_records([("g1", _output(""))], SETTINGS, LABEL)

        assert "source_guid 'g1' has no value in its id field 'ticket_id'" in str(caught.value)

    def test_identical_records_are_both_kept(self):
        outputs = [("g1", _output("T-1", summary="same")), ("g2", _output("T-2", summary="same"))]

        records = corpus_records(outputs, SETTINGS, LABEL)

        assert [r.chunk.id for r in records] == ["T-1", "T-2"]
        assert records[0].chunk.hash == records[1].chunk.hash
