"""`agac batch status` and `agac batch retrieve` find the workflow, its store and the
action a batch belongs to, or say why they cannot, before asking the provider anything.
"""

from __future__ import annotations

import os
from pathlib import Path

import click
import pytest
from click.testing import CliRunner

from agent_actions.llm.batch import batch_cli
from agent_actions.llm.batch.batch_cli import _list_workflows, _resolve_workflow, batch
from agent_actions.llm.batch.core.batch_models import BatchJobEntry
from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager
from agent_actions.storage import get_storage_backend


def _workflow(root: Path, name: str) -> Path:
    folder = root / "agent_workflow" / name
    (folder / "agent_config").mkdir(parents=True)
    return folder


def _store(workflow_root: Path, name: str, jobs: dict[str, list[str]]) -> None:
    (workflow_root / "agent_io" / "store").mkdir(parents=True, exist_ok=True)
    backend = get_storage_backend(
        workflow_path=str(workflow_root), workflow_name=name, backend_type="sqlite"
    )
    backend.initialize()
    try:
        for action, batch_ids in jobs.items():
            registry = BatchRegistryManager(storage_backend=backend, action_name=action)
            for i, batch_id in enumerate(batch_ids):
                registry.save_batch_job(
                    f"part_{i}.json",
                    BatchJobEntry(
                        batch_id=batch_id,
                        status="submitted",
                        timestamp="2026-11-01T09:00:00Z",
                        provider="openai",
                        file_name=f"part_{i}.json",
                    ),
                )
    finally:
        backend.close()


