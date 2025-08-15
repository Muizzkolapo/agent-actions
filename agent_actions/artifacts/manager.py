"""Manager for artifact persistence."""

from __future__ import annotations

from datetime import datetime
import json
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from .manifest import ManifestArtifact
from .run_results import RunResultsArtifact, AgentResult
from .catalog import AgentCatalogArtifact
from .validation_results import ValidationResultsArtifact


class ArtifactManager:
    """Manage creation and persistence of artifacts."""

    def __init__(self, project_path: Path) -> None:
        self.project_path = project_path
        self.artifacts_dir = project_path / "artifacts"
        self.current_run_id = self._generate_run_id()
        self.current_run_dir = self.artifacts_dir / "runs" / self.current_run_id
        self._lock = threading.Lock()

        self.artifacts_dir.mkdir(exist_ok=True)
        self.current_run_dir.mkdir(parents=True, exist_ok=True)

        self.run_results = RunResultsArtifact()
        self.validation_results = ValidationResultsArtifact()
        self.manifest: Optional[ManifestArtifact] = None
        self.catalog: Optional[AgentCatalogArtifact] = None

    def _generate_run_id(self) -> str:
        return datetime.now().strftime("run_%Y%m%d_%H%M%S")

    def set_manifest(self, manifest: ManifestArtifact) -> None:
        with self._lock:
            self.manifest = manifest

    def record_agent_start(self, unique_id: str) -> AgentResult:
        with self._lock:
            result = AgentResult(unique_id)
            result.thread_id = threading.current_thread().name
            compile_timing = result.add_timing("compile")
            compile_timing.start()
            self.run_results.add_result(result)
            return result

    def record_agent_success(
        self,
        result: AgentResult,
        response: Any,
        execution_time: float,
        adapter_response: Optional[Dict[str, Any]] = None,
    ) -> None:
        with self._lock:
            result.status = "success"
            result.execution_time = execution_time
            result.message = "Completed successfully"
            result.adapter_response = adapter_response or {}
            if result.timing:
                result.timing[-1].complete()

    def record_agent_error(
        self,
        result: AgentResult,
        error: Exception,
        execution_time: float,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        with self._lock:
            result.status = "error"
            result.execution_time = execution_time
            result.message = str(error)
            result.failures = 1
            result.error_details = {
                "error_type": type(error).__name__,
                "error_message": str(error),
                "context": context or {},
            }
            if result.timing:
                result.timing[-1].complete()

    def record_validation_attempt(
        self,
        agent_id: str,
        validator_type: str,
        attempt: int,
        status: str,
        error: Optional[str] = None,
        response: Optional[str] = None,
    ) -> None:
        self.validation_results.add_attempt(agent_id, validator_type, attempt, status, error, response)

    def save_artifacts(self) -> None:
        with self._lock:
            self.run_results.save(self.artifacts_dir / "run_results.json")
            self.validation_results.save(self.artifacts_dir / "validation_results.json")
            if self.manifest:
                self.manifest.save(self.artifacts_dir / "manifest.json")
            if self.catalog:
                self.catalog.save(self.artifacts_dir / "agent_catalog.json")
            # run-specific location
            self.current_run_dir.mkdir(parents=True, exist_ok=True)
            self.run_results.save(self.current_run_dir / "run_results.json")
            self.validation_results.save(self.current_run_dir / "validation_results.json")

    def record_error(
        self,
        error_type: str,
        operation: str,
        target: str,
        error: Exception,
        context: Optional[Dict[str, Any]] = None,
        user_message: Optional[str] = None,
    ) -> None:
        error_context = {
            "error_type": error_type,
            "operation": operation,
            "target": target,
            "error_class": type(error).__name__,
            "error_message": str(error),
            "context": context or {},
            "user_message": user_message,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
        error_file = self.current_run_dir / "error_context.json"
        with open(error_file, "w", encoding="utf-8") as fh:
            json.dump(error_context, fh, indent=2)
