"""Regression test for C-7: WorkspaceIndex.scan_workspace() sorted() glob for determinism."""

from __future__ import annotations

from pathlib import Path

import yaml

from agent_actions.workflow.workspace_index import WorkspaceIndex


def _make_workflow(workflows_root: Path, workflow_name: str, yml_files: dict[str, dict]) -> None:
    """Create a workflow dir with agent_config/*.yml files."""
    wf_dir = workflows_root / workflow_name
    cfg_dir = wf_dir / "agent_config"
    cfg_dir.mkdir(parents=True)
    for filename, content in yml_files.items():
        (cfg_dir / filename).write_text(yaml.dump(content))


class TestWorkspaceIndexDeterminism:
    """C-7: sorted() on glob results guarantees deterministic config selection."""

    def test_single_yml_selected(self, tmp_path):
        """Sanity: a single .yml file is loaded without error."""
        _make_workflow(tmp_path, "wf_a", {"wf_a.yml": {"actions": []}})
        idx = WorkspaceIndex(tmp_path)
        idx.scan_workspace()
        assert "wf_a" in idx.dependency_graph

    def test_multiple_yml_files_selects_first_alphabetically(self, tmp_path):
        """When no <workflow>.yml exists, sorted() picks the first name alphabetically."""
        _make_workflow(
            tmp_path,
            "my_workflow",
            {
                "zzz_last.yml": {"actions": []},
                "aaa_first.yml": {"actions": []},
                "mmm_middle.yml": {"actions": []},
            },
        )
        idx = WorkspaceIndex(tmp_path)
        idx.scan_workspace()
        # "aaa_first" comes first alphabetically — that name must be in the graph
        assert "aaa_first" in idx.dependency_graph

    def test_multiple_yml_deterministic_across_repeated_scans(self, tmp_path):
        """Repeated scans must select the same config file (determinism, not luck)."""
        _make_workflow(
            tmp_path,
            "my_workflow",
            {
                "zzz_last.yml": {"actions": []},
                "aaa_first.yml": {"actions": []},
            },
        )
        results = set()
        for _ in range(5):
            idx = WorkspaceIndex(tmp_path)
            idx.scan_workspace()
            # The key added to dependency_graph is the stem of the selected file
            results.update(idx.dependency_graph.keys())

        # All runs must agree on the same file stem
        assert len(results) == 1, f"Non-deterministic selection across runs: {results}"

    def test_named_yml_preferred_over_glob_fallback(self, tmp_path):
        """If <workflow_name>.yml exists it is used directly (no glob needed)."""
        _make_workflow(
            tmp_path,
            "my_workflow",
            {
                "my_workflow.yml": {"actions": []},
                "aaa_other.yml": {"actions": []},
            },
        )
        idx = WorkspaceIndex(tmp_path)
        idx.scan_workspace()
        # Named file is used; workflow_dir.name is 'my_workflow'
        assert "my_workflow" in idx.dependency_graph
