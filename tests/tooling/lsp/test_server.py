"""Tests for LSP server — _index_for_file routing, did_save, and integration tests."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from lsprotocol import types as lsp

from agent_actions.tooling.lsp.indexer import build_index
from agent_actions.tooling.lsp.models import ActionMetadata, Location, ProjectIndex
from agent_actions.tooling.lsp.server import (
    _build_watchers_for_project,
    _index_for_file,
    _register_file_watchers,
    _republish_diagnostics_for_projects,
    did_change_watched_files,
    did_save,
    initialized,
    server,
)


def _reset_server():
    """Reset server state to clean defaults."""
    server.project_indexes.clear()
    server.index = None
    server.project_root = None


def _make_project(root: Path, actions: dict[str, int] | None = None) -> ProjectIndex:
    """Create a minimal project structure on disk and return its index.

    Args:
        root: Project root directory.
        actions: Optional mapping of action_name → line_number to inject into
                 the index's file_actions for a dummy workflow file.
    """
    root.mkdir(parents=True, exist_ok=True)
    (root / "agent_actions.yml").touch()
    idx = ProjectIndex(root=root)
    if actions:
        wf_dir = root / "agent_workflow" / "wf" / "agent_config"
        wf_dir.mkdir(parents=True, exist_ok=True)
        yml = wf_dir / "workflow.yml"
        yml.touch()
        idx.file_actions[yml] = {}
        for name, line in actions.items():
            loc = Location(file_path=yml, line=line, column=0)
            idx.actions[name] = loc
            idx.file_actions[yml][name] = ActionMetadata(name=name, location=loc)
    return idx


# ---------------------------------------------------------------------------
# _index_for_file routing
# ---------------------------------------------------------------------------


class TestIndexForFile:
    """Tests for _index_for_file() routing."""

    def setup_method(self):
        _reset_server()

    def teardown_method(self):
        _reset_server()

    def test_single_project(self, tmp_path: Path):
        """File inside the only project returns that project's index."""
        root = tmp_path / "proj"
        root.mkdir()
        idx = ProjectIndex(root=root)
        server.project_indexes[root] = idx

        file_path = root / "agent_workflow" / "wf" / "agent_config" / "test.yml"
        file_path.parent.mkdir(parents=True)
        file_path.touch()

        assert _index_for_file(file_path) is idx

    def test_nested_roots_deepest_wins(self, tmp_path: Path):
        """When projects are nested, the deepest matching root wins."""
        outer = tmp_path / "outer"
        inner = outer / "sub" / "inner"
        outer.mkdir(parents=True)
        inner.mkdir(parents=True)

        outer_idx = ProjectIndex(root=outer)
        inner_idx = ProjectIndex(root=inner)
        server.project_indexes[outer] = outer_idx
        server.project_indexes[inner] = inner_idx

        file_in_inner = inner / "workflow.yml"
        file_in_inner.touch()
        assert _index_for_file(file_in_inner) is inner_idx

        file_in_outer = outer / "workflow.yml"
        file_in_outer.touch()
        assert _index_for_file(file_in_outer) is outer_idx

    def test_file_outside_all_projects_returns_none(self, tmp_path: Path):
        """File outside all projects returns None (no cross-project leakage)."""
        root = tmp_path / "proj"
        root.mkdir()
        idx = ProjectIndex(root=root)
        server.project_indexes[root] = idx
        server.index = idx  # backward-compat alias set, but should NOT leak

        outside = tmp_path / "unrelated" / "file.yml"
        outside.parent.mkdir(parents=True)
        outside.touch()

        assert _index_for_file(outside) is None

    def test_no_projects_returns_none(self, tmp_path: Path):
        """No projects indexed returns None."""
        file_path = tmp_path / "file.yml"
        file_path.touch()
        assert _index_for_file(file_path) is None

    def test_two_disjoint_projects(self, tmp_path: Path):
        """Files route to their respective project indexes."""
        proj_a = tmp_path / "proj_a"
        proj_b = tmp_path / "proj_b"
        proj_a.mkdir()
        proj_b.mkdir()

        idx_a = ProjectIndex(root=proj_a)
        idx_b = ProjectIndex(root=proj_b)
        server.project_indexes[proj_a] = idx_a
        server.project_indexes[proj_b] = idx_b

        file_a = proj_a / "workflow.yml"
        file_b = proj_b / "workflow.yml"
        file_a.touch()
        file_b.touch()

        assert _index_for_file(file_a) is idx_a
        assert _index_for_file(file_b) is idx_b


# ---------------------------------------------------------------------------
# did_save
# ---------------------------------------------------------------------------


