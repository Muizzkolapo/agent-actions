"""A record missing several observed fields is refused once, with every field named.

The scope pass used to raise at the first missing explicit observe ref, so a record
lacking two fields was fixed one field at a time. Both granularities now name all of
them: the RECORD-mode error and the FILE-mode refusal detail carry the same list, in
observe order, and the error's context holds it as ``field_refs``.
"""

from __future__ import annotations

import pytest

from agent_actions.errors import RecordContextError
from agent_actions.prompt.context.scope_application import (
    apply_context_scope,
    apply_context_scope_for_records,
)

CONTENT = {"source": {"title": "t"}}
SCOPE = {"observe": ["source.title", "source.region", "source.currency"]}
BOTH = "context_scope.observe fields 'source.region', 'source.currency' not found in this record"


class TestRecordMode:
    def test_two_missing_fields_are_named_together_in_observe_order(self):
        with pytest.raises(RecordContextError) as raised:
            apply_context_scope(dict(CONTENT), SCOPE, action_name="rec_probe")

        assert str(raised.value) == BOTH
        assert raised.value.context["field_refs"] == ["source.region", "source.currency"]
        assert raised.value.context["field_ref"] == "source.region"
        assert raised.value.context["directive"] == "observe"

    def test_one_missing_field_keeps_the_message_it_had(self):
        """Control: a single missing field is unchanged, so nothing reading it moves."""
        with pytest.raises(RecordContextError) as raised:
            apply_context_scope(
                dict(CONTENT), {"observe": ["source.title", "source.region"]}, action_name="rec"
            )

        assert (
            str(raised.value)
            == "context_scope.observe field 'source.region' not found in namespace 'source'"
        )
        assert raised.value.context["field_ref"] == "source.region"
        assert "field_refs" not in raised.value.context

    def test_a_missing_namespace_and_a_missing_field_are_both_named(self):
        with pytest.raises(RecordContextError) as raised:
            apply_context_scope(
                dict(CONTENT),
                {"observe": ["source.region", "prep.code"]},
                action_name="rec",
            )

        assert raised.value.context["field_refs"] == ["source.region", "prep.code"]

    def test_a_wildcard_on_a_missing_namespace_is_not_a_missing_field(self):
        """Wildcards stay best-effort: only explicit refs are gathered."""
        with pytest.raises(RecordContextError) as raised:
            apply_context_scope(
                dict(CONTENT),
                {"observe": ["prep.*", "source.region"]},
                action_name="rec",
            )

        assert "field_refs" not in raised.value.context
        assert raised.value.context["field_ref"] == "source.region"

    def test_a_record_with_every_field_present_is_not_refused(self):
        prompt_context, llm_context, _ = apply_context_scope(
            {"source": {"title": "t", "region": "r", "currency": "c"}}, SCOPE, action_name="rec"
        )

        assert llm_context["source"] == {"title": "t", "region": "r", "currency": "c"}
        assert prompt_context["source"]["title"] == "t"


class TestFileMode:
    def test_the_refusal_detail_names_both_fields(self):
        records = [{"source_guid": "g1", "content": {"prep": {"code": "ONE"}}}]

        enriched, skipped = apply_context_scope_for_records(
            records,
            {"observe": ["prep.code", "prep.region", "prep.zone"]},
            action_name="miss_probe",
        )

        assert enriched == []
        assert skipped[0]["detail"] == (
            "context_scope.observe fields 'prep.region', 'prep.zone' not found in this record"
        )

    def test_one_missing_field_keeps_the_detail_it_had(self):
        records = [{"source_guid": "g1", "content": {"prep": {"code": "ONE"}}}]

        _, skipped = apply_context_scope_for_records(
            records, {"observe": ["prep.code", "prep.region"]}, action_name="miss_probe"
        )

        assert skipped[0]["detail"] == (
            "context_scope.observe field 'prep.region' not found in this record"
        )

    def test_each_record_is_judged_on_its_own_fields(self):
        records = [
            {"source_guid": "g1", "content": {"prep": {"code": "ONE", "region": "n", "zone": "z"}}},
            {"source_guid": "g2", "content": {"prep": {"code": "TWO", "region": "s"}}},
            {"source_guid": "g3", "content": {"prep": {"code": "THREE"}}},
        ]

        enriched, skipped = apply_context_scope_for_records(
            records,
            {"observe": ["prep.code", "prep.region", "prep.zone"]},
            action_name="miss_probe",
        )

        assert [r["source_guid"] for r in enriched] == ["g1"]
        assert [(s["source_guid"], s["detail"]) for s in skipped] == [
            ("g2", "context_scope.observe field 'prep.zone' not found in this record"),
            (
                "g3",
                "context_scope.observe fields 'prep.region', 'prep.zone' not found in this record",
            ),
        ]
