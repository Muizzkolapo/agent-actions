"""
Tests for ManifestManager.

Covers initialization, action tracking, thread safety, and error handling.
"""

import json
import tempfile
import threading
import time
from pathlib import Path

import pytest

from agent_actions.workflow.managers.manifest import (
    MANIFEST_FILENAME,
    MANIFEST_SCHEMA_VERSION,
    DuplicateActionError,
    ManifestManager,
)


@pytest.fixture
def temp_agent_io():
    """Create a temporary agent_io directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def manifest_manager(temp_agent_io):
    """Create a ManifestManager instance."""
    return ManifestManager(temp_agent_io)


@pytest.fixture
def sample_workflow_data():
    """Sample data for initializing a workflow."""
    return {
        "workflow_name": "test_workflow",
        "execution_order": ["extract", "transform", "load"],
        "levels": [["extract"], ["transform"], ["load"]],
        "action_configs": {
            "extract": {"idx": 0, "dependencies": []},
            "transform": {"idx": 1, "dependencies": ["extract"]},
            "load": {"idx": 2, "dependencies": ["transform"]},
        },
    }


class TestManifestManagerInitialization:
    """Tests for ManifestManager initialization."""

    def test_init_creates_paths(self, temp_agent_io):
        """Should set up paths correctly."""
        manager = ManifestManager(temp_agent_io)

        assert manager.agent_io_path == temp_agent_io
        assert manager.target_dir == temp_agent_io / "target"
        assert manager.manifest_path == temp_agent_io / "target" / MANIFEST_FILENAME

    def test_init_accepts_string_path(self, temp_agent_io):
        """Should accept string path and convert to Path."""
        manager = ManifestManager(str(temp_agent_io))

        assert isinstance(manager.agent_io_path, Path)
        assert manager.agent_io_path == temp_agent_io

    def test_manifest_property_loads_lazily(self, manifest_manager):
        """Manifest should only load when accessed."""
        assert manifest_manager._manifest is None

        # Access manifest property
        _ = manifest_manager.manifest

        # Should have loaded (empty dict for non-existent file)
        assert manifest_manager._manifest == {}


class TestManifestInitialization:
    """Tests for initialize_manifest method."""

    def test_initialize_creates_manifest(self, manifest_manager, sample_workflow_data):
        """Should create a valid manifest file."""
        manifest_manager.initialize_manifest(**sample_workflow_data)

        assert manifest_manager.manifest_path.exists()
        assert manifest_manager._manifest is not None
        assert manifest_manager._manifest["schema_version"] == MANIFEST_SCHEMA_VERSION

    def test_initialize_sets_workflow_metadata(self, manifest_manager, sample_workflow_data):
        """Should set workflow name and status."""
        manifest_manager.initialize_manifest(**sample_workflow_data)

        assert manifest_manager.manifest["workflow_name"] == "test_workflow"
        assert manifest_manager.manifest["status"] == "running"
        assert manifest_manager.manifest["started_at"] is not None
        assert manifest_manager.manifest["completed_at"] is None

    def test_initialize_creates_action_entries(self, manifest_manager, sample_workflow_data):
        """Should create entries for all actions."""
        manifest_manager.initialize_manifest(**sample_workflow_data)

        actions = manifest_manager.manifest["actions"]
        assert len(actions) == 3
        assert "extract" in actions
        assert "transform" in actions
        assert "load" in actions

    def test_action_entries_have_correct_structure(self, manifest_manager, sample_workflow_data):
        """Each action entry should have required fields."""
        manifest_manager.initialize_manifest(**sample_workflow_data)

        extract = manifest_manager.manifest["actions"]["extract"]
        assert extract["index"] == 0
        assert extract["level"] == 0
        assert extract["status"] == "pending"
        assert extract["output_dir"] == "extract"
        assert extract["dependencies"] == []
        assert extract["started_at"] is None
        assert extract["completed_at"] is None

    def test_action_dependencies_are_stored(self, manifest_manager, sample_workflow_data):
        """Should store action dependencies correctly."""
        manifest_manager.initialize_manifest(**sample_workflow_data)

        transform = manifest_manager.manifest["actions"]["transform"]
        assert transform["dependencies"] == ["extract"]

    def test_creates_target_directory(self, manifest_manager, sample_workflow_data):
        """Should create target directory if it doesn't exist."""
        assert not manifest_manager.target_dir.exists()

        manifest_manager.initialize_manifest(**sample_workflow_data)

        assert manifest_manager.target_dir.exists()

    def test_custom_workflow_run_id(self, manifest_manager, sample_workflow_data):
        """Should accept custom workflow run ID."""
        manifest_manager.initialize_manifest(
            **sample_workflow_data,
            workflow_run_id="custom_run_123",
        )

        assert manifest_manager.manifest["workflow_run_id"] == "custom_run_123"