class TestDidSave:
    """Tests for did_save() handler."""

    def setup_method(self):
        _reset_server()

    def teardown_method(self):
        _reset_server()

    @patch("agent_actions.tooling.lsp.server._publish_diagnostics")
    @patch("agent_actions.tooling.lsp.server.build_index")
    def test_new_project_registration(self, mock_build_index, mock_diag, tmp_path: Path):
        """Saving a new agent_actions.yml registers it as a new project."""
        new_root = tmp_path / "new_proj"
        new_root.mkdir()
        yml = new_root / "agent_actions.yml"
        yml.touch()

        new_idx = ProjectIndex(root=new_root)
        mock_build_index.return_value = new_idx

        params = MagicMock(spec=lsp.DidSaveTextDocumentParams)
        params.text_document.uri = yml.as_uri()

        did_save(params)

        assert new_root in server.project_indexes
        assert server.project_indexes[new_root] is new_idx
        # First project sets backward-compat aliases
        assert server.project_root == new_root
        assert server.index is new_idx
        mock_diag.assert_called_once()

    @patch("agent_actions.tooling.lsp.server._publish_diagnostics")
    @patch("agent_actions.tooling.lsp.server.build_index")
    def test_existing_project_reindex_on_yml_save(
        self, mock_build_index, mock_diag, tmp_path: Path
    ):
        """Saving an already-tracked agent_actions.yml rebuilds that project's index."""
        root = tmp_path / "proj"
        root.mkdir()
        yml = root / "agent_actions.yml"
        yml.touch()

        old_idx = ProjectIndex(root=root)
        server.project_indexes[root] = old_idx
        server.project_root = root
        server.index = old_idx

        new_idx = ProjectIndex(root=root)
        mock_build_index.return_value = new_idx

        params = MagicMock(spec=lsp.DidSaveTextDocumentParams)
        params.text_document.uri = yml.as_uri()

        did_save(params)

        assert server.project_indexes[root] is new_idx
        # Backward-compat alias updated since this is the primary project
        assert server.index is new_idx

    @patch("agent_actions.tooling.lsp.server._publish_diagnostics")
    @patch("agent_actions.tooling.lsp.server.build_index")
    def test_per_project_rebuild_on_file_save(self, mock_build_index, mock_diag, tmp_path: Path):
        """Saving a file inside a project rebuilds only that project's index."""
        proj_a = tmp_path / "proj_a"
        proj_b = tmp_path / "proj_b"
        proj_a.mkdir()
        proj_b.mkdir()

        idx_a = ProjectIndex(root=proj_a)
        idx_b = ProjectIndex(root=proj_b)
        server.project_indexes[proj_a] = idx_a
        server.project_indexes[proj_b] = idx_b
        server.project_root = proj_a
        server.index = idx_a

        # Save a file inside proj_b
        workflow_file = proj_b / "workflow.yml"
        workflow_file.touch()

        new_idx_b = ProjectIndex(root=proj_b)
        mock_build_index.return_value = new_idx_b

        params = MagicMock(spec=lsp.DidSaveTextDocumentParams)
        params.text_document.uri = workflow_file.as_uri()

        did_save(params)

        # proj_b rebuilt
        assert server.project_indexes[proj_b] is new_idx_b
        # proj_a unchanged
        assert server.project_indexes[proj_a] is idx_a
        # Backward-compat alias NOT updated (proj_a is still primary)
        assert server.index is idx_a
        mock_build_index.assert_called_once_with(proj_b)

    @patch("agent_actions.tooling.lsp.server._publish_diagnostics")
    @patch("agent_actions.tooling.lsp.server.build_index")
    def test_alias_sync_when_primary_project_rebuilt(
        self, mock_build_index, mock_diag, tmp_path: Path
    ):
        """When the primary project is rebuilt via file save, server.index is updated."""
        root = tmp_path / "proj"
        root.mkdir()

        old_idx = ProjectIndex(root=root)
        server.project_indexes[root] = old_idx
        server.project_root = root
        server.index = old_idx

        workflow_file = root / "workflow.yml"
        workflow_file.touch()

        new_idx = ProjectIndex(root=root)
        mock_build_index.return_value = new_idx

        params = MagicMock(spec=lsp.DidSaveTextDocumentParams)
        params.text_document.uri = workflow_file.as_uri()

        did_save(params)

        assert server.project_indexes[root] is new_idx
        assert server.index is new_idx

    @patch("agent_actions.tooling.lsp.server._publish_diagnostics")
    def test_file_outside_all_projects_is_noop(self, mock_diag, tmp_path: Path):
        """Saving a file outside all projects does not rebuild anything."""
        root = tmp_path / "proj"
        root.mkdir()
        idx = ProjectIndex(root=root)
        server.project_indexes[root] = idx
        server.project_root = root
        server.index = idx

        outside = tmp_path / "unrelated" / "file.yml"
        outside.parent.mkdir(parents=True)
        outside.touch()

        params = MagicMock(spec=lsp.DidSaveTextDocumentParams)
        params.text_document.uri = outside.as_uri()

        did_save(params)

        # Index is unchanged
        assert server.project_indexes[root] is idx
        assert server.index is idx


