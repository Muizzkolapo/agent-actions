"""A version merge writes its correlated target and leaves nothing else behind."""

import pytest

from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
from agent_actions.workflow.managers.loop import VersionOutputCorrelator

LIFECYCLE = {"_state": "processed", "_state_schema_version": 1}

VERSIONS = {
    "scorer_1": [
        {
            "source_guid": "sg-001",
            "version_correlation_id": "vc-001",
            "target_id": "tid-1",
            "node_id": "scorer_1_aaa",
            "lineage": ["root_000", "scorer_1_aaa"],
            "content": {"scorer_1": {"score": 8}},
        }
    ],
    "scorer_2": [
        {
            "source_guid": "sg-001",
            "version_correlation_id": "vc-001",
            "target_id": "tid-2",
            "node_id": "scorer_2_bbb",
            "lineage": ["root_000", "scorer_2_bbb"],
            "content": {"scorer_2": {"score": 7}},
        }
    ],
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


class TestAVersionMergeLeavesNoSourceArtefact:
    def test_no_source_directory_is_created(self, correlator, backend, agent_folder):
        _write_versions(backend, VERSIONS)

        correlator.prepare_correlated_input("consumer", ["scorer_1", "scorer_2"], 3)

        assert not (agent_folder / "source").exists()

    def test_a_second_merge_to_the_same_basename_creates_nothing(
        self, correlator, backend, agent_folder
    ):
        _write_versions(backend, VERSIONS)

        correlator.prepare_correlated_input("consumer", ["scorer_1", "scorer_2"], 3)
        correlator.prepare_correlated_input("other_consumer", ["scorer_1", "scorer_2"], 4)

        assert not (agent_folder / "source").exists()

    def test_the_merged_target_still_reaches_the_store(self, correlator, backend, agent_folder):
        _write_versions(backend, VERSIONS)

        correlator.prepare_correlated_input("consumer", ["scorer_1", "scorer_2"], 3)

        merged = backend.read_target("consumer", "data.json")
        assert [r["source_guid"] for r in merged] == ["sg-001"]
        assert {"scorer_1_aaa", "scorer_2_bbb"} <= set(merged[0]["lineage"])
