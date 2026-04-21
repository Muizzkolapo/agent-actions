"""Tests for per-workflow action namespace resolution.

Verifies that identically-named actions in different workflows resolve
to the correct workflow scope in completions, go-to-definition, and
metadata lookups.
"""

from pathlib import Path

from agent_actions.tooling.lsp.models import (
    ActionMetadata,
    Location,
    ProjectIndex,
)


def _make_project(tmp_path: Path) -> tuple[ProjectIndex, Path, Path, Path, Path]:
    """Build a two-workflow project with overlapping action names.

    Layout:
        project_root/
          agent_workflow/
            workflow_a/
              agent_config/
                pipeline.yml      <- defines "classify" at line 5
            workflow_b/
              agent_config/
                pipeline.yml      <- defines "classify" at line 10

    Returns (index, root, file_a, file_b)
    """
    root = tmp_path / "project"
    root.mkdir()
    (root / "agent_actions.yml").touch()

    wf_a_dir = root / "agent_workflow" / "workflow_a" / "agent_config"
    wf_b_dir = root / "agent_workflow" / "workflow_b" / "agent_config"
    wf_a_dir.mkdir(parents=True)
    wf_b_dir.mkdir(parents=True)

    file_a = wf_a_dir / "pipeline.yml"
    file_b = wf_b_dir / "pipeline.yml"
    file_a.touch()
    file_b.touch()

    loc_a = Location(file_path=file_a, line=5, column=0)
    loc_b = Location(file_path=file_b, line=10, column=0)

    index = ProjectIndex(root=root)
    index.workflows["workflow_a"] = root / "agent_workflow" / "workflow_a"
    index.workflows["workflow_b"] = root / "agent_workflow" / "workflow_b"

    # Per-file actions
    index.file_actions[file_a] = {
        "classify": ActionMetadata(name="classify", location=loc_a),
        "extract": ActionMetadata(
            name="extract",
            location=Location(file_path=file_a, line=6, column=0),
        ),
    }
    index.file_actions[file_b] = {
        "classify": ActionMetadata(name="classify", location=loc_b),
        "summarize": ActionMetadata(
            name="summarize",
            location=Location(file_path=file_b, line=11, column=0),
        ),
    }

    # Per-workflow actions
    index.workflow_actions["workflow_a"] = {
        "classify": loc_a,
        "extract": Location(file_path=file_a, line=6, column=0),
    }
    index.workflow_actions["workflow_b"] = {
        "classify": loc_b,
        "summarize": Location(file_path=file_b, line=11, column=0),
    }

    # Cached workflow derivation (mirrors what the indexer populates)
    index.file_to_workflow[file_a] = "workflow_a"
    index.file_to_workflow[file_b] = "workflow_b"

    # Global (last-indexed wins — workflow_b's classify overwrites workflow_a's)
    index.actions["classify"] = loc_b
    index.actions["extract"] = Location(file_path=file_a, line=6, column=0)
    index.actions["summarize"] = Location(file_path=file_b, line=11, column=0)

    return index, root, file_a, file_b


# ---------------------------------------------------------------------------
# workflow_for_file
# ---------------------------------------------------------------------------


class TestWorkflowForFile:
    """Tests for ProjectIndex.workflow_for_file()."""

    def test_returns_workflow_name(self, tmp_path: Path):
        index = ProjectIndex(root=tmp_path)
        file_path = tmp_path / "agent_workflow" / "my_wf" / "agent_config" / "pipeline.yml"
        assert index.workflow_for_file(file_path) == "my_wf"

    def test_returns_none_for_flat_layout(self, tmp_path: Path):
        index = ProjectIndex(root=tmp_path)
        file_path = tmp_path / "agent_config" / "pipeline.yml"
        assert index.workflow_for_file(file_path) is None

    def test_returns_none_for_unrelated_path(self, tmp_path: Path):
        index = ProjectIndex(root=tmp_path)
        file_path = tmp_path / "some" / "other" / "file.yml"
        assert index.workflow_for_file(file_path) is None


# ---------------------------------------------------------------------------
# get_action — same action name in two workflows
# ---------------------------------------------------------------------------