# ---------------------------------------------------------------------------
# Integration: two projects with populated indexes
# ---------------------------------------------------------------------------


class TestMultiProjectIntegration:
    """Integration tests verifying routing with real build_index output."""

    def setup_method(self):
        _reset_server()

    def teardown_method(self):
        _reset_server()

    def _scaffold_project(self, root: Path, action_name: str) -> Path:
        """Create a minimal on-disk project with one action, return the YAML path."""
        root.mkdir(parents=True, exist_ok=True)
        (root / "agent_actions.yml").touch()
        wf_dir = root / "agent_workflow" / "wf" / "agent_config"
        wf_dir.mkdir(parents=True)
        yml = wf_dir / "workflow.yml"
        yml.write_text(f"actions:\n  - name: {action_name}\n    impl: some_tool\n")
        return yml

    def test_same_action_name_resolves_to_correct_project(self, tmp_path: Path):
        """Two projects both define 'deploy'; routing resolves to the correct one."""
        proj_a = tmp_path / "proj_a"
        proj_b = tmp_path / "proj_b"
        yml_a = self._scaffold_project(proj_a, "deploy")
        yml_b = self._scaffold_project(proj_b, "deploy")

        idx_a = build_index(proj_a)
        idx_b = build_index(proj_b)
        server.project_indexes[proj_a] = idx_a
        server.project_indexes[proj_b] = idx_b

        # Route files to their respective indexes
        resolved_a = _index_for_file(yml_a)
        resolved_b = _index_for_file(yml_b)

        assert resolved_a is idx_a
        assert resolved_b is idx_b

        # Both indexes contain 'deploy' but at different file locations
        assert "deploy" in idx_a.actions
        assert "deploy" in idx_b.actions
        assert idx_a.actions["deploy"].file_path == yml_a
        assert idx_b.actions["deploy"].file_path == yml_b

    def test_handler_receives_correct_index_per_project(self, tmp_path: Path):
        """Actions populated per-project are accessible via their respective indexes."""
        proj_a = tmp_path / "proj_a"
        proj_b = tmp_path / "proj_b"

        idx_a = _make_project(proj_a, {"fetch_data": 0, "transform": 5})
        idx_b = _make_project(proj_b, {"deploy": 0, "notify": 3})

        server.project_indexes[proj_a] = idx_a
        server.project_indexes[proj_b] = idx_b

        # File in proj_a → should see fetch_data and transform
        file_a = proj_a / "some_file.yml"
        file_a.touch()
        result_a = _index_for_file(file_a)
        assert result_a is idx_a
        assert "fetch_data" in result_a.actions
        assert "transform" in result_a.actions
        assert "deploy" not in result_a.actions

        # File in proj_b → should see deploy and notify
        file_b = proj_b / "some_file.yml"
        file_b.touch()
        result_b = _index_for_file(file_b)
        assert result_b is idx_b
        assert "deploy" in result_b.actions
        assert "notify" in result_b.actions
        assert "fetch_data" not in result_b.actions

    @patch("agent_actions.tooling.lsp.server._publish_diagnostics")
    @patch("agent_actions.tooling.lsp.server.build_index")
    def test_did_save_rebuilds_correct_project_in_multi_project(
        self, mock_build_index, mock_diag, tmp_path: Path
    ):
        """In a multi-project workspace, saving a file rebuilds only its project."""
        proj_a = tmp_path / "proj_a"
        proj_b = tmp_path / "proj_b"

        idx_a = _make_project(proj_a, {"action_a": 0})
        idx_b = _make_project(proj_b, {"action_b": 0})
        server.project_indexes[proj_a] = idx_a
        server.project_indexes[proj_b] = idx_b
        server.project_root = proj_a
        server.index = idx_a

        # Save a file in proj_b
        file_b = proj_b / "new_workflow.yml"
        file_b.touch()

        rebuilt_b = _make_project(proj_b, {"action_b": 0, "action_c": 5})
        mock_build_index.return_value = rebuilt_b

        params = MagicMock(spec=lsp.DidSaveTextDocumentParams)
        params.text_document.uri = file_b.as_uri()
        did_save(params)

        # proj_b was rebuilt, proj_a was not
        assert server.project_indexes[proj_b] is rebuilt_b
        assert server.project_indexes[proj_a] is idx_a
        mock_build_index.assert_called_once_with(proj_b)


