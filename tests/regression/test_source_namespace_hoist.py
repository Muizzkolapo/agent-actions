"""Regression tests locking in the source-namespace-hoist data-model fix.

Before this refactor, the user's original staging fields were stuffed inside
``record["content"]["source"]`` and consumers had to duck-type the shape to
recover them. After PR #433 added ``_state`` / ``_transitions``, the duck-type
misclassified wrapped target envelopes and the bus started returning the
previous action's output dict as the "source" namespace — every multi-action
pipeline failed at action 2 with::

    context_scope.observe field 'source.page_content' not found at runtime

The fix: hoist ``source`` out of ``content`` onto the envelope as a top-level
tracking field. This file pins the new behavior in five scenarios.
"""

from __future__ import annotations

from typing import Any

import pytest

from agent_actions.processing.record_helpers import build_guard_skipped_record
from agent_actions.prompt.context.scope_application import (
    apply_context_scope_for_records,
)
from agent_actions.prompt.context.scope_builder import (
    _load_source_namespace,
    build_field_context_with_history,
)
from agent_actions.record.envelope import (
    RECORD_TRACKING_FIELDS,
    RecordEnvelope,
)
from agent_actions.record.state import RecordState

# ---------------------------------------------------------------------------
# 1. Source is a tracking field — RecordEnvelope.build carries it
# ---------------------------------------------------------------------------


class TestSourceIsTrackingField:
    def test_source_is_in_tracking_fields(self):
        assert "source" in RECORD_TRACKING_FIELDS

    def test_build_carries_source_through_one_action(self):
        admitted_first_stage = {
            "source_guid": "sg-1",
            "source": {"page_content": "hello", "title": "T"},
            "_state": RecordState.ACTIVE.value,
        }
        result = RecordEnvelope.build("action_1", {"summary": "hi"}, admitted_first_stage)
        assert result["source"] == {"page_content": "hello", "title": "T"}
        assert "source" not in result["content"]
        assert result["content"] == {"action_1": {"summary": "hi"}}

    def test_build_carries_source_through_three_actions(self):
        r0 = {
            "source_guid": "sg-1",
            "source": {"page_content": "hello", "title": "T"},
            "_state": RecordState.ACTIVE.value,
        }
        r1 = RecordEnvelope.build("action_1", {"summary": "hi"}, r0)
        r2 = RecordEnvelope.build("action_2", {"score": 9}, r1)
        r3 = RecordEnvelope.build("action_3", {"label": "ok"}, r2)
        assert r3["source"] == {"page_content": "hello", "title": "T"}
        assert "source" not in r3["content"]
        assert set(r3["content"].keys()) == {"action_1", "action_2", "action_3"}


# ---------------------------------------------------------------------------
# 2. admit_staging_row hoists raw fields under "source"
# ---------------------------------------------------------------------------


class TestAdmissionHoistsSource:
    def test_hoist_creates_source_field(self):
        row = {"page_content": "x", "title": "T", "source_guid": "sg"}
        RecordEnvelope.admit_staging_row(row)
        assert row["source"] == {"page_content": "x", "title": "T"}
        assert "page_content" not in row
        assert "title" not in row

    def test_admission_is_idempotent(self):
        row: dict[str, Any] = {
            "source": {"page_content": "x"},
            "source_guid": "sg",
            "_state": RecordState.ACTIVE.value,
        }
        snapshot = dict(row)
        snapshot["source"] = dict(row["source"])
        RecordEnvelope.admit_staging_row(row)
        assert row == snapshot


# ---------------------------------------------------------------------------
# 3. Bus reads source from the envelope's top-level field
# ---------------------------------------------------------------------------


class TestBusReadsEnvelopeSource:
    def test_load_source_namespace_reads_envelope_top_level(self):
        record = {
            "source_guid": "sg",
            "source": {"page_content": "hello"},
            "content": {"action_1": {"x": 1}},
            "_state": RecordState.ACTIVE.value,
        }
        field_context: dict[str, Any] = {}
        _load_source_namespace(field_context, record, "action_2")
        assert field_context["source"] == {"page_content": "hello"}

    def test_action_two_can_read_source_page_content(self):
        """Reproduces the original bug: action 2 must resolve source.page_content."""
        upstream_record = {
            "source_guid": "sg-1",
            "source": {"page_content": "hello world", "title": "T"},
            "content": {"action_1": {"summary": "hi"}},
            "_state": RecordState.ACTIVE.value,
            "_transitions": [{"from_state": "active", "to_state": "active"}],
        }
        field_context = build_field_context_with_history(
            agent_name="action_2",
            agent_config={"context_scope": {"observe": ["source.page_content"]}},
            current_item=upstream_record,
        )
        assert field_context["source"]["page_content"] == "hello world"
        assert field_context["source"]["title"] == "T"

    def test_no_source_field_yields_no_source_namespace(self):
        record_without_source = {
            "source_guid": "sg",
            "content": {"action_1": {"x": 1}},
            "_state": RecordState.ACTIVE.value,
        }
        field_context: dict[str, Any] = {}
        _load_source_namespace(field_context, record_without_source, "action_2")
        assert "source" not in field_context


# ---------------------------------------------------------------------------
# 4. apply_context_scope_for_records reads source from envelope (no list)
# ---------------------------------------------------------------------------


class TestFileModeScopeReadsEnvelope:
    def test_source_is_resolved_per_record_without_source_data_list(self):
        records = [
            {
                "source_guid": "sg-A",
                "source": {"url": "https://a.example"},
                "content": {"extract": {"text": "Q1"}},
            },
            {
                "source_guid": "sg-B",
                "source": {"url": "https://b.example"},
                "content": {"extract": {"text": "Q2"}},
            },
        ]
        scope = {"observe": ["extract.text", "source.url"]}
        result = apply_context_scope_for_records(records, scope, action_name="classify")
        # source_data parameter is gone — the envelope is the only source of truth.
        assert result[0]["content"]["url"] == "https://a.example"
        assert result[1]["content"]["url"] == "https://b.example"


# ---------------------------------------------------------------------------
# 5. Guard-skipped records preserve source (tracking-field invariant)
# ---------------------------------------------------------------------------


class TestGuardSkipPreservesSource:
    def test_guard_skipped_record_carries_source(self):
        upstream = {
            "source_guid": "sg",
            "source": {"page_content": "hello"},
            "content": {"action_1": {"x": 1}},
            "_state": RecordState.ACTIVE.value,
        }
        skipped = build_guard_skipped_record(
            "action_2",
            upstream,
            source_guid="sg",
            clause="x == 0",
            behavior="skip",
            result=False,
        )
        assert skipped["source"] == {"page_content": "hello"}
        assert "source" not in skipped["content"]


# ---------------------------------------------------------------------------
# Edge case: literal user "source" field at staging admission
# ---------------------------------------------------------------------------


class TestLiteralUserSourceField:
    def test_pre_existing_source_dict_is_preserved(self):
        # If a user happens to provide a top-level "source" key in their
        # staging input, admission treats it as already-admitted and leaves
        # it alone — no double wrapping.
        row = {"source": {"some_field": "value"}, "source_guid": "sg"}
        RecordEnvelope.admit_staging_row(row)
        assert row["source"] == {"some_field": "value"}
        assert "_state" in row


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