class TestGetActionCollision:
    """get_action resolves to the correct workflow when names collide."""

    def test_same_file_wins(self, tmp_path: Path):
        """Per-file lookup is most specific — always wins."""
        index, root, file_a, file_b = _make_project(tmp_path)

        loc = index.get_action("classify", current_file=file_a)
        assert loc is not None
        assert loc.file_path == file_a
        assert loc.line == 5

    def test_other_workflow_does_not_leak(self, tmp_path: Path):
        """Querying from workflow_a must NOT return workflow_b's classify."""
        index, root, file_a, file_b = _make_project(tmp_path)

        loc_a = index.get_action("classify", current_file=file_a)
        loc_b = index.get_action("classify", current_file=file_b)
        assert loc_a is not None
        assert loc_b is not None
        assert loc_a.line == 5  # workflow_a's classify
        assert loc_b.line == 10  # workflow_b's classify

    def test_workflow_scoped_cross_file(self, tmp_path: Path):
        """An action defined in another file of the same workflow resolves via workflow scope."""
        index, root, file_a, file_b = _make_project(tmp_path)

        # Query "extract" from a *different* file in workflow_a (e.g., another config)
        other_file = root / "agent_workflow" / "workflow_a" / "agent_config" / "secondary.yml"
        other_file.parent.mkdir(parents=True, exist_ok=True)
        other_file.touch()
        # other_file has no file_actions entry, so per-file won't match

        loc = index.get_action("extract", current_file=other_file)
        assert loc is not None
        assert loc.file_path == file_a  # resolved via workflow scope

    def test_global_fallback_without_current_file(self, tmp_path: Path):
        """Without current_file, global fallback is used."""
        index, root, file_a, file_b = _make_project(tmp_path)

        loc = index.get_action("classify")
        assert loc is not None
        # Global has workflow_b's classify (last-indexed)
        assert loc.line == 10

    def test_flat_layout_uses_global(self, tmp_path: Path):
        """File not under agent_workflow/ falls back to global actions."""
        index, root, file_a, file_b = _make_project(tmp_path)

        flat_file = root / "agent_config" / "flat.yml"
        flat_file.parent.mkdir(parents=True, exist_ok=True)
        flat_file.touch()

        loc = index.get_action("classify", current_file=flat_file)
        assert loc is not None
        # Falls through per-file (no entry) and per-workflow (None) to global
        assert loc.line == 10

    def test_action_unique_to_one_workflow(self, tmp_path: Path):
        """Actions that only exist in one workflow resolve correctly from that workflow."""
        index, root, file_a, file_b = _make_project(tmp_path)

        # "extract" only exists in workflow_a — resolves from workflow_a
        loc = index.get_action("extract", current_file=file_a)
        assert loc is not None
        assert loc.file_path == file_a

        # From workflow_b, "extract" does NOT leak — workflow isolation
        loc_from_b = index.get_action("extract", current_file=file_b)
        assert loc_from_b is None


# ---------------------------------------------------------------------------
# get_action_metadata — workflow-scoped resolution
# ---------------------------------------------------------------------------


class TestGetActionMetadataCollision:
    """get_action_metadata resolves to the correct workflow when names collide."""

    def test_same_file_wins(self, tmp_path: Path):
        index, root, file_a, file_b = _make_project(tmp_path)

        meta = index.get_action_metadata("classify", current_file=file_a)
        assert meta is not None
        assert meta.location.file_path == file_a
        assert meta.location.line == 5

    def test_same_workflow_different_file(self, tmp_path: Path):
        """Metadata found from another file in the same workflow."""
        index, root, file_a, file_b = _make_project(tmp_path)

        other_file = root / "agent_workflow" / "workflow_a" / "agent_config" / "other.yml"
        other_file.parent.mkdir(parents=True, exist_ok=True)
        other_file.touch()
        index.file_actions[other_file] = {}

        meta = index.get_action_metadata("extract", current_file=other_file)
        assert meta is not None
        assert meta.location.file_path == file_a

    def test_collision_returns_correct_workflow(self, tmp_path: Path):
        index, root, file_a, file_b = _make_project(tmp_path)

        meta_a = index.get_action_metadata("classify", current_file=file_a)
        meta_b = index.get_action_metadata("classify", current_file=file_b)
        assert meta_a is not None
        assert meta_b is not None
        assert meta_a.location.line == 5
        assert meta_b.location.line == 10

    def test_no_current_file_returns_any(self, tmp_path: Path):
        """Without current_file, returns first match from any file."""
        index, root, file_a, file_b = _make_project(tmp_path)

        meta = index.get_action_metadata("classify")
        assert meta is not None
        # Returns one of the two — we just verify it doesn't crash
        assert meta.name == "classify"