# ---------------------------------------------------------------------------
# did_change_watched_files
# ---------------------------------------------------------------------------


def _file_event(path: Path, change_type: int = lsp.FileChangeType.Changed) -> lsp.FileEvent:
    """Create a FileEvent for testing."""
    return lsp.FileEvent(uri=path.as_uri(), type=change_type)


class TestDidChangeWatchedFiles:
    """Tests for did_change_watched_files() handler."""

    def setup_method(self):
        _reset_server()

    def teardown_method(self):
        _reset_server()

    @patch("agent_actions.tooling.lsp.server._republish_diagnostics_for_projects")
    @patch("agent_actions.tooling.lsp.server.build_index")
    def test_schema_change_triggers_reindex(self, mock_build_index, mock_repub, tmp_path: Path):
        """External schema file change triggers reindex for the correct project."""
        root = tmp_path / "proj"
        idx = _make_project(root)
        server.project_indexes[root] = idx
        server.project_root = root
        server.index = idx

        new_idx = ProjectIndex(root=root)
        mock_build_index.return_value = new_idx

        schema_file = root / "schema" / "new_schema.yml"
        schema_file.parent.mkdir(parents=True)
        schema_file.touch()

        params = lsp.DidChangeWatchedFilesParams(
            changes=[_file_event(schema_file, lsp.FileChangeType.Created)]
        )
        did_change_watched_files(params)

        mock_build_index.assert_called_once_with(root)
        assert server.project_indexes[root] is new_idx
        assert server.index is new_idx

    @patch("agent_actions.tooling.lsp.server._republish_diagnostics_for_projects")
    @patch("agent_actions.tooling.lsp.server.build_index")
    def test_tool_creation_triggers_reindex(self, mock_build_index, mock_repub, tmp_path: Path):
        """External tool file creation triggers reindex."""
        root = tmp_path / "proj"
        idx = _make_project(root)
        server.project_indexes[root] = idx

        new_idx = ProjectIndex(root=root)
        mock_build_index.return_value = new_idx

        tool_file = root / "tools" / "new_tool.py"
        tool_file.parent.mkdir(parents=True)
        tool_file.touch()

        params = lsp.DidChangeWatchedFilesParams(
            changes=[_file_event(tool_file, lsp.FileChangeType.Created)]
        )
        did_change_watched_files(params)

        mock_build_index.assert_called_once_with(root)

    @patch("agent_actions.tooling.lsp.server._republish_diagnostics_for_projects")
    @patch("agent_actions.tooling.lsp.server.build_index")
    def test_file_deletion_triggers_reindex(self, mock_build_index, mock_repub, tmp_path: Path):
        """External file deletion triggers reindex."""
        root = tmp_path / "proj"
        idx = _make_project(root)
        server.project_indexes[root] = idx

        new_idx = ProjectIndex(root=root)
        mock_build_index.return_value = new_idx

        workflow_file = root / "agent_workflow" / "wf" / "agent_config" / "old.yml"

        params = lsp.DidChangeWatchedFilesParams(
            changes=[_file_event(workflow_file, lsp.FileChangeType.Deleted)]
        )
        did_change_watched_files(params)

        mock_build_index.assert_called_once_with(root)

    @patch("agent_actions.tooling.lsp.server._republish_diagnostics_for_projects")
    @patch("agent_actions.tooling.lsp.server.build_index")
    def test_batch_changes_deduplicate_rebuild(self, mock_build_index, mock_repub, tmp_path: Path):
        """Multiple changes to the same project trigger only one rebuild."""
        root = tmp_path / "proj"
        idx = _make_project(root)
        server.project_indexes[root] = idx

        new_idx = ProjectIndex(root=root)
        mock_build_index.return_value = new_idx

        file_a = root / "schema" / "a.yml"
        file_b = root / "schema" / "b.yml"

        params = lsp.DidChangeWatchedFilesParams(
            changes=[
                _file_event(file_a, lsp.FileChangeType.Created),
                _file_event(file_b, lsp.FileChangeType.Changed),
            ]
        )
        did_change_watched_files(params)

        mock_build_index.assert_called_once_with(root)

    @patch("agent_actions.tooling.lsp.server._republish_diagnostics_for_projects")
    @patch("agent_actions.tooling.lsp.server.build_index")
    def test_multi_project_isolation(self, mock_build_index, mock_repub, tmp_path: Path):
        """Change in project B does not rebuild project A."""
        proj_a = tmp_path / "proj_a"
        proj_b = tmp_path / "proj_b"
        idx_a = _make_project(proj_a)
        idx_b = _make_project(proj_b)
        server.project_indexes[proj_a] = idx_a
        server.project_indexes[proj_b] = idx_b
        server.project_root = proj_a
        server.index = idx_a

        new_idx_b = ProjectIndex(root=proj_b)
        mock_build_index.return_value = new_idx_b

        file_b = proj_b / "tools" / "tool.py"

        params = lsp.DidChangeWatchedFilesParams(
            changes=[_file_event(file_b, lsp.FileChangeType.Changed)]
        )
        did_change_watched_files(params)

        mock_build_index.assert_called_once_with(proj_b)
        assert server.project_indexes[proj_a] is idx_a  # unchanged
        assert server.index is idx_a  # primary alias unchanged

    @patch("agent_actions.tooling.lsp.server._register_file_watchers")
    @patch("agent_actions.tooling.lsp.server._republish_diagnostics_for_projects")
    @patch("agent_actions.tooling.lsp.server.build_index")
    def test_new_agent_actions_yml_registers_project(
        self, mock_build_index, mock_repub, mock_reg, tmp_path: Path
    ):
        """Creating a new agent_actions.yml registers the project."""
        new_root = tmp_path / "new_proj"
        new_root.mkdir()
        yml = new_root / "agent_actions.yml"
        yml.touch()

        new_idx = ProjectIndex(root=new_root)
        mock_build_index.return_value = new_idx

        params = lsp.DidChangeWatchedFilesParams(
            changes=[_file_event(yml, lsp.FileChangeType.Created)]
        )
        did_change_watched_files(params)

        assert new_root in server.project_indexes
        assert server.project_indexes[new_root] is new_idx
        assert server.project_root == new_root
        assert server.index is new_idx

    @patch("agent_actions.tooling.lsp.server._clear_diagnostics_for_root")
    @patch("agent_actions.tooling.lsp.server._republish_diagnostics_for_projects")
    @patch("agent_actions.tooling.lsp.server.build_index")
    def test_agent_actions_yml_deleted_removes_project(
        self, mock_build_index, mock_repub, mock_clear, tmp_path: Path
    ):
        """Deleting agent_actions.yml removes the project from indexes."""
        root = tmp_path / "proj"
        idx = _make_project(root)
        server.project_indexes[root] = idx
        server.project_root = root
        server.index = idx

        yml = root / "agent_actions.yml"

        params = lsp.DidChangeWatchedFilesParams(
            changes=[_file_event(yml, lsp.FileChangeType.Deleted)]
        )
        did_change_watched_files(params)

        assert root not in server.project_indexes
        assert server.project_root is None
        assert server.index is None
        mock_build_index.assert_not_called()

    @patch("agent_actions.tooling.lsp.server._clear_diagnostics_for_root")
    @patch("agent_actions.tooling.lsp.server._republish_diagnostics_for_projects")
    @patch("agent_actions.tooling.lsp.server.build_index")
    def test_agent_actions_yml_deleted_falls_back_to_next_project(
        self, mock_build_index, mock_repub, mock_clear, tmp_path: Path
    ):
        """Deleting primary project's config falls back to the next project."""
        proj_a = tmp_path / "proj_a"
        proj_b = tmp_path / "proj_b"
        idx_a = _make_project(proj_a)
        idx_b = _make_project(proj_b)
        server.project_indexes[proj_a] = idx_a
        server.project_indexes[proj_b] = idx_b
        server.project_root = proj_a
        server.index = idx_a

        yml_a = proj_a / "agent_actions.yml"

        params = lsp.DidChangeWatchedFilesParams(
            changes=[_file_event(yml_a, lsp.FileChangeType.Deleted)]
        )
        did_change_watched_files(params)

        assert proj_a not in server.project_indexes
        assert server.project_root == proj_b
        assert server.index is idx_b

    @patch("agent_actions.tooling.lsp.server._republish_diagnostics_for_projects")
    @patch("agent_actions.tooling.lsp.server.build_index")
    def test_file_outside_all_projects_is_noop(self, mock_build_index, mock_repub, tmp_path: Path):
        """External change to a file outside all projects triggers no rebuild."""
        root = tmp_path / "proj"
        idx = _make_project(root)
        server.project_indexes[root] = idx

        outside = tmp_path / "unrelated" / "file.yml"

        params = lsp.DidChangeWatchedFilesParams(
            changes=[_file_event(outside, lsp.FileChangeType.Changed)]
        )
        did_change_watched_files(params)

        mock_build_index.assert_not_called()
        assert server.project_indexes[root] is idx

    @patch("agent_actions.tooling.lsp.server._republish_diagnostics_for_projects")
    @patch("agent_actions.tooling.lsp.server.build_index")
    def test_diagnostics_republished_for_affected_projects(
        self, mock_build_index, mock_repub, tmp_path: Path
    ):
        """After reindex, diagnostics are republished for affected projects."""
        root = tmp_path / "proj"
        idx = _make_project(root)
        server.project_indexes[root] = idx

        new_idx = ProjectIndex(root=root)
        mock_build_index.return_value = new_idx

        schema_file = root / "schema" / "s.yml"

        params = lsp.DidChangeWatchedFilesParams(
            changes=[_file_event(schema_file, lsp.FileChangeType.Created)]
        )
        did_change_watched_files(params)

        mock_repub.assert_called_once()
        called_roots = mock_repub.call_args[0][0]
        assert root in called_roots

    @patch("agent_actions.tooling.lsp.server._republish_diagnostics_for_projects")
    @patch("agent_actions.tooling.lsp.server.build_index")
    def test_alias_updated_when_primary_project_rebuilt(
        self, mock_build_index, mock_repub, tmp_path: Path
    ):
        """server.index is updated when the primary project is rebuilt via watcher."""
        root = tmp_path / "proj"
        old_idx = _make_project(root)
        server.project_indexes[root] = old_idx
        server.project_root = root
        server.index = old_idx

        new_idx = ProjectIndex(root=root)
        mock_build_index.return_value = new_idx

        tool_file = root / "tools" / "t.py"

        params = lsp.DidChangeWatchedFilesParams(
            changes=[_file_event(tool_file, lsp.FileChangeType.Changed)]
        )
        did_change_watched_files(params)

        assert server.project_indexes[root] is new_idx
        assert server.index is new_idx


