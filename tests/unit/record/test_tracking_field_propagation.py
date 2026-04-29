"""Tests for tracking field propagation through RecordEnvelope and enrichment pipeline."""

from agent_actions.record.envelope import (
    RECORD_FRAMEWORK_FIELDS,
    RECORD_STAGE_FIELDS,
    RECORD_TRACKING_FIELDS,
    RecordEnvelope,
)


class TestFieldSets:
    def test_tracking_fields_are_subset_of_framework(self):
        assert RECORD_TRACKING_FIELDS < RECORD_FRAMEWORK_FIELDS

    def test_stage_fields_are_subset_of_framework(self):
        assert RECORD_STAGE_FIELDS < RECORD_FRAMEWORK_FIELDS

    def test_framework_is_union(self):
        assert RECORD_FRAMEWORK_FIELDS == RECORD_TRACKING_FIELDS | RECORD_STAGE_FIELDS

    def test_sets_are_disjoint(self):
        assert RECORD_TRACKING_FIELDS.isdisjoint(RECORD_STAGE_FIELDS)

    def test_tracking_contains_source_guid(self):
        assert "source_guid" in RECORD_TRACKING_FIELDS

    def test_tracking_contains_version_correlation_id(self):
        assert "version_correlation_id" in RECORD_TRACKING_FIELDS

    def test_metadata_not_in_tracking(self):
        # metadata is a per-stage field — must not bleed into tracking carry
        assert "metadata" not in RECORD_TRACKING_FIELDS

    def test_target_id_not_in_tracking(self):
        assert "target_id" not in RECORD_TRACKING_FIELDS


class TestEnvelopeBuildCarriesTrackingFields:
    def test_carries_version_correlation_id(self):
        inp = {
            "source_guid": "g1",
            "version_correlation_id": "vcid-abc",
            "content": {},
        }
        result = RecordEnvelope.build("act", {"x": 1}, inp)
        assert result["version_correlation_id"] == "vcid-abc"

    def test_carries_source_guid(self):
        inp = {"source_guid": "g1", "content": {}}
        result = RecordEnvelope.build("act", {"x": 1}, inp)
        assert result["source_guid"] == "g1"

    def test_does_not_carry_metadata(self):
        inp = {"source_guid": "g1", "metadata": {"model": "gpt-4"}, "content": {}}
        result = RecordEnvelope.build("act", {"x": 1}, inp)
        assert "metadata" not in result

    def test_does_not_carry_target_id(self):
        inp = {"source_guid": "g1", "target_id": "t1", "content": {}}
        result = RecordEnvelope.build("act", {"x": 1}, inp)
        assert "target_id" not in result

    def test_does_not_carry_lineage(self):
        inp = {"source_guid": "g1", "lineage": ["n1", "n2"], "content": {}}
        result = RecordEnvelope.build("act", {"x": 1}, inp)
        assert "lineage" not in result

    def test_no_input_record_no_tracking_fields(self):
        result = RecordEnvelope.build("act", {"x": 1})
        assert "source_guid" not in result
        assert "version_correlation_id" not in result

    def test_tracking_fields_chain_through_stages(self):
        """version_correlation_id must survive 3 sequential build() calls."""
        r1 = RecordEnvelope.build(
            "source",
            {"raw": "data"},
            {"source_guid": "g1", "version_correlation_id": "vcid-xyz", "content": {}},
        )
        r2 = RecordEnvelope.build("summarize", {"summary": "short"}, r1)
        r3 = RecordEnvelope.build("review", {"score": 9}, r2)

        assert r3["version_correlation_id"] == "vcid-xyz"
        assert r3["source_guid"] == "g1"


class TestBuildSkippedCarriesTrackingFields:
    def test_carries_version_correlation_id(self):
        inp = {
            "source_guid": "g1",
            "version_correlation_id": "vcid-abc",
            "content": {"prior": {"x": 1}},
        }
        result = RecordEnvelope.build_skipped("skipped_action", inp)
        assert result["version_correlation_id"] == "vcid-abc"

    def test_does_not_carry_metadata(self):
        inp = {
            "source_guid": "g1",
            "metadata": {"model": "gpt-4"},
            "content": {},
        }
        result = RecordEnvelope.build_skipped("skipped_action", inp)
        assert "metadata" not in result
