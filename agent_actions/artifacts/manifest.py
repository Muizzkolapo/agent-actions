"""Manifest artifact capturing project structure."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .base import BaseArtifact, ArtifactMetadata


class ManifestArtifact(BaseArtifact):
    """Project manifest capturing agents and workflows."""

    def __init__(self, project_name: str, project_path: str, metadata: Optional[ArtifactMetadata] = None) -> None:
        super().__init__(metadata)
        self.project_name = project_name
        self.project_path = project_path
        self.agents: Dict[str, Dict[str, Any]] = {}
        self.workflows: Dict[str, Dict[str, Any]] = {}
        self.dependencies: Dict[str, List[str]] = {}
        self.project_config: Dict[str, Any] = {}

    def add_agent(self, unique_id: str, agent_config: Dict[str, Any]) -> None:
        self.agents[unique_id] = {
            "unique_id": unique_id,
            "name": agent_config.get("name", unique_id.split(".")[-1]),
            "agent_type": agent_config.get("agent_type"),
            "model_vendor": agent_config.get("model_vendor"),
            "model_name": agent_config.get("model_name"),
            "config": agent_config,
            "depends_on": agent_config.get("depends_on", []),
            "tags": agent_config.get("tags", []),
            "meta": agent_config.get("meta", {}),
            "interceptors": agent_config.get("interceptors", []),
        }

    def add_workflow(self, unique_id: str, workflow_config: Dict[str, Any]) -> None:
        self.workflows[unique_id] = {
            "unique_id": unique_id,
            "name": workflow_config.get("name", unique_id.split(".")[-1]),
            "agents": workflow_config.get("agents", []),
            "dependencies": workflow_config.get("dependencies", []),
            "config": workflow_config,
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "metadata": {
                **self.metadata.to_dict(),
                "project_name": self.project_name,
                "project_path": self.project_path,
            },
            "agents": self.agents,
            "workflows": self.workflows,
            "dependencies": self.dependencies,
            "project_config": self.project_config,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ManifestArtifact":
        metadata = data["metadata"]
        obj = cls(project_name=metadata["project_name"], project_path=metadata["project_path"])
        obj.agents = data.get("agents", {})
        obj.workflows = data.get("workflows", {})
        obj.dependencies = data.get("dependencies", {})
        obj.project_config = data.get("project_config", {})
        return obj