# ---------------------------------------------------------------------------
# _build_watchers_for_project
# ---------------------------------------------------------------------------


def _extract_patterns(watchers: list[lsp.FileSystemWatcher]) -> list[str]:
    """Extract glob pattern strings from a list of FileSystemWatchers."""
    patterns = []
    for w in watchers:
        gp = w.glob_pattern
        if isinstance(gp, lsp.RelativePattern):
            patterns.append(gp.pattern)
        else:
            patterns.append(gp)
    return patterns


class TestBuildWatchersForProject:
    """Tests for _build_watchers_for_project()."""

    def test_core_patterns_always_present(self, tmp_path: Path):
        """Core patterns (agent_actions.yml, workflows, prompts) are always included."""
        root = tmp_path / "proj"
        root.mkdir()
        (root / "agent_actions.yml").write_text("schema_path: schema\n")

        patterns = _extract_patterns(_build_watchers_for_project(root))

        assert "agent_actions.yml" in patterns
        assert "agent_workflow/*/agent_config/*.yml" in patterns
        assert "prompt_store/*.md" in patterns

    def test_tool_dir_pattern_from_config(self, tmp_path: Path):
        """Tool directory patterns are derived from config."""
        root = tmp_path / "proj"
        root.mkdir()
        (root / "agent_actions.yml").write_text("schema_path: schema\ntool_path: custom_tools\n")

        patterns = _extract_patterns(_build_watchers_for_project(root))

        assert "custom_tools/**/*.py" in patterns

    def test_schema_patterns_from_config(self, tmp_path: Path):
        """Schema directory patterns are derived from config."""
        root = tmp_path / "proj"
        root.mkdir()
        (root / "agent_actions.yml").write_text("schema_path: my_schemas\n")

        patterns = _extract_patterns(_build_watchers_for_project(root))

        assert "my_schemas/**/*.yml" in patterns
        assert "my_schemas/**/*.yaml" in patterns

    def test_fallback_when_config_missing(self, tmp_path: Path):
        """When config is missing, defaults to 'tools' and skips schema patterns."""
        root = tmp_path / "proj"
        root.mkdir()
        # No agent_actions.yml -> config loading will fail

        patterns = _extract_patterns(_build_watchers_for_project(root))

        # Core patterns still present
        assert "agent_actions.yml" in patterns
        # Default tool dir
        assert "tools/**/*.py" in patterns