@pytest.fixture
def project(tmp_path: Path, monkeypatch) -> Path:
    (tmp_path / "agent_actions.yml").write_text("{}\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(batch_cli.LoggerFactory, "initialize", lambda **_: None)
    return tmp_path


class _Submission:
    asked: list[tuple] = []

    def __init__(self, **_):
        pass

    def check_status(self, batch_id, output_directory, action_name):
        _Submission.asked.append((batch_id, output_directory, action_name))
        return "in_progress"


class _Retrieval:
    built: list[dict] = []

    def __init__(self, **kwargs):
        _Retrieval.built.append(kwargs)

    def retrieve_results(self, batch_id, output_directory):
        return str(Path(output_directory) / f"{batch_id}_results.jsonl")


@pytest.fixture
def services(monkeypatch):
    _Submission.asked = []
    _Retrieval.built = []
    monkeypatch.setattr(batch_cli, "BatchSubmissionService", _Submission)
    monkeypatch.setattr(batch_cli, "BatchRetrievalService", _Retrieval)


def _invoke(*args: str):
    return CliRunner().invoke(batch, list(args))


def test_only_real_workflow_folders_with_an_agent_config_are_listed(tmp_path):
    _workflow(tmp_path, "zeta")
    _workflow(tmp_path, "alpha")
    (tmp_path / "agent_workflow" / ".hidden" / "agent_config").mkdir(parents=True)
    (tmp_path / "agent_workflow" / "no_config").mkdir()
    (tmp_path / "agent_workflow" / "stray.txt").write_text("")
    outside = tmp_path / "outside"
    (outside / "agent_config").mkdir(parents=True)
    os.symlink(outside, tmp_path / "agent_workflow" / "linked")
    linked_config = _workflow(tmp_path, "linked_config").joinpath("agent_config")
    linked_config.rmdir()
    os.symlink(outside / "agent_config", linked_config)

    assert _list_workflows(tmp_path) == ["alpha", "zeta"]


def test_a_symlinked_workflow_folder_lists_nothing(tmp_path):
    real = tmp_path / "real"
    _workflow(real, "alpha")
    project = tmp_path / "project"
    project.mkdir()
    os.symlink(real / "agent_workflow", project / "agent_workflow")

    assert _list_workflows(project) == []


def test_a_project_without_workflows_points_at_init(tmp_path):
    with pytest.raises(click.UsageError, match="Run `agac init`"):
        _resolve_workflow(tmp_path, None)


def test_the_only_workflow_is_chosen_without_a_name(tmp_path):
    _workflow(tmp_path, "pipeline")

    assert _resolve_workflow(tmp_path, None) == (
        "pipeline",
        tmp_path / "agent_workflow" / "pipeline",
    )


def test_several_workflows_need_a_name_and_are_listed(tmp_path):
    _workflow(tmp_path, "one")
    _workflow(tmp_path, "two")

    with pytest.raises(click.UsageError, match="pass -a <workflow_name>. Available: one, two"):
        _resolve_workflow(tmp_path, None)


def test_an_unknown_workflow_name_lists_the_known_ones(tmp_path):
    _workflow(tmp_path, "one")

    with pytest.raises(click.UsageError, match="Workflow 'typo' not found. Available: one"):
        _resolve_workflow(tmp_path, "typo")


@pytest.mark.parametrize("command", ["status", "retrieve"])
def test_a_batch_id_is_required(project, command):
    result = _invoke(command)

    assert result.exit_code == 2
    assert "--batch-id is required." in result.output


@pytest.mark.parametrize("command", ["status", "retrieve"])
def test_a_workflow_that_never_ran_has_no_batch_state_and_none_is_created(project, command):
    workflow_root = _workflow(project, "pipeline")

    result = _invoke(command, "--batch-id", "b1")

    assert result.exit_code == 2
    assert "Workflow 'pipeline' has no batch state yet." in result.output
    assert not (workflow_root / "agent_io" / "store").exists()


def test_status_asks_the_action_that_owns_the_batch(project, services):
    workflow_root = _workflow(project, "pipeline")
    _store(workflow_root, "pipeline", {"extract": ["b1"], "summarize": ["b2"]})

    result = _invoke("status", "--batch-id", "b2")

    assert result.exit_code == 0, result.output
    assert result.output.endswith("Batch job status: in_progress\n")
    assert _Submission.asked == [("b2", str(workflow_root), "summarize")]


def test_status_with_an_explicit_action_uses_it(project, services):
    workflow_root = _workflow(project, "pipeline")
    _store(workflow_root, "pipeline", {"extract": ["b1"]})

    result = _invoke("status", "--batch-id", "elsewhere", "-w", "pipeline", "-A", "revived")

    assert result.exit_code == 0, result.output
    assert _Submission.asked == [("elsewhere", str(workflow_root), "revived")]


def test_retrieve_writes_under_the_actions_target_folder_and_prints_the_path(project, services):
    workflow_root = _workflow(project, "pipeline")
    _store(workflow_root, "pipeline", {"extract": ["b1"]})

    result = _invoke("retrieve", "--batch-id", "b1")

    target = workflow_root / "agent_io" / "target" / "extract"
    assert result.exit_code == 0, result.output
    assert f"{target / 'b1_results.jsonl'}\n" in result.output
    assert target.is_dir()
    assert _Retrieval.built[0]["action_name"] == "extract"


def test_retrieve_from_a_workflow_that_does_not_load_warns_it_writes_raw_answers(
    project, services
):
    workflow_root = _workflow(project, "pipeline")
    _store(workflow_root, "pipeline", {"extract": ["b1"]})

    result = CliRunner().invoke(batch, ["retrieve", "--batch-id", "b1"])

    assert result.exit_code == 0, result.stderr
    assert "Warning: workflow 'pipeline' did not load" in result.stderr
    assert "raw answers of the provider" in result.stderr
    assert _Retrieval.built[0]["agent_config"] is None


def test_retrieve_for_an_action_the_workflow_lacks_warns_it_writes_raw_answers(
    project, services, monkeypatch
):
    workflow_root = _workflow(project, "pipeline")
    _store(workflow_root, "pipeline", {"gone": ["b1"]})

    class _Loaded:
        action_configs = {"extract": {"model_vendor": "openai"}}

    monkeypatch.setattr(
        "agent_actions.cli.workflow_loader.load_workflow", lambda *a, **k: _Loaded()
    )

    result = CliRunner().invoke(batch, ["retrieve", "--batch-id", "b1"])

    assert result.exit_code == 0, result.stderr
    assert "Warning: workflow 'pipeline' has no action 'gone'." in result.stderr
    assert _Retrieval.built[0]["agent_config"] is None


def test_retrieve_hands_the_service_the_config_of_the_action(project, services, monkeypatch):
    workflow_root = _workflow(project, "pipeline")
    _store(workflow_root, "pipeline", {"extract": ["b1"]})
    config = {"model_vendor": "openai", "json_mode": False}

    class _Loaded:
        action_configs = {"extract": config}

    monkeypatch.setattr(
        "agent_actions.cli.workflow_loader.load_workflow", lambda *a, **k: _Loaded()
    )

    result = CliRunner().invoke(batch, ["retrieve", "--batch-id", "b1"])

    assert result.exit_code == 0, result.stderr
    assert "Warning" not in result.stderr
    assert _Retrieval.built[0]["agent_config"] is config
