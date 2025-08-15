from __future__ import annotations

import json
from pathlib import Path

from agent_actions.artifacts.base import BaseArtifact
from agent_actions.artifacts.manifest import ManifestArtifact
from agent_actions.artifacts.run_results import AgentResult, RunResultsArtifact
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
