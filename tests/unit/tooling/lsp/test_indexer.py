"""Tests for LSP indexer — find_all_project_roots()."""

from pathlib import Path

from agent_actions.tooling.lsp.indexer import find_all_project_roots


class TestFindAllProjectRoots:
    """Tests for find_all_project_roots()."""

    def test_no_workspace_folders(self):
        """Empty input yields no roots."""
        assert find_all_project_roots([]) == []

    def test_single_project_upward(self, tmp_path: Path):
        """Discovers project root by walking upward from a subfolder."""
        (tmp_path / "agent_actions.yml").touch()
        sub = tmp_path / "agent_workflow" / "wf1"
        sub.mkdir(parents=True)
        roots = find_all_project_roots([sub])
        assert roots == [tmp_path]

    def test_single_project_downward(self, tmp_path: Path):
        """Discovers a project root by globbing downward."""
        proj = tmp_path / "project_a"
        proj.mkdir()
        (proj / "agent_actions.yml").touch()
        roots = find_all_project_roots([tmp_path])
        assert roots == [proj]

    def test_two_projects(self, tmp_path: Path):
        """Discovers multiple disjoint projects."""
        proj_a = tmp_path / "project_a"
        proj_b = tmp_path / "project_b"
        proj_a.mkdir()
        proj_b.mkdir()
        (proj_a / "agent_actions.yml").touch()
        (proj_b / "agent_actions.yml").touch()
        roots = find_all_project_roots([tmp_path])
        assert set(roots) == {proj_a, proj_b}
        assert len(roots) == 2

    def test_deduplication(self, tmp_path: Path):
        """Same root discovered from multiple workspace folders is deduplicated."""
        (tmp_path / "agent_actions.yml").touch()
        sub_a = tmp_path / "a"
        sub_b = tmp_path / "b"
        sub_a.mkdir()
        sub_b.mkdir()
        roots = find_all_project_roots([sub_a, sub_b])
        assert roots == [tmp_path]

    def test_nested_projects(self, tmp_path: Path):
        """Nested projects are both discovered (upward finds outer, glob finds inner)."""
        (tmp_path / "agent_actions.yml").touch()
        inner = tmp_path / "sub" / "inner"
        inner.mkdir(parents=True)
        (inner / "agent_actions.yml").touch()
        roots = find_all_project_roots([tmp_path])
        # depth=0 (tmp_path itself) is covered by the upward walk
        assert set(roots) == {tmp_path, inner}
        assert len(roots) == 2

    def test_no_projects_found(self, tmp_path: Path):
        """No agent_actions.yml anywhere yields empty list."""
        sub = tmp_path / "empty"
        sub.mkdir()
        roots = find_all_project_roots([sub])
        assert roots == []

    def test_results_are_sorted(self, tmp_path: Path):
        """Returned roots are sorted for deterministic ordering."""
        proj_z = tmp_path / "z_proj"
        proj_a = tmp_path / "a_proj"
        proj_z.mkdir()
        proj_a.mkdir()
        (proj_z / "agent_actions.yml").touch()
        (proj_a / "agent_actions.yml").touch()
        roots = find_all_project_roots([tmp_path])
        assert roots == sorted(roots)
