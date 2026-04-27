"""Regression tests: lineage preservation across version merge boundaries.

When version_consumption merges outputs from N version agents, the merged
record's lineage must survive into the consuming action's output.  Before the
fix, _create_correlation_source_data() wrote skeletal source records without
lineage, causing the enricher to truncate to [own_node_id].
"""

import json
from pathlib import Path

import pytest

from agent_actions.processing.enrichment import LineageEnricher
from agent_actions.processing.types import ProcessingContext, ProcessingResult
from agent_actions.workflow.managers.loop import VersionOutputCorrelator

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_version_outputs(agent_folder: Path, version_agents: dict):
    """Write version agent output files to target directories.

    version_agents: {"agent_name": [records...], ...}
    """
    for agent_name, records in version_agents.items():
        target_dir = agent_folder / "target" / agent_name
        target_dir.mkdir(parents=True, exist_ok=True)
        with open(target_dir / "data.json", "w") as f:
            json.dump(records, f)


def _load_source_data(agent_folder: Path, filename: str = "data.json") -> list[dict]:
    """Load source records written by _create_correlation_source_data."""
    source_file = agent_folder / "source" / filename
    if not source_file.exists():
        return []
    with open(source_file) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestVersionMergeLineage:
    """Verify lineage survives version merge and is extended by consuming action."""

    @pytest.fixture
    def agent_folder(self, tmp_path):
        return tmp_path

    @pytest.fixture
    def correlator(self, agent_folder):
        return VersionOutputCorrelator(agent_folder)

    def test_merged_record_preserves_lineage(self, correlator, agent_folder):
        """Merged record has union of all version agent lineages."""
        _write_version_outputs(
            agent_folder,
            {
                "score_quality_1": [
                    {
                        "source_guid": "sg-001",
                        "version_correlation_id": "vc-001",
                        "target_id": "tid-1",
                        "node_id": "score_quality_1_aaa",
                        "lineage": ["extract_facts_000", "score_quality_1_aaa"],
                        "content": {"score_quality_1": {"score": 8}},
                    },
                ],
                "score_quality_2": [
                    {
                        "source_guid": "sg-001",
                        "version_correlation_id": "vc-001",
                        "target_id": "tid-2",
                        "node_id": "score_quality_2_bbb",
                        "lineage": ["extract_facts_000", "score_quality_2_bbb"],
                        "content": {"score_quality_2": {"score": 7}},
                    },
                ],
                "score_quality_3": [
                    {
                        "source_guid": "sg-001",
                        "version_correlation_id": "vc-001",
                        "target_id": "tid-3",
                        "node_id": "score_quality_3_ccc",
                        "lineage": ["extract_facts_000", "score_quality_3_ccc"],
                        "content": {"score_quality_3": {"score": 9}},
                    },
                ],
            },
        )

        result_dir = correlator.prepare_correlated_input(
            "aggregate_votes",
            ["score_quality_1", "score_quality_2", "score_quality_3"],
            4,
        )
        assert result_dir is not None

        with open(Path(result_dir) / "data.json") as f:
            merged_records = json.load(f)

        assert len(merged_records) == 1
        rec = merged_records[0]
        assert rec["source_guid"] == "sg-001"
        assert rec["lineage"].count("extract_facts_000") == 1
        assert "score_quality_1_aaa" in rec["lineage"]
        assert "score_quality_2_bbb" in rec["lineage"]
        assert "score_quality_3_ccc" in rec["lineage"]

    def test_consuming_action_extends_merged_lineage(self, correlator, agent_folder):
        """Consuming action's enricher extends merged lineage, not truncates."""
        _write_version_outputs(
            agent_folder,
            {
                "scorer_1": [
                    {
                        "source_guid": "sg-001",
                        "version_correlation_id": "vc-001",
                        "target_id": "tid-1",
                        "node_id": "scorer_1_aaa",
                        "lineage": ["node_0_root", "scorer_1_aaa"],
                        "content": {"scorer_1": {"score": 8}},
                    },
                ],
                "scorer_2": [
                    {
                        "source_guid": "sg-001",
                        "version_correlation_id": "vc-001",
                        "target_id": "tid-2",
                        "node_id": "scorer_2_bbb",
                        "lineage": ["node_0_root", "scorer_2_bbb"],
                        "content": {"scorer_2": {"score": 7}},
                    },
                ],
            },
        )

        correlator.prepare_correlated_input("consumer", ["scorer_1", "scorer_2"], 3)

        source_data = _load_source_data(agent_folder)
        assert len(source_data) == 1
        assert "lineage" in source_data[0], "Source record must include lineage"

        enricher = LineageEnricher()
        result = ProcessingResult.success(
            data=[{"content": {"aggregated": True}}],
            source_guid="sg-001",
        )
        context = ProcessingContext(
            agent_config={"agent_type": "consumer"},
            agent_name="consumer",
            is_first_stage=False,
            source_data=source_data,
        )

        enriched = enricher.enrich(result, context)

        item = enriched.data[0]
        lineage = item["lineage"]
        assert "node_0_root" in lineage
        version_nodes = {"scorer_1_aaa", "scorer_2_bbb"}
        assert version_nodes & set(lineage), "At least one version node_id must be in lineage"
        # Must end with consumer's own node_id (not truncated to just this)
        assert len(lineage) > 1, "Lineage must not be truncated to [own_node_id]"

    def test_merged_record_has_source_guid(self, correlator, agent_folder):
        """Merged record source_guid is non-empty."""
        _write_version_outputs(
            agent_folder,
            {
                "v1": [
                    {
                        "source_guid": "sg-abc",
                        "version_correlation_id": "vc-1",
                        "target_id": "tid-1",
                        "node_id": "v1_aaa",
                        "lineage": ["root_000", "v1_aaa"],
                        "content": {"v1": {"x": 1}},
                    },
                ],
            },
        )

        result_dir = correlator.prepare_correlated_input("consumer", ["v1"], 2)
        with open(Path(result_dir) / "data.json") as f:
            records = json.load(f)

        assert records[0]["source_guid"] == "sg-abc"

        source_data = _load_source_data(agent_folder)
        assert source_data[0]["source_guid"] == "sg-abc"

    def test_partial_merge_preserves_lineage(self, correlator, agent_folder):
        """Missing versions don't break lineage on present versions."""
        _write_version_outputs(
            agent_folder,
            {
                "v1": [
                    {
                        "source_guid": "sg-001",
                        "version_correlation_id": "vc-001",
                        "target_id": "tid-1",
                        "node_id": "v1_aaa",
                        "lineage": ["root_000", "v1_aaa"],
                        "content": {"v1": {"x": 1}},
                    },
                    {
                        "source_guid": "sg-002",
                        "version_correlation_id": "vc-002",
                        "target_id": "tid-2",
                        "node_id": "v1_bbb",
                        "lineage": ["root_001", "v1_bbb"],
                        "content": {"v1": {"x": 2}},
                    },
                ],
                "v2": [
                    # Only has sg-001, missing sg-002
                    {
                        "source_guid": "sg-001",
                        "version_correlation_id": "vc-001",
                        "target_id": "tid-3",
                        "node_id": "v2_ccc",
                        "lineage": ["root_000", "v2_ccc"],
                        "content": {"v2": {"y": 1}},
                    },
                ],
            },
        )

        result_dir = correlator.prepare_correlated_input("consumer", ["v1", "v2"], 3)
        with open(Path(result_dir) / "data.json") as f:
            records = json.load(f)

        assert len(records) == 2

        # Record with both versions: full merged lineage
        rec1 = next(r for r in records if r["source_guid"] == "sg-001")
        assert "root_000" in rec1["lineage"]
        assert "v1_aaa" in rec1["lineage"]
        assert "v2_ccc" in rec1["lineage"]

        # Record with only v1: lineage from v1 only, still correct
        rec2 = next(r for r in records if r["source_guid"] == "sg-002")
        assert rec2["lineage"] == ["root_001", "v1_bbb"]

    def test_source_file_lineage_enables_enricher_chain(self, correlator, agent_folder):
        """Source file with lineage lets enricher build correct chain for multiple records."""
        _write_version_outputs(
            agent_folder,
            {
                "gen_1": [
                    {
                        "source_guid": "sg-A",
                        "version_correlation_id": "vc-A",
                        "target_id": "tid-A1",
                        "node_id": "gen_1_aaa",
                        "lineage": ["extract_000", "gen_1_aaa"],
                        "content": {"gen_1": {"val": 1}},
                    },
                    {
                        "source_guid": "sg-B",
                        "version_correlation_id": "vc-B",
                        "target_id": "tid-B1",
                        "node_id": "gen_1_bbb",
                        "lineage": ["extract_001", "gen_1_bbb"],
                        "content": {"gen_1": {"val": 2}},
                    },
                ],
                "gen_2": [
                    {
                        "source_guid": "sg-A",
                        "version_correlation_id": "vc-A",
                        "target_id": "tid-A2",
                        "node_id": "gen_2_ccc",
                        "lineage": ["extract_000", "gen_2_ccc"],
                        "content": {"gen_2": {"val": 3}},
                    },
                    {
                        "source_guid": "sg-B",
                        "version_correlation_id": "vc-B",
                        "target_id": "tid-B2",
                        "node_id": "gen_2_ddd",
                        "lineage": ["extract_001", "gen_2_ddd"],
                        "content": {"gen_2": {"val": 4}},
                    },
                ],
            },
        )

        correlator.prepare_correlated_input("consumer", ["gen_1", "gen_2"], 3)
        source_data = _load_source_data(agent_folder)
        assert len(source_data) == 2

        # Enrich each record — per-item parent lookup via source_guid matching
        enricher = LineageEnricher()

        for sg in ["sg-A", "sg-B"]:
            result = ProcessingResult.success(
                data=[{"content": {"processed": True}}],
                source_guid=sg,
            )
            context = ProcessingContext(
                agent_config={"agent_type": "consumer"},
                agent_name="consumer",
                is_first_stage=False,
                source_data=source_data,
            )
            enriched = enricher.enrich(result, context)
            item = enriched.data[0]
            assert len(item["lineage"]) > 1, f"Lineage for {sg} truncated to {item['lineage']}"