# ---------------------------------------------------------------------------
# Additional did_change_watched_files branch coverage
# ---------------------------------------------------------------------------


class TestDidChangeWatchedFilesBranches:
    """Cover untested branches in did_change_watched_files()."""

    def setup_method(self):
        _reset_server()

    def teardown_method(self):
        _reset_server()

    @patch("agent_actions.tooling.lsp.server._republish_diagnostics_for_projects")
    @patch("agent_actions.tooling.lsp.server.build_index")
    def test_delete_untracked_project_is_noop(self, mock_build_index, mock_repub, tmp_path: Path):
        """Deleting an agent_actions.yml for a non-tracked project is a silent no-op."""
        root = tmp_path / "proj"
        root.mkdir()
        yml = root / "agent_actions.yml"
        yml.touch()

        # No project registered — deletion should not crash
        params = lsp.DidChangeWatchedFilesParams(
            changes=[_file_event(yml, lsp.FileChangeType.Deleted)]
        )
        did_change_watched_files(params)

        mock_build_index.assert_not_called()
        assert not server.project_indexes

    @patch("agent_actions.tooling.lsp.server._clear_diagnostics_for_root")
    @patch("agent_actions.tooling.lsp.server._republish_diagnostics_for_projects")
    @patch("agent_actions.tooling.lsp.server.build_index")
    def test_delete_non_primary_project(
        self, mock_build_index, mock_repub, mock_clear, tmp_path: Path
    ):
        """Deleting a non-primary project leaves primary unchanged."""
        proj_a = tmp_path / "proj_a"
        proj_b = tmp_path / "proj_b"
        idx_a = _make_project(proj_a)
        idx_b = _make_project(proj_b)
        server.project_indexes[proj_a] = idx_a
        server.project_indexes[proj_b] = idx_b
        server.project_root = proj_a
        server.index = idx_a

        yml_b = proj_b / "agent_actions.yml"

        params = lsp.DidChangeWatchedFilesParams(
            changes=[_file_event(yml_b, lsp.FileChangeType.Deleted)]
        )
        did_change_watched_files(params)

        assert proj_b not in server.project_indexes
        assert server.project_root == proj_a
        assert server.index is idx_a
        mock_clear.assert_called_once_with(proj_b)

    @patch("agent_actions.tooling.lsp.server._republish_diagnostics_for_projects")
    @patch("agent_actions.tooling.lsp.server.build_index")
    def test_changed_tracked_project_triggers_reindex(
        self, mock_build_index, mock_repub, tmp_path: Path
    ):
        """Changed agent_actions.yml on an already-tracked project triggers reindex."""
        root = tmp_path / "proj"
        idx = _make_project(root)
        server.project_indexes[root] = idx
        server.project_root = root
        server.index = idx

        new_idx = ProjectIndex(root=root)
        mock_build_index.return_value = new_idx

        yml = root / "agent_actions.yml"

        params = lsp.DidChangeWatchedFilesParams(
            changes=[_file_event(yml, lsp.FileChangeType.Changed)]
        )
        did_change_watched_files(params)

        mock_build_index.assert_called_once_with(root)
        assert server.project_indexes[root] is new_idx

    @patch("agent_actions.tooling.lsp.server._register_file_watchers")
    @patch("agent_actions.tooling.lsp.server._republish_diagnostics_for_projects")
    @patch("agent_actions.tooling.lsp.server.build_index")
    def test_new_project_when_primary_exists(
        self, mock_build_index, mock_repub, mock_reg, tmp_path: Path
    ):
        """Registering a new project when primary already exists doesn't change aliases."""
        existing = tmp_path / "existing"
        existing_idx = _make_project(existing)
        server.project_indexes[existing] = existing_idx
        server.project_root = existing
        server.index = existing_idx

        new_root = tmp_path / "new_proj"
        new_root.mkdir()
        yml = new_root / "agent_actions.yml"
        yml.touch()

        new_idx = ProjectIndex(root=new_root)
        mock_build_index.return_value = new_idx

        params = lsp.DidChangeWatchedFilesParams(
            changes=[_file_event(yml, lsp.FileChangeType.Created)]
        )
        did_change_watched_files(params)

        assert new_root in server.project_indexes
        # Primary alias unchanged — existing project stays primary
        assert server.project_root == existing
        assert server.index is existing_idx
        mock_reg.assert_called_once()

    @patch("agent_actions.tooling.lsp.server._republish_diagnostics_for_projects")
    @patch("agent_actions.tooling.lsp.server.build_index")
    def test_empty_changes_is_noop(self, mock_build_index, mock_repub, tmp_path: Path):
        """Empty changes list triggers no rebuild."""
        root = tmp_path / "proj"
        idx = _make_project(root)
        server.project_indexes[root] = idx

        params = lsp.DidChangeWatchedFilesParams(changes=[])
        did_change_watched_files(params)

        mock_build_index.assert_not_called()


