"""Manager for artifact persistence."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import threading
import logging
import time
import os
from pathlib import Path
from typing import Any, Dict, Optional

from .manifest import ManifestArtifact
from .run_results import RunResultsArtifact, AgentResult
from .catalog import AgentCatalogArtifact
from .validation_results import ValidationResultsArtifact
from .base import SecurityError


class ArtifactManager:
    """Manage creation and persistence of artifacts."""
    
    # Security limits
    MAX_AGENT_ID_LENGTH = 100
    MAX_VALIDATOR_TYPE_LENGTH = 50
    MAX_ERROR_MESSAGE_LENGTH = 1000
    MAX_RESULTS_COUNT = 10000

    def __init__(self, project_path: Path) -> None:
        self.project_path = project_path
        self.artifacts_dir = project_path / "artifacts"
        self.current_run_id = self._generate_run_id()
        self.current_run_dir = self.artifacts_dir / "runs" / self.current_run_id
        self._lock = threading.Lock()
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        
        # Performance optimization: track if artifacts need saving
        self._artifacts_dirty = False
        self._save_on_change = os.getenv('AGENT_ACTIONS_SAVE_ARTIFACTS_IMMEDIATELY', 'false').lower() == 'true'

        self._logger.info(f"Initializing ArtifactManager for run {self.current_run_id}")
        
        self.artifacts_dir.mkdir(exist_ok=True)
        self.current_run_dir.mkdir(parents=True, exist_ok=True)

        self.run_results = RunResultsArtifact()
        self.validation_results = ValidationResultsArtifact()
        self.manifest: Optional[ManifestArtifact] = None
        self.catalog: Optional[AgentCatalogArtifact] = None
        
        self._logger.debug(f"ArtifactManager initialized with artifacts dir: {self.artifacts_dir}")

    def _generate_run_id(self) -> str:
        return datetime.now().strftime("run_%Y%m%d_%H%M%S")

    def _mark_dirty(self) -> None:
        """Mark artifacts as needing to be saved."""
        self._artifacts_dirty = True
    
    def set_manifest(self, manifest: ManifestArtifact) -> None:
        with self._lock:
            self.manifest = manifest
            self._mark_dirty()

    def _validate_agent_id(self, agent_id: str) -> None:
        """Validate agent ID for security."""
        if not agent_id or not isinstance(agent_id, str):
            raise SecurityError("Agent ID must be a non-empty string")
        if len(agent_id) > self.MAX_AGENT_ID_LENGTH:
            raise SecurityError(f"Agent ID too long (max {self.MAX_AGENT_ID_LENGTH} chars)")
        if not agent_id.replace(".", "").replace("_", "").replace("-", "").isalnum():
            raise SecurityError("Agent ID contains invalid characters")
    
    def _validate_validator_type(self, validator_type: str) -> None:
        """Validate validator type for security."""
        if not validator_type or not isinstance(validator_type, str):
            raise SecurityError("Validator type must be a non-empty string")
        if len(validator_type) > self.MAX_VALIDATOR_TYPE_LENGTH:
            raise SecurityError(f"Validator type too long (max {self.MAX_VALIDATOR_TYPE_LENGTH} chars)")
        if not validator_type.replace("_", "").isalnum():
            raise SecurityError("Validator type contains invalid characters")
    
    def _check_results_limit(self) -> None:
        """Check if we're approaching the results limit."""
        if len(self.run_results.results) >= self.MAX_RESULTS_COUNT:
            raise SecurityError(f"Too many results (max {self.MAX_RESULTS_COUNT})")

    def record_agent_start(self, unique_id: str) -> AgentResult:
        self._validate_agent_id(unique_id)
        with self._lock:
            self._check_results_limit()
            result = AgentResult(unique_id)
            result.thread_id = threading.current_thread().name
            compile_timing = result.add_timing("compile")
            compile_timing.start()
            self.run_results.add_result(result)
            self._mark_dirty()
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
            self._mark_dirty()

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
            self._mark_dirty()

    def record_validation_attempt(
        self,
        agent_id: str,
        validator_type: str,
        attempt: int,
        status: str,
        error: Optional[str] = None,
        response: Optional[str] = None,
    ) -> None:
        # Input validation
        self._validate_agent_id(agent_id)
        self._validate_validator_type(validator_type)
        
        if not isinstance(attempt, int) or attempt < 1:
            raise SecurityError("Attempt must be a positive integer")
        
        if not status or not isinstance(status, str):
            raise SecurityError("Status must be a non-empty string")
        
        if error and len(error) > self.MAX_ERROR_MESSAGE_LENGTH:
            error = error[:self.MAX_ERROR_MESSAGE_LENGTH] + "... (truncated)"
        
        if response and len(response) > self.MAX_ERROR_MESSAGE_LENGTH:
            response = response[:self.MAX_ERROR_MESSAGE_LENGTH] + "... (truncated)"
        
        # CRITICAL FIX: Add thread safety protection
        with self._lock:
            self.validation_results.add_attempt(agent_id, validator_type, attempt, status, error, response)
            self._mark_dirty()

    def save_artifacts(self, force: bool = False) -> None:
        """Save all artifacts with comprehensive error handling."""
        # Performance optimization: only save if dirty or forced
        if not force and not self._artifacts_dirty:
            self._logger.debug("Skipping artifact save - no changes detected")
            return
            
        with self._lock:
            try:
                start_time = time.time()
                self._logger.info("Starting artifact save process")
                saved_artifacts = []
                
                # Save main artifacts
                self.run_results.save(self.artifacts_dir / "run_results.json")
                saved_artifacts.append("run_results.json")
                
                self.validation_results.save(self.artifacts_dir / "validation_results.json")
                saved_artifacts.append("validation_results.json")
                
                if self.manifest:
                    self.manifest.save(self.artifacts_dir / "manifest.json")
                    saved_artifacts.append("manifest.json")
                
                if self.catalog:
                    self.catalog.save(self.artifacts_dir / "agent_catalog.json")
                    saved_artifacts.append("agent_catalog.json")
                
                # Save run-specific copies only if enabled (performance optimization)
                if os.getenv('AGENT_ACTIONS_SAVE_RUN_COPIES', 'true').lower() == 'true':
                    self.current_run_dir.mkdir(parents=True, exist_ok=True)
                    self.run_results.save(self.current_run_dir / "run_results.json")
                    self.validation_results.save(self.current_run_dir / "validation_results.json")
                
                # Mark as clean
                self._artifacts_dirty = False
                
                save_time = time.time() - start_time
                self._logger.info(f"Successfully saved artifacts in {save_time:.3f}s: {', '.join(saved_artifacts)}")
                
                # Log performance warning if save is too slow
                if save_time > 0.1:
                    self._logger.warning(f"Artifact save took {save_time:.3f}s - consider performance optimizations")
                
            except Exception as e:
                self._logger.error(f"Failed to save artifacts: {e}")
                raise

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
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        error_file = self.current_run_dir / "error_context.json"
        with open(error_file, "w", encoding="utf-8") as fh:
            json.dump(error_context, fh, indent=2)
