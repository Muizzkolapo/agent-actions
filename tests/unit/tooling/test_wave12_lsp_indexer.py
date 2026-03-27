"""Wave 12 T2-6 regression: find_project_root returns None when no marker found."""

from __future__ import annotations

from agent_actions.tooling.lsp.indexer import find_project_root


class TestFindProjectRootReturnsNone:
    """T2-6: find_project_root must return None when no agent_actions.yml is found."""

    def test_returns_none_for_path_without_marker(self, tmp_path):
        """A directory with no agent_actions.yml (anywhere) must yield None."""
        result = find_project_root(tmp_path)
        assert result is None

    def test_returns_none_for_nested_path_without_marker(self, tmp_path):
        """Deeply nested path with no marker must return None."""
        deep = tmp_path / "a" / "b" / "c"
        deep.mkdir(parents=True)
        result = find_project_root(deep)
        assert result is None

    def test_returns_path_when_marker_exists_in_parent(self, tmp_path):
        """When agent_actions.yml exists in an ancestor, it must be returned (not None)."""
        marker = tmp_path / "agent_actions.yml"
        marker.write_text("name: test_project\n")
        child_dir = tmp_path / "subdir"
        child_dir.mkdir()

        result = find_project_root(child_dir)
        assert result is not None
        assert (result / "agent_actions.yml").exists()

    def test_returns_path_when_marker_exists_in_child(self, tmp_path):
        """When agent_actions.yml exists in a subdirectory (depth=1), LSP downward search finds it."""
        child = tmp_path / "project"
        child.mkdir()
        marker = child / "agent_actions.yml"
        marker.write_text("name: test\n")

        result = find_project_root(tmp_path)
        assert result is not None
        assert result == child

    def test_returns_path_when_marker_exists_at_depth2(self, tmp_path):
        """LSP downward glob must find agent_actions.yml at depth=2."""
        nested = tmp_path / "workspace" / "project"
        nested.mkdir(parents=True)
        (nested / "agent_actions.yml").write_text("name: deep\n")

        result = find_project_root(tmp_path)
        assert result is not None
        assert result == nested

    def test_returns_path_when_marker_exists_at_depth3(self, tmp_path):
        """LSP downward glob must find agent_actions.yml at depth=3."""
        deep = tmp_path / "a" / "b" / "project"
        deep.mkdir(parents=True)
        (deep / "agent_actions.yml").write_text("name: deepest\n")

        result = find_project_root(tmp_path)
        assert result is not None
        assert result == deep