# ---------------------------------------------------------------------------
# _republish_diagnostics_for_projects
# ---------------------------------------------------------------------------


class TestRepublishDiagnostics:
    """Tests for _republish_diagnostics_for_projects()."""

    def setup_method(self):
        _reset_server()

    def teardown_method(self):
        _reset_server()

    @patch("agent_actions.tooling.lsp.server._publish_diagnostics")
    def test_empty_roots_is_noop(self, mock_pub):
        """Empty roots set does not call _publish_diagnostics."""
        _republish_diagnostics_for_projects(set())
        mock_pub.assert_not_called()

    @patch("agent_actions.tooling.lsp.server._publish_diagnostics")
    def test_publishes_for_matching_project(self, mock_pub, tmp_path: Path):
        """Publishes diagnostics for open documents in the affected project."""
        root = tmp_path / "proj"
        idx = _make_project(root)
        server.project_indexes[root] = idx

        doc_uri = (root / "agent_workflow" / "wf" / "agent_config" / "w.yml").as_uri()
        mock_workspace = MagicMock()
        mock_workspace.text_documents = {doc_uri: MagicMock()}
        with patch.object(
            type(server), "workspace", new_callable=lambda: property(lambda self: mock_workspace)
        ):
            _republish_diagnostics_for_projects({root})

        mock_pub.assert_called_once_with(doc_uri)

    @patch("agent_actions.tooling.lsp.server._publish_diagnostics")
    def test_skips_documents_in_other_projects(self, mock_pub, tmp_path: Path):
        """Does not republish diagnostics for documents outside affected projects."""
        proj_a = tmp_path / "proj_a"
        proj_b = tmp_path / "proj_b"
        idx_a = _make_project(proj_a)
        idx_b = _make_project(proj_b)
        server.project_indexes[proj_a] = idx_a
        server.project_indexes[proj_b] = idx_b

        doc_uri_b = (proj_b / "workflow.yml").as_uri()
        mock_workspace = MagicMock()
        mock_workspace.text_documents = {doc_uri_b: MagicMock()}
        with patch.object(
            type(server), "workspace", new_callable=lambda: property(lambda self: mock_workspace)
        ):
            _republish_diagnostics_for_projects({proj_a})

        mock_pub.assert_not_called()


