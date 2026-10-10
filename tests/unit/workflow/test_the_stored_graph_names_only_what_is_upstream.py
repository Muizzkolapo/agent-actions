"""The run stores, as each action's upstream, the actions above it through `dependencies`.

Two readers take the stored graph as exactly that: the storage walk subtracts the
records a guard filtered there, and delta storage rejoins a row with their
namespaces. Storing every action of every earlier level instead made a filter beside
an action remove its records, and a peer's namespaces were rejoined onto its rows.
"""

import json
from unittest.mock import MagicMock

import pytest

from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
from agent_actions.workflow.coordinator import AgentWorkflow
from agent_actions.workflow.parallel.action_executor import ActionLevelOrchestrator


def _version(base, *dependencies):
    return {
        "dependencies": list(dependencies),
        "is_versioned_agent": True,
        "version_base_name": base,
    }


# Levels: [flatten, other], [vote_1, vote_2, side], [merge], [final].
CONFIGS = {
    "flatten": {"dependencies": []},
    "other": {"dependencies": []},
    "vote_1": _version("vote", "flatten"),
    "vote_2": _version("vote", "flatten"),
    "side": {"dependencies": ["flatten"]},
    "merge": {"dependencies": ["vote"]},
    "final": {"dependencies": ["merge"]},
}


@pytest.fixture
def stored(tmp_path):
    order = list(CONFIGS)
    orchestrator = ActionLevelOrchestrator(order, CONFIGS)
    backend = SQLiteBackend(str(tmp_path / "store.db"), "probe")
    backend.initialize()
    workflow = object.__new__(AgentWorkflow)
    workflow.storage_backend = backend
    workflow.metadata = MagicMock(execution_order=order)
    workflow.services = MagicMock()
    workflow.services.core.action_level_orchestrator = orchestrator
    try:
        workflow._persist_execution_metadata(orchestrator.compute_execution_levels())
        yield json.loads(backend.load_metadata("dependency_graph"))
    finally:
        backend.close()


def test_a_start_node_has_nothing_upstream_of_it(stored):
    assert stored["flatten"] == []
    assert stored["other"] == []


def test_an_action_beside_another_is_not_upstream_of_what_reads_that_one(stored):
    assert stored["side"] == ["flatten"]
    assert "side" not in stored["merge"]
    assert "other" not in stored["final"]


def test_a_version_base_stands_for_every_version(stored):
    assert stored["merge"] == ["flatten", "vote_1", "vote_2"]


def test_what_is_upstream_is_listed_in_the_order_it_runs(stored):
    """Delta storage takes the first of several rows stored whole as the boundary."""
    assert stored["final"] == ["flatten", "vote_1", "vote_2", "merge"]