# ---------------------------------------------------------------------------
# Indexer integration — build_index populates workflow_actions
# ---------------------------------------------------------------------------


class TestIndexerPopulatesWorkflowActions:
    """build_index produces per-workflow action registries."""

    def test_two_workflows_same_action_name(self, tmp_path: Path):
        """Identical action names in separate workflows are indexed per-workflow."""
        from agent_actions.tooling.lsp.indexer import build_index

        root = tmp_path / "project"
        root.mkdir()
        (root / "agent_actions.yml").write_text("project_name: test\n")

        for wf_name, line_content in [("alpha", "alpha_action"), ("beta", "beta_action")]:
            wf_dir = root / "agent_workflow" / wf_name / "agent_config"
            wf_dir.mkdir(parents=True)
            # Both workflows define "classify" plus a unique action
            (wf_dir / "pipeline.yml").write_text(
                f"actions:\n  - name: classify\n  - name: {line_content}\n"
            )

        index = build_index(root)

        # Per-workflow registries exist
        assert "alpha" in index.workflow_actions
        assert "beta" in index.workflow_actions

        # Both have "classify" but pointing to different files
        assert "classify" in index.workflow_actions["alpha"]
        assert "classify" in index.workflow_actions["beta"]
        alpha_file = index.workflow_actions["alpha"]["classify"].file_path
        beta_file = index.workflow_actions["beta"]["classify"].file_path
        assert alpha_file != beta_file
        assert "alpha" in str(alpha_file)
        assert "beta" in str(beta_file)

        # Unique actions only in their workflow
        assert "alpha_action" in index.workflow_actions["alpha"]
        assert "alpha_action" not in index.workflow_actions["beta"]
        assert "beta_action" in index.workflow_actions["beta"]
        assert "beta_action" not in index.workflow_actions["alpha"]

        # Global dict has all actions (last-indexed wins for collisions)
        assert "classify" in index.actions
        assert "alpha_action" in index.actions
        assert "beta_action" in index.actions

    def test_flat_layout_no_workflow_actions(self, tmp_path: Path):
        """Project without agent_workflow/ has empty workflow_actions."""
        from agent_actions.tooling.lsp.indexer import build_index

        root = tmp_path / "flat_project"
        root.mkdir()
        (root / "agent_actions.yml").write_text("project_name: flat\n")

        index = build_index(root)
        assert index.workflow_actions == {}


# ---------------------------------------------------------------------------
# Mixed layout: some workflows + flat config
# ---------------------------------------------------------------------------


class TestMixedLayout:
    """Projects with both agent_workflow/ and flat agent_config/ configs."""

    def test_flat_file_falls_through_to_global(self, tmp_path: Path):
        """A flat-layout file uses global fallback, doesn't see workflow-scoped actions."""
        index, root, file_a, file_b = _make_project(tmp_path)

        # Add a flat-layout action
        flat_file = root / "agent_config" / "flat.yml"
        flat_file.parent.mkdir(parents=True, exist_ok=True)
        flat_file.touch()

        flat_loc = Location(file_path=flat_file, line=0, column=0)
        index.file_actions[flat_file] = {
            "flat_action": ActionMetadata(name="flat_action", location=flat_loc),
        }
        index.actions["flat_action"] = flat_loc

        # From flat file, "classify" resolves via global (workflow_b's, last-indexed)
        loc = index.get_action("classify", current_file=flat_file)
        assert loc is not None
        assert loc.line == 10

        # "flat_action" resolves from flat file's own file_actions
        loc_flat = index.get_action("flat_action", current_file=flat_file)
        assert loc_flat is not None
        assert loc_flat.file_path == flat_file
