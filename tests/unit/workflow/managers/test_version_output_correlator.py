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
            "v1": {"source_guid": "sg-abc", "content": {"v1": {"x": 1}}},
        }
        version_outputs = {"v1": [agent_records["v1"]]}

        merged = correlator._create_merged_record(agent_records, version_outputs)

        assert merged["source_guid"] == "sg-abc"

    def test_source_guid_missing_does_not_raise(self, tmp_path):
        """Missing source_guid should not raise KeyError (was a bug)."""
        correlator = self._make_correlator(tmp_path)
        agent_records = {
            "v1": {"content": {"v1": {"x": 1}}},  # no source_guid
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
                "content": {"v1": {"val": 42}},
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


class TestCreateMergedRecordLineage:
    """Verify _create_merged_record merges lineage from all version agents."""

    def _make_correlator(self, tmp_path):
        return VersionOutputCorrelator(agent_folder=tmp_path)

    def test_lineage_merged_from_all_versions(self, tmp_path):
        """Merged lineage contains entries from ALL version agents, deduplicated."""
        correlator = self._make_correlator(tmp_path)
        agent_records = {
            "v1": {
                "source_guid": "sg-1",
                "lineage": ["node_0_aaa", "node_1_v1"],
                "content": {"v1": {"x": 1}},
            },
            "v2": {
                "source_guid": "sg-1",
                "lineage": ["node_0_aaa", "node_1_v2"],
                "content": {"v2": {"x": 2}},
            },
            "v3": {
                "source_guid": "sg-1",
                "lineage": ["node_0_aaa", "node_1_v3"],
                "content": {"v3": {"x": 3}},
            },
        }
        version_outputs = {k: [v] for k, v in agent_records.items()}

        merged = correlator._create_merged_record(agent_records, version_outputs)

        assert merged["lineage"].count("node_0_aaa") == 1
        assert "node_1_v1" in merged["lineage"]
        assert "node_1_v2" in merged["lineage"]
        assert "node_1_v3" in merged["lineage"]
        assert len(merged["lineage"]) == 4

    def test_lineage_empty_when_versions_have_no_lineage(self, tmp_path):
        """Merged lineage is empty list when no version has lineage."""
        correlator = self._make_correlator(tmp_path)
        agent_records = {
            "v1": {"source_guid": "sg-1", "content": {"v1": {"x": 1}}},
            "v2": {"source_guid": "sg-1", "content": {"v2": {"x": 2}}},
        }
        version_outputs = {k: [v] for k, v in agent_records.items()}

        merged = correlator._create_merged_record(agent_records, version_outputs)

        assert merged["lineage"] == []

    def test_lineage_preserves_order(self, tmp_path):
        """Merged lineage preserves insertion order: ancestors first, then version-specific."""
        correlator = self._make_correlator(tmp_path)
        agent_records = {
            "v1": {
                "source_guid": "sg-1",
                "lineage": ["root", "mid", "v1_leaf"],
                "content": {"v1": {"x": 1}},
            },
            "v2": {
                "source_guid": "sg-1",
                "lineage": ["root", "mid", "v2_leaf"],
                "content": {"v2": {"x": 2}},
            },
        }
        version_outputs = {k: [v] for k, v in agent_records.items()}

        merged = correlator._create_merged_record(agent_records, version_outputs)

        assert merged["lineage"][0] == "root"
        assert merged["lineage"][1] == "mid"
        assert "v1_leaf" in merged["lineage"]
        assert "v2_leaf" in merged["lineage"]

    def test_partial_merge_preserves_lineage_from_present_versions(self, tmp_path):
        """Missing versions don't break lineage on present versions."""
        correlator = self._make_correlator(tmp_path)
        agent_records = {
            "v1": {
                "source_guid": "sg-1",
                "lineage": ["node_0", "node_v1"],
                "content": {"v1": {"x": 1}},
            },
            # v2 and v3 missing for this source_guid
        }
        version_outputs = {
            "v1": [agent_records["v1"]],
            "v2": [],
            "v3": [],
        }

        merged = correlator._create_merged_record(agent_records, version_outputs)

        assert merged["lineage"] == ["node_0", "node_v1"]
        assert merged["source_guid"] == "sg-1"
        assert "_missing_iterations" in merged
        assert set(merged["_missing_iterations"]) == {"v2", "v3"}
