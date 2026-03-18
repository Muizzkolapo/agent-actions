"""Regression tests for VersionOutputCorrelator._create_merged_record."""

from agent_actions.workflow.managers.loop import VersionOutputCorrelator


class TestCreateMergedRecordSourceGuid:
    """Verify _create_merged_record handles missing source_guid gracefully."""

    def _make_correlator(self, tmp_path):
        return VersionOutputCorrelator(agent_folder=tmp_path)

    def test_source_guid_present(self, tmp_path):
        """source_guid in base record is propagated to merged record."""
        correlator = self._make_correlator(tmp_path)
        agent_records = {
            "v1": {"source_guid": "sg-abc", "content": {"x": 1}},
        }
        version_outputs = {"v1": [agent_records["v1"]]}

        merged = correlator._create_merged_record(agent_records, version_outputs)

        assert merged["source_guid"] == "sg-abc"

    def test_source_guid_missing_does_not_raise(self, tmp_path):
        """Missing source_guid should not raise KeyError (was a bug)."""
        correlator = self._make_correlator(tmp_path)
        agent_records = {
            "v1": {"content": {"x": 1}},  # no source_guid
        }
        version_outputs = {"v1": [agent_records["v1"]]}

        merged = correlator._create_merged_record(agent_records, version_outputs)

        assert merged["source_guid"] is None

    def test_merged_record_contains_all_expected_keys(self, tmp_path):
        """Merged record should always contain the canonical keys."""
        correlator = self._make_correlator(tmp_path)
        agent_records = {
            "v1": {
                "source_guid": "sg-1",
                "target_id": "tid-1",
                "node_id": "nid-1",
                "version_correlation_id": "vcid-1",
                "content": {"val": 42},
            },
        }
        version_outputs = {"v1": [agent_records["v1"]]}

        merged = correlator._create_merged_record(agent_records, version_outputs)

        assert merged["source_guid"] == "sg-1"
        assert merged["target_id"] == "tid-1"
        assert merged["node_id"] == "nid-1"
        assert merged["version_correlation_id"] == "vcid-1"
        assert "content" in merged
        assert "_correlation_sources" in merged