class TestDuplicateActionValidation:
    """Tests for duplicate action name detection."""

    def test_raises_on_duplicate_actions(self, manifest_manager):
        """Should raise DuplicateActionError for duplicate action names."""
        with pytest.raises(DuplicateActionError) as exc_info:
            manifest_manager.initialize_manifest(
                workflow_name="test",
                execution_order=["action_a", "action_b", "action_a"],
                levels=[["action_a", "action_b", "action_a"]],
                action_configs={},
            )

        assert "action_a" in str(exc_info.value)
        assert "Duplicate action names detected" in str(exc_info.value)

    def test_raises_on_multiple_duplicates(self, manifest_manager):
        """Should report all duplicates."""
        with pytest.raises(DuplicateActionError) as exc_info:
            manifest_manager.initialize_manifest(
                workflow_name="test",
                execution_order=["a", "b", "a", "b", "c"],
                levels=[["a", "b", "a", "b", "c"]],
                action_configs={},
            )

        error_msg = str(exc_info.value)
        assert "a" in error_msg
        assert "b" in error_msg

    def test_allows_unique_actions(self, manifest_manager, sample_workflow_data):
        """Should not raise for unique action names."""
        # Should not raise
        manifest_manager.initialize_manifest(**sample_workflow_data)

        assert len(manifest_manager.manifest["actions"]) == 3


class TestActionStatusTracking:
    """Tests for action status marking methods."""

    def test_mark_action_started(self, manifest_manager, sample_workflow_data):
        """Should mark action as running."""
        manifest_manager.initialize_manifest(**sample_workflow_data)
        manifest_manager.mark_action_started("extract")

        action = manifest_manager.manifest["actions"]["extract"]
        assert action["status"] == "running"
        assert action["started_at"] is not None

    def test_mark_action_completed(self, manifest_manager, sample_workflow_data):
        """Should mark action as completed."""
        manifest_manager.initialize_manifest(**sample_workflow_data)
        manifest_manager.mark_action_completed("extract", record_count=100)

        action = manifest_manager.manifest["actions"]["extract"]
        assert action["status"] == "completed"
        assert action["completed_at"] is not None
        assert action["record_count"] == 100

    def test_mark_action_skipped(self, manifest_manager, sample_workflow_data):
        """Should mark action as skipped with reason."""
        manifest_manager.initialize_manifest(**sample_workflow_data)
        manifest_manager.mark_action_skipped("extract", reason="No input data")

        action = manifest_manager.manifest["actions"]["extract"]
        assert action["status"] == "skipped"
        assert action["skip_reason"] == "No input data"

    def test_mark_action_failed(self, manifest_manager, sample_workflow_data):
        """Should mark action as failed with error."""
        manifest_manager.initialize_manifest(**sample_workflow_data)
        manifest_manager.mark_action_failed("extract", error="Connection timeout")

        action = manifest_manager.manifest["actions"]["extract"]
        assert action["status"] == "failed"
        assert action["error"] == "Connection timeout"

    def test_mark_unknown_action_raises(self, manifest_manager, sample_workflow_data):
        """Should raise KeyError for unknown action."""
        manifest_manager.initialize_manifest(**sample_workflow_data)

        with pytest.raises(KeyError) as exc_info:
            manifest_manager.mark_action_started("nonexistent")

        assert "nonexistent" in str(exc_info.value)

    def test_mark_completed_unknown_action_raises(self, manifest_manager, sample_workflow_data):
        """Should raise KeyError for unknown action on completed."""
        manifest_manager.initialize_manifest(**sample_workflow_data)

        with pytest.raises(KeyError):
            manifest_manager.mark_action_completed("nonexistent")

    def test_mark_skipped_unknown_action_raises(self, manifest_manager, sample_workflow_data):
        """Should raise KeyError for unknown action on skipped."""
        manifest_manager.initialize_manifest(**sample_workflow_data)

        with pytest.raises(KeyError):
            manifest_manager.mark_action_skipped("nonexistent")

    def test_mark_failed_unknown_action_raises(self, manifest_manager, sample_workflow_data):
        """Should raise KeyError for unknown action on failed."""
        manifest_manager.initialize_manifest(**sample_workflow_data)

        with pytest.raises(KeyError):
            manifest_manager.mark_action_failed("nonexistent", "error")


