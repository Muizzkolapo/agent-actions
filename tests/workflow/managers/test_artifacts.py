"""Tests for ArtifactLinker — workflow artifact linking via manifests."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from agent_actions.workflow.managers.artifacts import ArtifactLinker


@pytest.fixture()
def workflows_root(tmp_path: Path) -> Path:
    """Return a temporary workflows root directory."""
    return tmp_path / "workflows"


@pytest.fixture()
def linker(workflows_root: Path) -> ArtifactLinker:
    """Return an ArtifactLinker rooted at the temp workflows dir."""
    workflows_root.mkdir()
    return ArtifactLinker(workflows_root)


# ---------------------------------------------------------------------------
# validate_safe_path
# ---------------------------------------------------------------------------


class TestValidateSafePath:
    def test_path_inside_base_dir(self, linker: ArtifactLinker, workflows_root: Path):
        child = workflows_root / "sub" / "file.txt"
        child.parent.mkdir(parents=True)
        child.touch()
        assert linker.validate_safe_path(child, workflows_root) is True

    def test_path_outside_base_dir(self, linker: ArtifactLinker, tmp_path: Path):
        outside = tmp_path / "other" / "file.txt"
        outside.parent.mkdir(parents=True)
        outside.touch()
        assert linker.validate_safe_path(outside, linker.workflows_root) is False

    def test_path_traversal_via_dotdot(self, linker: ArtifactLinker, tmp_path: Path):
        sneaky = linker.workflows_root / ".." / "outside"
        sneaky.parent.mkdir(parents=True, exist_ok=True)
        assert linker.validate_safe_path(sneaky, linker.workflows_root) is False

    def test_symlink_outside_base_dir(self, linker: ArtifactLinker, tmp_path: Path):
        external = tmp_path / "external_dir"
        external.mkdir()
        symlink = linker.workflows_root / "link"
        symlink.symlink_to(external)
        assert linker.validate_safe_path(symlink, linker.workflows_root) is False


# ---------------------------------------------------------------------------
# find_latest_node_dir
# ---------------------------------------------------------------------------


class TestFindLatestNodeDir:
    def test_returns_most_recently_modified(self, linker: ArtifactLinker):
        target = linker.workflows_root / "target"
        target.mkdir()
        old = target / "node_a"
        old.mkdir()
        # Set old mtime in the past
        os.utime(old, (0, 0))
        new = target / "node_b"
        new.mkdir()
        # Ensure node_b has a later mtime
        time.sleep(0.01)
        new.joinpath("marker").touch()
        result = linker.find_latest_node_dir(target)
        assert result == new

    def test_returns_none_for_empty_dir(self, linker: ArtifactLinker):
        target = linker.workflows_root / "empty_target"
        target.mkdir()
        assert linker.find_latest_node_dir(target) is None

    def test_skips_hidden_directories(self, linker: ArtifactLinker):
        target = linker.workflows_root / "target"
        target.mkdir()
        hidden = target / ".hidden"
        hidden.mkdir()
        assert linker.find_latest_node_dir(target) is None

    def test_skips_hidden_returns_visible(self, linker: ArtifactLinker):
        target = linker.workflows_root / "target"
        target.mkdir()
        (target / ".hidden").mkdir()
        visible = target / "visible"
        visible.mkdir()
        assert linker.find_latest_node_dir(target) == visible


# ---------------------------------------------------------------------------
# read_manifest
# ---------------------------------------------------------------------------


class TestReadManifest:
    def test_valid_manifest(self, tmp_path: Path):
        manifest_data = {
            "upstream_workflow": "wf_a",
            "upstream_path": "/some/path",
            "files": ["a.csv"],
        }
        manifest_file = tmp_path / ArtifactLinker.MANIFEST_FILENAME
        manifest_file.write_text(json.dumps(manifest_data))
        result = ArtifactLinker.read_manifest(tmp_path)
        assert result == manifest_data

    def test_missing_file_returns_none(self, tmp_path: Path):
        assert ArtifactLinker.read_manifest(tmp_path) is None

    def test_malformed_json_returns_none(self, tmp_path: Path):
        manifest_file = tmp_path / ArtifactLinker.MANIFEST_FILENAME
        manifest_file.write_text("{not valid json")
        assert ArtifactLinker.read_manifest(tmp_path) is None

    def test_missing_required_fields_returns_none(self, tmp_path: Path):
        manifest_file = tmp_path / ArtifactLinker.MANIFEST_FILENAME
        manifest_file.write_text(json.dumps({"files": ["a.csv"]}))
        assert ArtifactLinker.read_manifest(tmp_path) is None

    def test_partial_required_fields_returns_none(self, tmp_path: Path):
        manifest_file = tmp_path / ArtifactLinker.MANIFEST_FILENAME
        manifest_file.write_text(json.dumps({"upstream_workflow": "wf"}))
        assert ArtifactLinker.read_manifest(tmp_path) is None


# ---------------------------------------------------------------------------
# _write_upstream_manifest
# ---------------------------------------------------------------------------


class TestWriteUpstreamManifest:
    def test_creates_manifest_with_correct_structure(self, linker: ArtifactLinker):
        source_node = linker.workflows_root / "src_node"
        source_node.mkdir(parents=True)
        (source_node / "data.csv").touch()
        (source_node / "report.json").touch()
        (source_node / ".hidden").touch()  # should be excluded

        target_io = linker.workflows_root / "target_wf" / "agent_io"

        linker._write_upstream_manifest(target_io, "wf_source", source_node)

        manifest_file = target_io / ArtifactLinker.MANIFEST_FILENAME
        assert manifest_file.exists()

        manifest = json.loads(manifest_file.read_text())
        assert manifest["upstream_workflow"] == "wf_source"
        assert manifest["upstream_path"] == str(source_node)
        assert manifest["files"] == ["data.csv", "report.json"]

    def test_creates_target_io_directory_if_missing(self, linker: ArtifactLinker):
        source_node = linker.workflows_root / "src"
        source_node.mkdir(parents=True)
        (source_node / "file.txt").touch()

        target_io = linker.workflows_root / "new" / "deep" / "agent_io"
        assert not target_io.exists()

        linker._write_upstream_manifest(target_io, "wf", source_node)
        assert target_io.exists()
        assert (target_io / ArtifactLinker.MANIFEST_FILENAME).exists()

    def test_atomic_write_no_temp_files_remain(self, linker: ArtifactLinker):
        source_node = linker.workflows_root / "src"
        source_node.mkdir(parents=True)
        (source_node / "f.txt").touch()

        target_io = linker.workflows_root / "tgt" / "agent_io"
        linker._write_upstream_manifest(target_io, "wf", source_node)

        # Only the manifest file should remain (no .manifest_tmp_ leftovers)
        remaining = list(target_io.iterdir())
        assert len(remaining) == 1
        assert remaining[0].name == ArtifactLinker.MANIFEST_FILENAME


# ---------------------------------------------------------------------------
# link_workflow_artifacts (integration-style with real filesystem)
# ---------------------------------------------------------------------------


class TestLinkWorkflowArtifacts:
    def _setup_source(self, workflows_root: Path, name: str) -> Path:
        """Create a source workflow with an output node containing a file."""
        source_target = workflows_root / name / "agent_io" / "target"
        node = source_target / "node_1"
        node.mkdir(parents=True)
        (node / "output.csv").touch()
        return source_target

    def test_happy_path(self, linker: ArtifactLinker):
        self._setup_source(linker.workflows_root, "src_wf")
        target_io = linker.workflows_root / "tgt_wf" / "agent_io"
        target_io.mkdir(parents=True)

        linker.link_workflow_artifacts("src_wf", "tgt_wf")

        manifest_file = target_io / ArtifactLinker.MANIFEST_FILENAME
        assert manifest_file.exists()
        manifest = json.loads(manifest_file.read_text())
        assert manifest["upstream_workflow"] == "src_wf"
        assert "output.csv" in manifest["files"]

    def test_source_target_dir_missing_returns_early(self, linker: ArtifactLinker):
        target_io = linker.workflows_root / "tgt_wf" / "agent_io"
        target_io.mkdir(parents=True)

        linker.link_workflow_artifacts("nonexistent", "tgt_wf")

        # No manifest written — early return
        assert not (target_io / ArtifactLinker.MANIFEST_FILENAME).exists()

    def test_no_output_nodes_returns_early(self, linker: ArtifactLinker):
        source_target = linker.workflows_root / "empty_src" / "agent_io" / "target"
        source_target.mkdir(parents=True)
        target_io = linker.workflows_root / "tgt_wf" / "agent_io"
        target_io.mkdir(parents=True)

        linker.link_workflow_artifacts("empty_src", "tgt_wf")

        assert not (target_io / ArtifactLinker.MANIFEST_FILENAME).exists()

    def test_path_traversal_rejected(self, linker: ArtifactLinker, tmp_path: Path):
        # Create a source that resolves outside workflows_root
        external = tmp_path / "external"
        external.mkdir()
        (external / "evil.txt").touch()

        source_target = linker.workflows_root / "attack" / "agent_io" / "target"
        source_target.mkdir(parents=True)
        # Create a symlink node pointing outside
        (source_target / "node_x").symlink_to(external)
        target_io = linker.workflows_root / "tgt_wf" / "agent_io"
        target_io.mkdir(parents=True)

        linker.link_workflow_artifacts("attack", "tgt_wf")

        # Rejected — no manifest written
        assert not (target_io / ArtifactLinker.MANIFEST_FILENAME).exists()

    def test_target_path_traversal_rejected(self, linker: ArtifactLinker, tmp_path: Path):
        """Exercises artifacts.py:41-43 — target_io outside workflows_root."""
        self._setup_source(linker.workflows_root, "src_wf")

        # Create target that symlinks outside workflows_root
        external_target = tmp_path / "external_target"
        external_target.mkdir()
        target_wf = linker.workflows_root / "tgt_wf"
        target_wf.mkdir(parents=True)
        (target_wf / "agent_io").symlink_to(external_target)

        linker.link_workflow_artifacts("src_wf", "tgt_wf")

        # Rejected — no manifest written in the external directory
        assert not (external_target / ArtifactLinker.MANIFEST_FILENAME).exists()


# ---------------------------------------------------------------------------
# _write_upstream_manifest error cleanup
# ---------------------------------------------------------------------------


class TestWriteUpstreamManifestCleanup:
    def test_cleans_up_temp_file_on_json_dump_failure(self, linker: ArtifactLinker):
        """Exercises artifacts.py:79-84 — temp file removal on write error."""
        source_node = linker.workflows_root / "src"
        source_node.mkdir(parents=True)
        (source_node / "f.txt").touch()

        target_io = linker.workflows_root / "tgt" / "agent_io"
        target_io.mkdir(parents=True)

        with patch(
            "agent_actions.workflow.managers.artifacts.json.dump", side_effect=OSError("disk full")
        ):
            with pytest.raises(OSError, match="disk full"):
                linker._write_upstream_manifest(target_io, "wf", source_node)

        # No temp files or manifests should remain
        remaining = [f for f in target_io.iterdir() if not f.name.startswith("__")]
        assert all(not f.name.startswith(".manifest_tmp_") for f in remaining)
        assert not (target_io / ArtifactLinker.MANIFEST_FILENAME).exists()


# ---------------------------------------------------------------------------
# link_upstream_artifacts / link_downstream_artifacts (delegation)
# ---------------------------------------------------------------------------


class TestDelegationMethods:
    def test_link_upstream_delegates(self, linker: ArtifactLinker):
        # Setup source and target
        source_target = linker.workflows_root / "up" / "agent_io" / "target" / "node_1"
        source_target.mkdir(parents=True)
        (source_target / "data.csv").touch()
        target_io = linker.workflows_root / "current" / "agent_io"
        target_io.mkdir(parents=True)

        linker.link_upstream_artifacts("up", "current")

        manifest = json.loads((target_io / ArtifactLinker.MANIFEST_FILENAME).read_text())
        assert manifest["upstream_workflow"] == "up"

    def test_link_downstream_delegates(self, linker: ArtifactLinker):
        source_target = linker.workflows_root / "current" / "agent_io" / "target" / "node_1"
        source_target.mkdir(parents=True)
        (source_target / "result.json").touch()
        target_io = linker.workflows_root / "down" / "agent_io"
        target_io.mkdir(parents=True)

        linker.link_downstream_artifacts("current", "down")

        manifest = json.loads((target_io / ArtifactLinker.MANIFEST_FILENAME).read_text())
        assert manifest["upstream_workflow"] == "current"
