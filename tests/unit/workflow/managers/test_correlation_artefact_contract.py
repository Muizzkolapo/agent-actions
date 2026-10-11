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


class TestTheConsumersOwnTargetIsLeftAlone:
    def test_what_it_stored_before_is_still_what_it_holds(self, correlator, backend):
        """Its target holds its answers, which a run carries records from (1318)."""
        _write_versions(backend, _versions())
        answer = {
            "source_guid": "sg-001",
            "target_id": "tid-consumer",
            "node_id": "consumer_n",
            "lineage": ["root_000", "consumer_n"],
            "content": {"consumer": {"verdict": "keep"}},
            **LIFECYCLE,
        }
        backend._write_target_raw("consumer", "data.json", [answer])

        correlator.prepare_correlated_input("consumer", ["scorer_1", "scorer_2"], 3)

        assert backend._read_target_raw("consumer", "data.json") == [answer]


class TestTwoMergesSharingATargetBasename:
    def test_each_consumer_gets_its_own_input(self, correlator, backend, agent_folder):
        """The basename collision the old artefact had cannot recur."""
        _write_versions(backend, _versions())

        first = correlator.prepare_correlated_input("consumer", ["scorer_1", "scorer_2"], 3)
        second = correlator.prepare_correlated_input("other_consumer", ["scorer_1", "scorer_2"], 4)

        assert [r["source_guid"] for r in first["data.json"]] == ["sg-001"]
        assert [r["source_guid"] for r in second["data.json"]] == ["sg-001"]


class TestTheMergedRecordCanParentTheConsumer:
    def test_it_passes_the_filter_that_populates_parent_records(
        self, correlator, backend, agent_folder
    ):
        """`parent_records` is built by this predicate; a merged record must satisfy it."""
        _write_versions(backend, _versions())

        merged = correlator.prepare_correlated_input("consumer", ["scorer_1", "scorer_2"], 3)

        assert [LineageBuilder.is_lineage_bearing(r) for r in merged["data.json"]] == [True]

    def test_a_record_stripped_of_lineage_would_not(self, correlator, backend, agent_folder):
        """The predicate is doing work — it rejects what the old stub rows looked like."""
        stub = {"source_guid": "sg-001", "id": "t1", "lineage": [], "node_id": "n1"}
        assert LineageBuilder.is_lineage_bearing(stub) is False
