"""What a version merge leaves on disk, and what carries lineage once it has."""

import pytest

from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
from agent_actions.utils.lineage import LineageBuilder
from agent_actions.workflow.managers.loop import VersionOutputCorrelator

LIFECYCLE = {"_state": "processed", "_state_schema_version": 1}


def _versions(guid="sg-001"):
    return {
        f"scorer_{i}": [
            {
                "source_guid": guid,
                "version_correlation_id": f"vc-{guid}",
                "target_id": f"tid-{i}",
                "node_id": f"scorer_{i}_n{i}",
                "lineage": ["root_000", f"scorer_{i}_n{i}"],
                "content": {f"scorer_{i}": {"score": i}},
            }
        ]
        for i in (1, 2)
    }


@pytest.fixture
def agent_folder(tmp_path):
    return tmp_path / "wf" / "agent_io"


@pytest.fixture
def backend(agent_folder):
    b = SQLiteBackend.create(db_path=str(agent_folder / "store" / "test.db"), workflow_name="test")
    b.initialize()
    yield b
    b.close()


@pytest.fixture
def correlator(agent_folder, backend):
    return VersionOutputCorrelator(agent_folder, storage_backend=backend)


def _write_versions(backend, agents):
    for name, records in agents.items():
        backend._write_target_raw(name, "data.json", [{**r, **LIFECYCLE} for r in records])


class TestAMergeLeavesNoJsonArtefact:
    def test_no_json_file_is_written_anywhere_under_the_workflow(
        self, correlator, backend, agent_folder, tmp_path
    ):
        """Pins the absence of an artefact, not merely the absence of one directory."""
        _write_versions(backend, _versions())

        correlator.prepare_correlated_input("consumer", ["scorer_1", "scorer_2"], 3)

        assert [str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*.json")] == []


class TestTheNoBackendBranchWritesOnlyItsTarget:
    def test_the_correlated_file_lands_and_no_source_directory_appears(self, tmp_path):
        """The disk branch is the one a backend-less correlator takes."""
        agent_folder = tmp_path / "wf" / "agent_io"
        out_dir = agent_folder / "target" / "consumer"
        out_dir.mkdir(parents=True)
        correlator = VersionOutputCorrelator(agent_folder)

        correlator._write_correlated_data(
            out_dir, [{"source_guid": "sg-001", "target_id": "t1", "node_id": "n1"}], "data.json"
        )

        assert (out_dir / "data.json").exists()
        assert not (agent_folder / "source").exists()


class TestTwoMergesSharingATargetBasename:
    def test_each_consumer_keeps_its_own_output(self, correlator, backend, agent_folder):
        """The basename collision the old artefact had cannot recur in the store."""
        _write_versions(backend, _versions())

        correlator.prepare_correlated_input("consumer", ["scorer_1", "scorer_2"], 3)
        correlator.prepare_correlated_input("other_consumer", ["scorer_1", "scorer_2"], 4)

        first = backend.read_target("consumer", "data.json")
        second = backend.read_target("other_consumer", "data.json")
        assert [r["source_guid"] for r in first] == ["sg-001"]
        assert [r["source_guid"] for r in second] == ["sg-001"]


class TestTheMergedRecordCanParentTheConsumer:
    def test_it_passes_the_filter_that_populates_parent_records(
        self, correlator, backend, agent_folder
    ):
        """`parent_records` is built by this predicate; a merged record must satisfy it."""
        _write_versions(backend, _versions())

        correlator.prepare_correlated_input("consumer", ["scorer_1", "scorer_2"], 3)

        merged = backend.read_target("consumer", "data.json")
        assert [LineageBuilder.is_lineage_bearing(r) for r in merged] == [True]

    def test_a_record_stripped_of_lineage_would_not(self, correlator, backend, agent_folder):
        """The predicate is doing work — it rejects what the old stub rows looked like."""
        stub = {"source_guid": "sg-001", "id": "t1", "lineage": [], "node_id": "n1"}
        assert LineageBuilder.is_lineage_bearing(stub) is False
