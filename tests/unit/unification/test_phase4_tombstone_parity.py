"""Phase 4: Online tombstone parity — all tombstone types must have consistent structural fields.

U-2.F: build_tombstone() and build_exhausted_tombstone() must both produce
``_tombstone: True`` and ``_tombstone_reason: <reason>`` so downstream code
(result collector, preview CLI, FILE tool) can identify tombstones by shape
instead of guessing from ``_state`` values.
"""

from unittest.mock import patch

import pytest

from agent_actions.processing.record_helpers import (
    build_exhausted_tombstone,
    build_tombstone,
)

# Every tombstone — regardless of reason — must have these fields.
REQUIRED_TOMBSTONE_FIELDS = {"_tombstone", "_tombstone_reason"}


def _make_input_record(**overrides):
    """Minimal input record for tombstone construction."""
    base = {
        "content": {"upstream_action": {"field": "value"}},
        "target_id": "t-001",
        "source_guid": "sg-001",
        "_state_history": [
            {
                "timestamp": "2026-01-01T00:00:00",
                "action": "prior",
                "from": None,
                "to": "active",
                "reason": "init",
                "detail": None,
            }
        ],
    }
    base.update(overrides)
    return base


class TestTombstoneMarkerFields:
    """build_tombstone() must set _tombstone and _tombstone_reason."""

    @pytest.mark.parametrize(
        "reason",
        [
            "upstream_unprocessed",
            "guard_skip",
            "guard_filter",
            "guard_prefilter_skip",
            "prep_failed",
            "batch_not_returned",
            "llm_layer_guard_skip",
        ],
    )
    def test_tombstone_has_marker_fields(self, reason):
        """Every reason must produce _tombstone=True and _tombstone_reason=<reason>."""
        record = _make_input_record()
        tombstone = build_tombstone("action", record, reason, source_guid="sg-001")

        missing = REQUIRED_TOMBSTONE_FIELDS - set(tombstone.keys())
        assert not missing, f"Tombstone for reason={reason!r} missing fields: {missing}"
        assert tombstone["_tombstone"] is True
        assert tombstone["_tombstone_reason"] == reason

    def test_tombstone_none_input_has_marker_fields(self):
        """Even with None input_record, marker fields must be present."""
        tombstone = build_tombstone("action", None, "guard_skip")
        assert tombstone["_tombstone"] is True
        assert tombstone["_tombstone_reason"] == "guard_skip"


class TestExhaustedTombstoneMarkerFields:
    """build_exhausted_tombstone() must set _tombstone and _tombstone_reason."""

    def test_exhausted_tombstone_has_marker_fields(self):
        record = _make_input_record()
        tombstone = build_exhausted_tombstone(
            "action", record, {"field": None}, source_guid="sg-001"
        )

        missing = REQUIRED_TOMBSTONE_FIELDS - set(tombstone.keys())
        assert not missing, f"Exhausted tombstone missing fields: {missing}"
        assert tombstone["_tombstone"] is True
        assert tombstone["_tombstone_reason"] == "retry_exhausted"

    def test_exhausted_tombstone_none_input_has_marker_fields(self):
        tombstone = build_exhausted_tombstone("action", None, {"field": None})
        assert tombstone["_tombstone"] is True
        assert tombstone["_tombstone_reason"] == "retry_exhausted"


class TestTombstoneShapeParity:
    """All tombstone types must share structural marker fields."""

    def test_regular_and_exhausted_both_have_markers(self):
        """build_tombstone and build_exhausted_tombstone produce same marker field set."""
        record = _make_input_record()

        regular = build_tombstone("action", record, "guard_skip", source_guid="sg-001")
        exhausted = build_exhausted_tombstone(
            "action", record, {"field": None}, source_guid="sg-001"
        )

        for field in REQUIRED_TOMBSTONE_FIELDS:
            assert field in regular, f"build_tombstone missing {field}"
            assert field in exhausted, f"build_exhausted_tombstone missing {field}"

    def test_upstream_and_guard_skip_have_same_marker_keys(self):
        """UPSTREAM_UNPROCESSED and GUARD_SKIP tombstones share identical marker fields."""
        record = _make_input_record()
        cascade = build_tombstone("action", record, "upstream_unprocessed", source_guid="sg-001")
        skip = build_tombstone("action", record, "guard_skip", source_guid="sg-001")

        for field in REQUIRED_TOMBSTONE_FIELDS:
            assert field in cascade, f"cascade tombstone missing {field}"
            assert field in skip, f"skip tombstone missing {field}"
        assert cascade["_tombstone"] is True
        assert skip["_tombstone"] is True

    def test_extra_metadata_does_not_clobber_regular_markers(self):
        """extra_metadata kwarg must not overwrite _tombstone/_tombstone_reason on build_tombstone."""
        tombstone = build_tombstone(
            "action",
            _make_input_record(),
            "guard_skip",
            source_guid="sg-001",
            extra_metadata={"custom": "val"},
        )
        assert tombstone["_tombstone"] is True
        assert tombstone["_tombstone_reason"] == "guard_skip"

    def test_extra_metadata_does_not_clobber_exhausted_markers(self):
        """extra_metadata kwarg must not overwrite _tombstone/_tombstone_reason on build_exhausted_tombstone."""
        tombstone = build_exhausted_tombstone(
            "action",
            _make_input_record(),
            {"field": None},
            source_guid="sg-001",
            extra_metadata={"custom": "val"},
        )
        assert tombstone["_tombstone"] is True
        assert tombstone["_tombstone_reason"] == "retry_exhausted"


class TestSiblingBuilderParity:
    """Sibling builders that construct tombstone-like records must also carry markers."""

    def test_exhausted_record_builder_has_markers(self):
        """ExhaustedRecordBuilder.build_exhausted_item must set _tombstone markers."""
        from agent_actions.processing.exhausted_builder import ExhaustedRecordBuilder
        from agent_actions.processing.types import RecoveryMetadata, RetryMetadata

        recovery = RecoveryMetadata(
            retry=RetryMetadata(attempts=3, failures=3, succeeded=False, reason="api_error")
        )
        item = ExhaustedRecordBuilder.build_exhausted_item(
            source_guid="sg-001",
            original_row=_make_input_record(),
            recovery_metadata=recovery,
            agent_config={"action_name": "test_action"},
            action_name="test_action",
        )
        assert item["_tombstone"] is True
        assert item["_tombstone_reason"] == "retry_exhausted"

    def test_passthrough_item_builder_has_markers(self):
        """PassthroughItemBuilder.build_item must set _tombstone markers."""
        from agent_actions.utils.passthrough_builder import PassthroughItemBuilder

        with patch.multiple(
            "agent_actions.utils.passthrough_builder.IDGenerator",
            generate_target_id=staticmethod(lambda: "fixed-tid"),
            generate_node_id=staticmethod(lambda action_name: f"{action_name}_fixed-nid"),
        ):
            item = PassthroughItemBuilder.build_item(
                row=_make_input_record(),
                reason="where_clause_not_matched",
                action_name="test_action",
            )
        assert item["_tombstone"] is True
        assert item["_tombstone_reason"] == "where_clause_not_matched"
