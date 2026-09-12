"""Docs scanning skips directories that cannot hold a user's workflow."""

from __future__ import annotations

from pathlib import Path

from agent_actions.tooling.docs import scanner


def _make_venv(root: Path, name: str = ".venv") -> Path:
    venv = root / name
    venv.mkdir()
    (venv / "pyvenv.cfg").write_text("home = /usr/bin\n")
    return venv


def _workflow(base: Path, name: str) -> Path:
    cfg = base / name / "agent_config"
    cfg.mkdir(parents=True)
    (cfg / f"{name}.yml").write_text(f"name: {name}\n")
    return cfg


class TestScanWorkflowsSkipsNonProjectDirs:
    def test_vendored_workflow_in_a_virtualenv_is_not_documented(self, tmp_path):
        """A dependency shipping an example project is not the user's workflow."""
        venv = _make_venv(tmp_path)
        _workflow(venv / "lib", "vendored_example")
        _workflow(tmp_path / "agent_workflow", "real_wf")

        found = scanner.scan_workflows(tmp_path)

        assert "real_wf" in found
        assert "vendored_example" not in found

    def test_virtualenv_under_an_arbitrary_name_is_skipped(self, tmp_path):
        venv = _make_venv(tmp_path, name=".project_env")
        _workflow(venv / "lib", "vendored_example")

        assert scanner.scan_workflows(tmp_path) == {}

    def test_readmes_skip_vendored_workflows(self, tmp_path):
        venv = _make_venv(tmp_path)
        _workflow(venv / "lib", "vendored_example")
        (venv / "lib" / "vendored_example" / "README.md").write_text("dependency readme")
        _workflow(tmp_path / "agent_workflow", "real_wf")
        (tmp_path / "agent_workflow" / "real_wf" / "README.md").write_text("real readme")

        readmes = scanner.scan_readmes(tmp_path)

        assert readmes["real_wf"].content == "real readme"
        assert "vendored_example" not in readmes


class TestScanRunsSkipsNonProjectDirs:
    def test_agent_io_inside_a_virtualenv_is_not_a_project_run(self, tmp_path):
        venv = _make_venv(tmp_path)
        (venv / "lib" / "vendored" / "agent_io" / "logs").mkdir(parents=True)
        (tmp_path / "agent_workflow" / "real_wf" / "agent_io" / "logs").mkdir(parents=True)
        _workflow(tmp_path / "agent_workflow", "real_wf")

        runs = scanner.scan_runs(tmp_path)

        assert "real_wf" in runs
        assert "vendored" not in runs


class TestProjectDirsAreStillFound:
    def test_nested_project_workflows_are_still_discovered(self, tmp_path):
        """Pruning must not narrow discovery within the user's own tree."""
        _workflow(tmp_path / "agent_workflow", "wf_a")
        _workflow(tmp_path / "nested" / "deeply" / "agent_workflow", "wf_b")

        found = scanner.scan_workflows(tmp_path)

        assert set(found) == {"wf_a", "wf_b"}
