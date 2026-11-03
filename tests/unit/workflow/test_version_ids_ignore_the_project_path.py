"""Version correlation ids depend on the workflow, not where its project sits (1605)."""

import logging
from types import SimpleNamespace

from agent_actions.workflow.coordinator import AgentWorkflow
from agent_actions.workflow.managers.loop import VersionOutputCorrelator


def _session_id(agent_name: str, config_path: str) -> str:
    workflow = SimpleNamespace(
        agent_name=agent_name,
        config=SimpleNamespace(paths=SimpleNamespace(constructor_path=config_path)),
    )
    return AgentWorkflow._generate_workflow_session_id(workflow)


def test_the_session_id_is_the_same_from_any_path():
    here = _session_id("review", "/home/a/project/agent_config/review.yml")
    there = _session_id("review", "/mnt/worktree/project/agent_config/review.yml")
    assert here == there


def test_two_workflows_keep_different_session_ids():
    path = "/home/a/project/agent_config/x.yml"
    assert _session_id("review", path) != _session_id("triage", path)


def _row(version: str, guid: str, correlation: str) -> dict:
    return {
        "source_guid": guid,
        "version_correlation_id": correlation,
        "content": {version: {"vote": "yes"}},
        "_source_file": "items.json",
    }


def _correlate(caplog, outputs: dict[str, list[dict]]) -> list[dict]:
    correlator = VersionOutputCorrelator(agent_folder=None)
    correlator._load_version_outputs = lambda sources, lost: (outputs, {"items.json"})
    correlator._forget_files_no_version_holds = lambda *args: None
    with caplog.at_level(logging.WARNING):
        return correlator.prepare_correlated_input("merge", ["vote_1", "vote_2"], 0)["items.json"]


def test_versions_merged_apart_are_named_with_the_rerun_that_joins_them(caplog):
    merged = _correlate(
        caplog,
        {
            "vote_1": [_row("vote_1", "g1", "corr_old")],
            "vote_2": [_row("vote_2", "g1", "corr_new")],
        },
    )

    assert len(merged) == 2
    assert "versions of 1 source record(s) carry different correlation ids" in caplog.text
    assert "g1" in caplog.text
    assert "agac run --rerun vote" in caplog.text


def test_a_version_that_filtered_the_record_is_not_named(caplog):
    merged = _correlate(
        caplog,
        {
            "vote_1": [_row("vote_1", "g1", "corr_a"), _row("vote_1", "g2", "corr_b")],
            "vote_2": [_row("vote_2", "g1", "corr_a")],
        },
    )

    assert len(merged) == 2
    assert "carry different correlation ids" not in caplog.text