class TestWorkflowStatusTracking:
    """Tests for workflow-level status marking."""

    def test_mark_workflow_completed(self, manifest_manager, sample_workflow_data):
        """Should mark workflow as completed."""
        manifest_manager.initialize_manifest(**sample_workflow_data)
        manifest_manager.mark_workflow_completed()

        assert manifest_manager.manifest["status"] == "completed"
        assert manifest_manager.manifest["completed_at"] is not None

    def test_mark_workflow_failed(self, manifest_manager, sample_workflow_data):
        """Should mark workflow as failed with error."""
        manifest_manager.initialize_manifest(**sample_workflow_data)
        manifest_manager.mark_workflow_failed("Pipeline crashed")

        assert manifest_manager.manifest["status"] == "failed"
        assert manifest_manager.manifest["error"] == "Pipeline crashed"


class TestDirectoryResolution:
    """Tests for directory path resolution methods."""

    def test_get_output_directory(self, manifest_manager, sample_workflow_data):
        """Should return correct output directory path."""
        manifest_manager.initialize_manifest(**sample_workflow_data)

        output_dir = manifest_manager.get_output_directory("extract")

        assert output_dir == manifest_manager.target_dir / "extract"

    def test_get_output_directory_unknown_raises(self, manifest_manager, sample_workflow_data):
        """Should raise KeyError for unknown action."""
        manifest_manager.initialize_manifest(**sample_workflow_data)

        with pytest.raises(KeyError) as exc_info:
            manifest_manager.get_output_directory("nonexistent")

        assert "nonexistent" in str(exc_info.value)

    def test_get_dependency_directories(self, manifest_manager, sample_workflow_data):
        """Should return paths to all dependency directories."""
        manifest_manager.initialize_manifest(**sample_workflow_data)

        deps = manifest_manager.get_dependency_directories("transform")

        assert len(deps) == 1
        assert deps[0] == manifest_manager.target_dir / "extract"

    def test_get_dependency_directories_no_deps(self, manifest_manager, sample_workflow_data):
        """Should return empty list for action without dependencies."""
        manifest_manager.initialize_manifest(**sample_workflow_data)

        deps = manifest_manager.get_dependency_directories("extract")

        assert deps == []

    def test_get_previous_action_directory(self, manifest_manager, sample_workflow_data):
        """Should return previous action's directory."""
        manifest_manager.initialize_manifest(**sample_workflow_data)

        prev_dir = manifest_manager.get_previous_action_directory("transform")

        assert prev_dir == manifest_manager.target_dir / "extract"

    def test_get_previous_action_directory_first(self, manifest_manager, sample_workflow_data):
        """Should return None for first action."""
        manifest_manager.initialize_manifest(**sample_workflow_data)

        prev_dir = manifest_manager.get_previous_action_directory("extract")

        assert prev_dir is None


