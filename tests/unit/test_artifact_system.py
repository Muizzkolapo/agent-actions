from __future__ import annotations

import json
import pytest
from pathlib import Path

from agent_actions.core.contracts.base import BaseArtifact, SecurityError
from agent_actions.artifacts.manifest import ManifestArtifact
from agent_actions.artifacts.run_results import AgentResult, RunResultsArtifact, ExecutionTiming
from agent_actions.artifacts.catalog import AgentCatalogArtifact
from agent_actions.artifacts.validation_results import ValidationResultsArtifact
from agent_actions.artifacts.manager import ArtifactManager


class DummyArtifact(BaseArtifact):
    """Simple artifact used for testing save/load."""

    def __init__(self, value: str) -> None:
        super().__init__()
        self.value = value

    def to_dict(self):  # type: ignore[override]
        return {"metadata": self.metadata.to_dict(), "value": self.value}

    @classmethod
    def from_dict(cls, data):  # type: ignore[override]
        return cls(data["value"])


def test_base_artifact_save_and_load(tmp_path: Path) -> None:
    artifact = DummyArtifact("hello")
    path = tmp_path / "artifact.json"
    artifact.save(path)
    loaded = DummyArtifact.load(path)
    assert isinstance(loaded, DummyArtifact)
    assert loaded.value == "hello"


def test_manifest_additions() -> None:
    manifest = ManifestArtifact("proj", "/tmp")
    manifest.add_agent("proj.agent", {"agent_type": "llm"})
    manifest.add_workflow("proj.flow", {"agents": ["proj.agent"]})
    data = manifest.to_dict()
    assert "proj.agent" in data["agents"]
    assert data["workflows"]["proj.flow"]["agents"] == ["proj.agent"]


def test_artifact_manager_records_success(tmp_path: Path) -> None:
    manager = ArtifactManager(tmp_path)
    manifest = ManifestArtifact("proj", str(tmp_path))
    manager.set_manifest(manifest)
    result = manager.record_agent_start("proj.agent")
    manager.record_agent_success(result, response={}, execution_time=0.1)
    manager.save_artifacts()
    run_file = tmp_path / "artifacts" / "run_results.json"
    assert run_file.exists()
    data = json.load(open(run_file))
    assert data["results"][0]["status"] == "success"


# NEW TESTS FOR CRITICAL FIXES

def test_run_results_data_persistence(tmp_path: Path) -> None:
    """Test that RunResultsArtifact properly saves and loads result data."""
    # Create artifact with results
    artifact = RunResultsArtifact()
    artifact.elapsed_time = 5.5
    artifact.args = {"test": "value"}
    
    # Add agent results
    result1 = AgentResult("agent1")
    result1.status = "success"
    result1.execution_time = 2.3
    result1.message = "Completed"
    result1.failures = 0
    result1.adapter_response = {"output": "test"}
    
    # Add timing data
    timing = result1.add_timing("compile")
    timing.start()
    timing.complete()
    
    artifact.add_result(result1)
    
    # Save and load
    path = tmp_path / "test_results.json"
    artifact.save(path)
    loaded = RunResultsArtifact.load(path)
    
    # Verify data is preserved
    assert loaded.elapsed_time == 5.5
    assert loaded.args == {"test": "value"}
    assert len(loaded.results) == 1
    
    loaded_result = loaded.results[0]
    assert loaded_result.unique_id == "agent1"
    assert loaded_result.status == "success"
    assert loaded_result.execution_time == 2.3
    assert loaded_result.message == "Completed"
    assert loaded_result.failures == 0
    assert loaded_result.adapter_response == {"output": "test"}
    assert len(loaded_result.timing) == 1
    assert loaded_result.timing[0].name == "compile"
    assert loaded_result.timing[0].started_at is not None
    assert loaded_result.timing[0].completed_at is not None


