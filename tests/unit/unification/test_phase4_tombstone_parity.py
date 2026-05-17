"""Phase 4: Online tombstone parity — all tombstone types must have consistent structural fields.

U-2.F: build_tombstone() and build_exhausted_tombstone() must both produce
``_tombstone: True`` and ``_tombstone_reason: <reason>`` so downstream code
(result collector, preview CLI, FILE tool) can identify tombstones by shape
instead of guessing from ``_state`` values.
"""

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

        cascade_markers = {k: cascade[k] for k in REQUIRED_TOMBSTONE_FIELDS}
        skip_markers = {k: skip[k] for k in REQUIRED_TOMBSTONE_FIELDS}

        # Both must have the same keys (values differ by reason)
        assert set(cascade_markers.keys()) == set(skip_markers.keys())
        assert cascade_markers["_tombstone"] is True
        assert skip_markers["_tombstone"] is True

    def test_extra_metadata_does_not_clobber_markers(self):
        """extra_metadata kwarg must not overwrite _tombstone/_tombstone_reason."""
        tombstone = build_tombstone(
            "action",
            _make_input_record(),
            "guard_skip",
            source_guid="sg-001",
            extra_metadata={"custom": "val"},
        )
        assert tombstone["_tombstone"] is True
        assert tombstone["_tombstone_reason"] == "guard_skip"