# ---------------------------------------------------------------------------
# initialized and _register_file_watchers
# ---------------------------------------------------------------------------


class TestInitializedAndRegistration:
    """Tests for initialized() and _register_file_watchers()."""

    def setup_method(self):
        _reset_server()

    def teardown_method(self):
        _reset_server()

    @patch("agent_actions.tooling.lsp.server._register_file_watchers")
    def test_initialized_calls_register(self, mock_reg):
        """initialized() handler calls _register_file_watchers."""
        params = MagicMock(spec=lsp.InitializedParams)
        initialized(params)
        mock_reg.assert_called_once()

    @patch("agent_actions.tooling.lsp.server.server.client_register_capability")
    def test_register_sends_correct_params(self, mock_cap, tmp_path: Path):
        """_register_file_watchers sends RegistrationParams to client."""
        root = tmp_path / "proj"
        root.mkdir()
        (root / "agent_actions.yml").write_text("schema_path: schema\n")
        idx = ProjectIndex(root=root)
        server.project_indexes[root] = idx

        _register_file_watchers()

        mock_cap.assert_called_once()
        reg_params = mock_cap.call_args[0][0]
        assert isinstance(reg_params, lsp.RegistrationParams)
        assert len(reg_params.registrations) == 1

    @patch("agent_actions.tooling.lsp.server.server.client_register_capability")
    def test_register_failure_is_nonfatal(self, mock_cap, tmp_path: Path):
        """Registration failure is logged but does not crash."""
        root = tmp_path / "proj"
        root.mkdir()
        (root / "agent_actions.yml").write_text("schema_path: schema\n")
        idx = ProjectIndex(root=root)
        server.project_indexes[root] = idx

        mock_cap.side_effect = RuntimeError("client does not support")

        # Should not raise
        _register_file_watchers()

    def test_register_with_no_projects_is_noop(self):
        """No projects → no registration call."""
        with patch(
            "agent_actions.tooling.lsp.server.server.client_register_capability"
        ) as mock_cap:
            _register_file_watchers()
            mock_cap.assert_not_called()