class TestQueryMethods:
    """Tests for manifest query methods."""

    def test_get_parallel_actions(self, manifest_manager):
        """Should return actions at a given level."""
        manifest_manager.initialize_manifest(
            workflow_name="test",
            execution_order=["a", "b", "c", "d"],
            levels=[["a"], ["b", "c"], ["d"]],
            action_configs={},
        )

        level_1 = manifest_manager.get_parallel_actions(1)

        assert set(level_1) == {"b", "c"}

    def test_get_action_index(self, manifest_manager, sample_workflow_data):
        """Should return execution index."""
        manifest_manager.initialize_manifest(**sample_workflow_data)

        assert manifest_manager.get_action_index("extract") == 0
        assert manifest_manager.get_action_index("transform") == 1
        assert manifest_manager.get_action_index("load") == 2

    def test_is_action_completed(self, manifest_manager, sample_workflow_data):
        """Should check completion status."""
        manifest_manager.initialize_manifest(**sample_workflow_data)

        assert not manifest_manager.is_action_completed("extract")

        manifest_manager.mark_action_completed("extract")

        assert manifest_manager.is_action_completed("extract")

    def test_is_action_skipped(self, manifest_manager, sample_workflow_data):
        """Should check skipped status."""
        manifest_manager.initialize_manifest(**sample_workflow_data)

        assert not manifest_manager.is_action_skipped("extract")

        manifest_manager.mark_action_skipped("extract")

        assert manifest_manager.is_action_skipped("extract")

    def test_get_completed_actions(self, manifest_manager, sample_workflow_data):
        """Should return list of completed actions."""
        manifest_manager.initialize_manifest(**sample_workflow_data)
        manifest_manager.mark_action_completed("extract")
        manifest_manager.mark_action_completed("transform")

        completed = manifest_manager.get_completed_actions()

        assert set(completed) == {"extract", "transform"}

    def test_get_upstream_actions(self, manifest_manager, sample_workflow_data):
        """Should return actions with lower index."""
        manifest_manager.initialize_manifest(**sample_workflow_data)

        upstream = manifest_manager.get_upstream_actions("load")

        assert upstream == ["extract", "transform"]


class TestPersistence:
    """Tests for manifest persistence (load/save)."""

    def test_saves_to_disk(self, manifest_manager, sample_workflow_data):
        """Should save manifest to disk."""
        manifest_manager.initialize_manifest(**sample_workflow_data)

        with open(manifest_manager.manifest_path) as f:
            saved = json.load(f)

        assert saved["workflow_name"] == "test_workflow"
        assert len(saved["actions"]) == 3

    def test_loads_from_disk(self, temp_agent_io, sample_workflow_data):
        """Should load existing manifest on access."""
        # Create and save manifest
        manager1 = ManifestManager(temp_agent_io)
        manager1.initialize_manifest(**sample_workflow_data)
        manager1.mark_action_completed("extract")

        # New manager instance should load from disk
        manager2 = ManifestManager(temp_agent_io)

        assert manager2.manifest["actions"]["extract"]["status"] == "completed"

    def test_atomic_write(self, manifest_manager, sample_workflow_data):
        """Save should be atomic (no partial writes)."""
        manifest_manager.initialize_manifest(**sample_workflow_data)

        # Simulate crash during save by checking temp file cleanup
        _initial_files = set(manifest_manager.target_dir.glob("*"))

        manifest_manager.mark_action_completed("extract")

        final_files = set(manifest_manager.target_dir.glob("*"))
        temp_files = [f for f in final_files if f.suffix == ".tmp"]

        assert len(temp_files) == 0, "Temp files should be cleaned up"

    def test_clear_manifest(self, manifest_manager, sample_workflow_data):
        """Should remove manifest file."""
        manifest_manager.initialize_manifest(**sample_workflow_data)
        assert manifest_manager.manifest_path.exists()

        manifest_manager.clear_manifest()

        assert not manifest_manager.manifest_path.exists()
        assert manifest_manager._manifest is None

    def test_has_manifest(self, manifest_manager, sample_workflow_data):
        """Should check if manifest file exists."""
        assert not manifest_manager.has_manifest()

        manifest_manager.initialize_manifest(**sample_workflow_data)

        assert manifest_manager.has_manifest()