def test_validation_results_data_persistence(tmp_path: Path) -> None:
    """Test that ValidationResultsArtifact properly saves and loads data."""
    artifact = ValidationResultsArtifact()
    artifact.add_attempt("agent1", "json_validator", 1, "success")
    artifact.add_attempt("agent1", "json_validator", 2, "error", "Invalid format", "bad json")
    
    path = tmp_path / "test_validation.json"
    artifact.save(path)
    loaded = ValidationResultsArtifact.load(path)
    
    # Verify data is preserved
    assert "agent1" in loaded.results
    assert "json_validator" in loaded.results["agent1"]
    attempts = loaded.results["agent1"]["json_validator"]
    assert len(attempts) == 2
    assert attempts[0]["status"] == "success"
    assert attempts[1]["error"] == "Invalid format"


def test_catalog_data_persistence(tmp_path: Path) -> None:
    """Test that AgentCatalogArtifact properly saves and loads data."""
    artifact = AgentCatalogArtifact()
    artifact.add_agent("agent1", {"type": "llm", "model": "gpt-4"})
    artifact.add_agent("agent2", {"type": "tool", "function": "calculator"})
    
    path = tmp_path / "test_catalog.json"
    artifact.save(path)
    loaded = AgentCatalogArtifact.load(path)
    
    # Verify data is preserved
    assert len(loaded.agents) == 2
    assert loaded.agents["agent1"]["type"] == "llm"
    assert loaded.agents["agent2"]["function"] == "calculator"


def test_manifest_metadata_preservation(tmp_path: Path) -> None:
    """Test that ManifestArtifact preserves metadata correctly."""
    manifest = ManifestArtifact("test_project", "/tmp/test")
    manifest.add_agent("agent1", {"type": "llm"})
    manifest.add_workflow("workflow1", {"agents": ["agent1"]})
    
    path = tmp_path / "test_manifest.json"
    manifest.save(path)
    loaded = ManifestArtifact.load(path)
    
    # Verify core data
    assert loaded.project_name == "test_project"
    assert loaded.project_path == "/tmp/test"
    assert "agent1" in loaded.agents
    assert "workflow1" in loaded.workflows
    
    # Verify metadata is preserved
    assert loaded.metadata.generated_at == manifest.metadata.generated_at
    assert loaded.metadata.invocation_id == manifest.metadata.invocation_id


def test_security_path_validation(tmp_path: Path) -> None:
    """Test path traversal security validation."""
    artifact = DummyArtifact("test")
    
    # Test path traversal attempts
    with pytest.raises(SecurityError):
        artifact.save(tmp_path / "../../../etc/passwd")
    
    # Test invalid extensions
    with pytest.raises(SecurityError):
        artifact.save(tmp_path / "test.exe")
    
    # Test valid path works
    valid_path = tmp_path / "valid.json"
    artifact.save(valid_path)  # Should not raise
    assert valid_path.exists()


def test_security_file_size_limits(tmp_path: Path) -> None:
    """Test file size security limits."""
    # Create large content
    large_artifact = DummyArtifact("x" * (11 * 1024 * 1024))  # 11MB > 10MB limit
    
    with pytest.raises(SecurityError, match="Content too large"):
        large_artifact.save(tmp_path / "large.json")


def test_security_input_validation() -> None:
    """Test input validation in ArtifactManager."""
    from tempfile import TemporaryDirectory
    
    with TemporaryDirectory() as tmpdir:
        manager = ArtifactManager(Path(tmpdir))
        
        # Test invalid agent IDs
        with pytest.raises(SecurityError, match="Agent ID must be"):
            manager.record_agent_start("")
        
        with pytest.raises(SecurityError, match="Agent ID too long"):
            manager.record_agent_start("x" * 200)
        
        with pytest.raises(SecurityError, match="invalid characters"):
            manager.record_agent_start("agent/../../../etc")
        
        # Test invalid validator types
        with pytest.raises(SecurityError, match="Validator type must be"):
            manager.record_validation_attempt("agent1", "", 1, "success")
        
        with pytest.raises(SecurityError, match="invalid characters"):
            manager.record_validation_attempt("agent1", "validator/../bad", 1, "success")


