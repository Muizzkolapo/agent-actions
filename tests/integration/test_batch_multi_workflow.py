"""Regression tests for the batch CLI in multi-workflow projects.

Pins three behaviors:

1. `batch status` / `batch retrieve` expose `-a/--agent` and `--action`.
2. The CLI resolves the registry from the per-workflow SQLite DB
   (`agent_workflow/<wf>/agent_io/store/<wf>.db`) and looks it up by the
   real action name (`batch_registry:{action_name}`).
3. Single-workflow projects still work without flags.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from agent_actions.cli.main import cli
from agent_actions.llm.batch.core.batch_constants import BatchStatus
from agent_actions.llm.batch.core.batch_models import BatchJobEntry
from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager
from agent_actions.storage import get_storage_backend


def _seed_workflow(project_root: Path, wf: str, action: str, batch_id: str) -> None:
    wf_root = project_root / "agent_workflow" / wf
    (wf_root / "agent_io" / "store").mkdir(parents=True, exist_ok=True)
    (wf_root / "agent_config").mkdir(parents=True, exist_ok=True)
    (wf_root / f"{wf}.yml").write_text(f"name: {wf}\n")
    (wf_root / "agent_config" / f"{wf}.yml").write_text(f"name: {wf}\n")

    backend = get_storage_backend(workflow_path=str(wf_root), workflow_name=wf)
    backend.initialize()
    registry = BatchRegistryManager(storage_backend=backend, action_name=action)
    registry.save_batch_job(
        file_name=f"{action}_chunk_0.jsonl",
        entry=BatchJobEntry(
            batch_id=batch_id,
            status=BatchStatus.COMPLETED,
            timestamp="2026-06-28T00:00:00Z",
            provider="ollama",
            file_name=f"{action}_chunk_0.jsonl",
        ),
    )


@pytest.fixture
def multi_workflow_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Two workflows under one project, each seeded with a batch_registry entry."""
    (tmp_path / "agent_actions.yml").write_text("name: multi\n")
    _seed_workflow(tmp_path, "alpha", "alpha_action", "fake_alpha_batch")
    _seed_workflow(tmp_path, "beta", "beta_action", "fake_beta_batch")
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def single_workflow_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """One workflow whose action name differs from its workflow name."""
    (tmp_path / "agent_actions.yml").write_text("name: solo\n")
    _seed_workflow(tmp_path, "solo", "solo_action", "fake_solo_batch")
    monkeypatch.chdir(tmp_path)
    return tmp_path


class TestFlagSurface:
    def test_status_advertises_agent_and_action_flags(self):
        result = CliRunner().invoke(cli, ["batch", "status", "--help"])
        assert "--agent" in result.output, "batch status must accept -a/--agent"
        assert "--action" in result.output, "batch status must accept --action"

    def test_retrieve_advertises_agent_and_action_flags(self):
        result = CliRunner().invoke(cli, ["batch", "retrieve", "--help"])
        assert "--agent" in result.output, "batch retrieve must accept -a/--agent"
        assert "--action" in result.output, "batch retrieve must accept --action"


@pytest.fixture
def captured_check_status(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """Capture (action_name, output_directory) the CLI passes to the service."""
    calls: list[dict] = []

    def fake_check_status(self, batch_id, output_directory, action_name):
        calls.append(
            {
                "batch_id": batch_id,
                "output_directory": output_directory,
                "action_name": action_name,
            }
        )
        return "COMPLETED"

    from agent_actions.llm.batch.services.submission import BatchSubmissionService

    monkeypatch.setattr(BatchSubmissionService, "check_status", fake_check_status)
    return calls


class TestWorkflowScopedResolution:
    def test_status_routes_to_alpha_workflow_and_action(
        self, multi_workflow_project, captured_check_status
    ):
        result = CliRunner().invoke(
            cli,
            [
                "batch",
                "status",
                "-a",
                "alpha",
                "--action",
                "alpha_action",
                "--batch-id",
                "fake_alpha_batch",
            ],
        )
        assert result.exit_code == 0, f"non-zero exit; output: {result.output}"
        assert len(captured_check_status) == 1
        call = captured_check_status[0]
        assert call["action_name"] == "alpha_action"
        assert Path(call["output_directory"]).name == "alpha"

    def test_status_routes_to_beta_workflow_and_action(
        self, multi_workflow_project, captured_check_status
    ):
        result = CliRunner().invoke(
            cli,
            [
                "batch",
                "status",
                "-a",
                "beta",
                "--action",
                "beta_action",
                "--batch-id",
                "fake_beta_batch",
            ],
        )
        assert result.exit_code == 0, f"non-zero exit; output: {result.output}"
        call = captured_check_status[0]
        assert call["action_name"] == "beta_action"
        assert Path(call["output_directory"]).name == "beta"

    def test_ambiguous_workflow_raises_usage_error(self, multi_workflow_project):
        result = CliRunner().invoke(
            cli, ["batch", "status", "--batch-id", "irrelevant"]
        )
        assert result.exit_code != 0
        assert "alpha" in result.output and "beta" in result.output, (
            "error must list available workflows"
        )


class TestActionNameRouting:
    def test_single_workflow_resolves_action_distinct_from_workflow_name(
        self, single_workflow_project, captured_check_status
    ):
        result = CliRunner().invoke(
            cli,
            ["batch", "status", "--action", "solo_action", "--batch-id", "fake_solo_batch"],
        )
        assert result.exit_code == 0, f"non-zero exit; output: {result.output}"
        assert captured_check_status[0]["action_name"] == "solo_action", (
            "CLI must pass --action verbatim, NOT workflow_name"
        )
