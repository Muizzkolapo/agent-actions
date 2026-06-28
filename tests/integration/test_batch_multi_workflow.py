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
from tests._support.batch_workflows import seed_workflow


@pytest.fixture
def multi_workflow_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Two workflows under one project, each seeded with a batch_registry entry."""
    (tmp_path / "agent_actions.yml").write_text("name: multi\n")
    seed_workflow(tmp_path, "alpha", "alpha_action", "fake_alpha_batch")
    seed_workflow(tmp_path, "beta", "beta_action", "fake_beta_batch")
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def single_workflow_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """One workflow whose action name differs from its workflow name."""
    (tmp_path / "agent_actions.yml").write_text("name: solo\n")
    seed_workflow(tmp_path, "solo", "solo_action", "fake_solo_batch")
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
        result = CliRunner().invoke(cli, ["batch", "status", "--batch-id", "irrelevant"])
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


class TestHardening:
    def test_empty_action_string_rejected(self, single_workflow_project):
        result = CliRunner().invoke(cli, ["batch", "status", "--action", "", "--batch-id", "x"])
        assert result.exit_code != 0
        assert "--action must not be empty" in result.output

    def test_status_refuses_to_silently_create_db(self, tmp_path, monkeypatch):
        """Read-only commands must not mutate the working tree when there's no
        batch state yet."""
        (tmp_path / "agent_actions.yml").write_text("name: empty\n")
        wf_root = tmp_path / "agent_workflow" / "empty"
        (wf_root / "agent_config").mkdir(parents=True)
        (wf_root / "agent_config" / "empty.yml").write_text("name: empty\n")
        monkeypatch.chdir(tmp_path)

        result = CliRunner().invoke(cli, ["batch", "status", "--batch-id", "x"])
        assert result.exit_code != 0
        assert "no batch state yet" in result.output.lower()
        assert not (wf_root / "agent_io" / "store" / "empty.db").exists()

    def test_symlink_workflow_is_ignored(self, tmp_path, monkeypatch):
        """A symlink under agent_workflow/ must not be treated as a workflow."""
        (tmp_path / "agent_actions.yml").write_text("name: solo\n")
        seed_workflow(tmp_path, "real", "real_action", "fake_real_batch")
        external = tmp_path.parent / f"escape-{tmp_path.name}"
        external.mkdir()
        (external / "agent_config").mkdir()
        try:
            (tmp_path / "agent_workflow" / "sneaky").symlink_to(external)
            monkeypatch.chdir(tmp_path)

            result = CliRunner().invoke(cli, ["batch", "status", "-a", "sneaky", "--batch-id", "x"])
            assert result.exit_code != 0
            assert "not found" in result.output.lower()
        finally:
            import shutil

            shutil.rmtree(external, ignore_errors=True)

    def test_batch_id_routes_to_owning_action_when_action_omitted(
        self, tmp_path, monkeypatch, captured_check_status
    ):
        """When --action is omitted but --batch-id is provided, auto-select
        the action whose registry actually contains that batch_id."""
        from agent_actions.llm.batch.core.batch_constants import BatchStatus
        from agent_actions.llm.batch.core.batch_models import BatchJobEntry
        from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager
        from agent_actions.storage import get_storage_backend

        (tmp_path / "agent_actions.yml").write_text("name: multi_action\n")
        seed_workflow(tmp_path, "multi", "action_a", "fake_a_batch")

        wf_root = tmp_path / "agent_workflow" / "multi"
        backend = get_storage_backend(workflow_path=str(wf_root), workflow_name="multi")
        backend.initialize()
        BatchRegistryManager(storage_backend=backend, action_name="action_b").save_batch_job(
            file_name="action_b_chunk_0.jsonl",
            entry=BatchJobEntry(
                batch_id="fake_b_batch",
                status=BatchStatus.COMPLETED,
                timestamp="2026-06-28T00:00:00Z",
                provider="ollama",
                file_name="action_b_chunk_0.jsonl",
            ),
        )
        monkeypatch.chdir(tmp_path)

        result = CliRunner().invoke(cli, ["batch", "status", "--batch-id", "fake_b_batch"])
        assert result.exit_code == 0, f"output: {result.output}"
        assert captured_check_status[0]["action_name"] == "action_b", (
            "CLI must auto-route batch_id to the action that owns it"
        )