class TestThreadSafety:
    """Tests for thread safety of manifest operations."""

    def test_concurrent_action_updates(self, manifest_manager):
        """Should handle concurrent action status updates."""
        # Create workflow with many actions
        actions = [f"action_{i}" for i in range(10)]
        manifest_manager.initialize_manifest(
            workflow_name="test",
            execution_order=actions,
            levels=[actions],
            action_configs={a: {"idx": i} for i, a in enumerate(actions)},
        )

        errors = []

        def mark_completed(action_name):
            try:
                manifest_manager.mark_action_started(action_name)
                time.sleep(0.01)  # Small delay to increase chance of race
                manifest_manager.mark_action_completed(action_name, record_count=100)
            except Exception as e:
                errors.append(e)

        # Run concurrent updates
        threads = [threading.Thread(target=mark_completed, args=(action,)) for action in actions]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All actions should be completed
        assert len(errors) == 0, f"Errors: {errors}"
        for action in actions:
            assert manifest_manager.is_action_completed(action)

    def test_manifest_property_loads_once_under_contention(self, temp_agent_io):
        """Concurrent access to manifest property should call load_manifest only once."""
        manager = ManifestManager(temp_agent_io)
        load_count = 0
        original_load = manager.load_manifest

        def counting_load():
            nonlocal load_count
            load_count += 1
            time.sleep(0.05)  # Slow down to widen the race window
            return original_load()

        manager.load_manifest = counting_load

        barrier = threading.Barrier(10)
        errors = []

        def access_manifest():
            try:
                barrier.wait()
                _ = manager.manifest
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=access_manifest) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Errors: {errors}"
        assert load_count == 1, f"load_manifest called {load_count} times, expected 1"

    def test_no_deadlock_when_mutation_triggers_lazy_load(
        self, temp_agent_io, sample_workflow_data
    ):
        """First mutation on a fresh manager with persisted manifest must not deadlock.

        Regression: mark_action_started holds _lock, then accesses self.manifest
        which tries to acquire the same lock for lazy loading. With a non-reentrant
        Lock this deadlocks; RLock allows re-entry.
        """
        # Persist a manifest to disk via a first manager
        manager1 = ManifestManager(temp_agent_io)
        manager1.initialize_manifest(**sample_workflow_data)

        # Create a fresh manager (manifest not yet loaded into memory)
        manager2 = ManifestManager(temp_agent_io)
        assert manager2._manifest is None  # not loaded yet

        # This must complete without deadlock — use a timeout to detect hangs
        result = [None]
        error = [None]

        def mutate():
            try:
                manager2.mark_action_started("extract")
                result[0] = manager2.manifest["actions"]["extract"]["status"]
            except Exception as e:
                error[0] = e

        t = threading.Thread(target=mutate, daemon=True)
        t.start()
        t.join(timeout=5)

        assert not t.is_alive(), "mark_action_started deadlocked (thread still alive after 5s)"
        assert error[0] is None, f"Unexpected error: {error[0]}"
        assert result[0] == "running"

    def test_concurrent_read_write(self, manifest_manager):
        """Should handle concurrent reads and writes."""
        actions = [f"action_{i}" for i in range(5)]
        manifest_manager.initialize_manifest(
            workflow_name="test",
            execution_order=actions,
            levels=[actions],
            action_configs={a: {"idx": i} for i, a in enumerate(actions)},
        )

        read_results = []
        errors = []

        def writer(action_name):
            try:
                manifest_manager.mark_action_completed(action_name)
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(10):
                    completed = manifest_manager.get_completed_actions()
                    read_results.append(len(completed))
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        # Start readers and writers concurrently
        threads = []
        for action in actions:
            threads.append(threading.Thread(target=writer, args=(action,)))
        for _ in range(3):
            threads.append(threading.Thread(target=reader))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Errors: {errors}"


class TestSchemaVersioning:
    """Tests for schema version handling."""

    pass