def test_thread_safety_validation_recording(tmp_path: Path) -> None:
    """Test that validation recording is thread-safe."""
    import threading
    import time
    
    manager = ArtifactManager(tmp_path)
    results = []
    errors = []
    
    def record_validation():
        try:
            for i in range(10):
                manager.record_validation_attempt(f"agent{i}", "test_validator", i+1, "success")
                time.sleep(0.001)  # Small delay to increase chance of race condition
            results.append("success")
        except Exception as e:
            errors.append(e)
    
    # Create multiple threads
    threads = [threading.Thread(target=record_validation) for _ in range(5)]
    
    # Start all threads
    for thread in threads:
        thread.start()
    
    # Wait for completion
    for thread in threads:
        thread.join()
    
    # Verify no errors occurred
    assert len(errors) == 0, f"Thread safety errors: {errors}"
    assert len(results) == 5  # All threads completed successfully


def test_metadata_datetime_not_deprecated() -> None:
    """Test that metadata uses non-deprecated datetime methods."""
    from agent_actions.core.contracts.base import ArtifactMetadata
    import warnings
    
    # Capture warnings
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        metadata = ArtifactMetadata()
        
        # Check that no deprecation warnings were raised
        deprecation_warnings = [warning for warning in w if issubclass(warning.category, DeprecationWarning)]
        assert len(deprecation_warnings) == 0, f"Deprecation warnings found: {[str(w) for w in deprecation_warnings]}"
    
    # Verify the timestamp format is correct
    assert metadata.generated_at.endswith("Z")
    assert "T" in metadata.generated_at


def test_error_handling_malformed_json(tmp_path: Path) -> None:
    """Test error handling for malformed JSON files."""
    # Create malformed JSON file
    bad_file = tmp_path / "bad.json"
    bad_file.write_text('{"invalid": json without closing brace')
    
    with pytest.raises(SecurityError, match="Invalid JSON format"):
        RunResultsArtifact.load(bad_file)


def test_error_handling_missing_metadata(tmp_path: Path) -> None:
    """Test error handling for JSON missing metadata."""
    # Create JSON without metadata
    bad_file = tmp_path / "no_metadata.json"
    bad_file.write_text('{"data": "test"}')
    
    with pytest.raises(SecurityError, match="missing required metadata"):
        RunResultsArtifact.load(bad_file)


def test_comprehensive_artifact_workflow(tmp_path: Path) -> None:
    """Test complete artifact workflow with all fixes."""
    # Create manager and artifacts
    manager = ArtifactManager(tmp_path)
    
    # Create manifest
    manifest = ManifestArtifact("test_project", str(tmp_path))
    manifest.add_agent("test.agent", {"type": "llm", "model": "gpt-4"})
    manager.set_manifest(manifest)
    
    # Record agent execution
    result = manager.record_agent_start("test.agent")
    manager.record_agent_success(result, response={"output": "success"}, execution_time=1.5)
    
    # Record validation attempts
    manager.record_validation_attempt("test.agent", "json_validator", 1, "success")
    manager.record_validation_attempt("test.agent", "schema_validator", 1, "error", "Schema mismatch")
    
    # Save all artifacts
    manager.save_artifacts()
    
    # Verify artifacts exist and contain correct data
    artifacts_dir = tmp_path / "artifacts"
    assert (artifacts_dir / "manifest.json").exists()
    assert (artifacts_dir / "run_results.json").exists()
    assert (artifacts_dir / "validation_results.json").exists()
    
    # Load and verify run results
    loaded_run_results = RunResultsArtifact.load(artifacts_dir / "run_results.json")
    assert len(loaded_run_results.results) == 1
    assert loaded_run_results.results[0].status == "success"
    assert loaded_run_results.results[0].execution_time == 1.5
    
    # Load and verify validation results
    loaded_validation = ValidationResultsArtifact.load(artifacts_dir / "validation_results.json")
    assert "test.agent" in loaded_validation.results
    assert "json_validator" in loaded_validation.results["test.agent"]
    assert "schema_validator" in loaded_validation.results["test.agent"]
    
    # Load and verify manifest
    loaded_manifest = ManifestArtifact.load(artifacts_dir / "manifest.json")
    assert loaded_manifest.project_name == "test_project"
    assert "test.agent" in loaded_manifest.agents
