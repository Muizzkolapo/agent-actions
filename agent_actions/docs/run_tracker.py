"""
Run tracking for documentation system.

Records workflow execution data to artefact/runs.json for the docs UI.
"""

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import portalocker

from agent_actions.utilities.retry import retry


@dataclass
class RunConfig:
    """Configuration for recording a workflow run."""

    workflow_id: str
    workflow_name: str
    status: str
    started_at: str
    ended_at: Optional[str] = None
    duration_seconds: Optional[float] = None
    actions_completed: int = 0
    actions_total: int = 0
    error_message: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class ActionCompleteConfig:
    """Configuration for recording action completion."""

    run_id: str
    action_name: str
    status: str
    duration_seconds: float
    tokens: Optional[Dict[str, int]] = None
    files_processed: int = 0
    skip_reason: Optional[str] = None
    error: Optional[str] = None


class RunTracker:
    """Track workflow execution runs for documentation."""

    def __init__(self, artefact_dir: Optional[Path] = None):
        """
        Initialize run tracker.

        Args:
            artefact_dir: Directory to store runs.json (defaults to ./artefact)
        """
        self.artefact_dir = artefact_dir or Path.cwd() / "artefact"
        self.runs_file = self.artefact_dir / "runs.json"

    def _load_existing_runs(self) -> Dict[str, Any]:
        """Load existing runs data or create new structure with file locking."""
        if self.runs_file.exists():
            try:
                with portalocker.Lock(self.runs_file, "r", timeout=5) as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError, portalocker.exceptions.LockException):
                # If file is corrupted or locked, start fresh
                pass

        # Return empty structure
        return {
            "metadata": {"generated_at": datetime.now().isoformat(), "total_runs": 0},
            "executions": [],
        }

    def _save_runs(self, runs_data: Dict[str, Any]) -> None:
        """Save runs data to file with file locking to prevent concurrent write issues."""
        # Ensure directory exists
        self.artefact_dir.mkdir(parents=True, exist_ok=True)

        # Update metadata
        runs_data["metadata"]["generated_at"] = datetime.now().isoformat()
        runs_data["metadata"]["total_runs"] = len(runs_data["executions"])

        # Write to file with exclusive lock
        with portalocker.Lock(self.runs_file, "w", timeout=5) as f:
            json.dump(runs_data, f, indent=2)

    def record_run(self, *, config: RunConfig) -> str:
        """
        Record a workflow execution run with atomic file locking.

        This method ensures thread-safe and process-safe appending to runs.json
        by holding an exclusive lock during the entire read-modify-write operation.

        Args:
            config: RunConfig containing run parameters

        Returns:
            Run ID of the recorded execution
        """
        # Ensure directory exists
        self.artefact_dir.mkdir(parents=True, exist_ok=True)

        # Create file if it doesn't exist
        if not self.runs_file.exists():
            self._create_empty_runs_file()

        # Atomic read-modify-write with exclusive lock
        with portalocker.Lock(self.runs_file, "r+", timeout=10, flags=portalocker.LOCK_EX) as f:
            runs_data = self._load_runs_data_from_file(f)
            run_id = self._create_run_record(runs_data, config)
            self._write_runs_data_to_file(f, runs_data)

        return run_id

    def _create_empty_runs_file(self) -> None:
        """Create empty runs file with initial structure."""
        with open(self.runs_file, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "metadata": {"generated_at": datetime.now().isoformat(), "total_runs": 0},
                    "executions": [],
                },
                f,
            )

    def _load_runs_data_from_file(self, f) -> Dict[str, Any]:
        """Load runs data from file handle."""
        try:
            f.seek(0)
            return json.load(f)
        except (json.JSONDecodeError, IOError):
            # File is empty or corrupted, create new structure
            return {
                "metadata": {"generated_at": datetime.now().isoformat(), "total_runs": 0},
                "executions": [],
            }

    def _create_run_record(self, runs_data: Dict[str, Any], config: RunConfig) -> str:
        """Create run record and add to runs_data."""
        run_count = len(runs_data["executions"]) + 1
        run_id = f"run_{config.workflow_id}_{run_count:03d}"

        # Calculate duration if not provided
        calc_duration = config.duration_seconds
        if calc_duration is None and config.started_at and config.ended_at:
            calc_duration = self._calculate_duration(config.started_at, config.ended_at)

        # Create run record
        run_record = {
            "id": run_id,
            "workflow_id": config.workflow_id,
            "workflow_name": config.workflow_name,
            "status": config.status,
            "started_at": config.started_at,
            "ended_at": config.ended_at,
            "duration_seconds": calc_duration or 0,
            "actions_completed": config.actions_completed,
            "actions_total": config.actions_total,
        }

        # Add optional fields
        if config.error_message:
            run_record["error_message"] = config.error_message

        if config.metadata:
            run_record["metadata"] = config.metadata

        # Add to executions list (prepend to show most recent first)
        runs_data["executions"].insert(0, run_record)

        # Keep only last 100 runs to avoid file getting too large
        runs_data["executions"] = runs_data["executions"][:100]

        return run_id

    def _write_runs_data_to_file(self, f, runs_data: Dict[str, Any]) -> None:
        """Write runs data to file handle."""
        # Update metadata
        runs_data["metadata"]["generated_at"] = datetime.now().isoformat()
        runs_data["metadata"]["total_runs"] = len(runs_data["executions"])

        # Write back to file (atomically within the lock)
        f.seek(0)
        f.truncate()
        json.dump(runs_data, f, indent=2)

    def _calculate_duration(self, started_at: str, ended_at: str) -> float:
        """Calculate duration between timestamps."""
        try:
            start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            end = datetime.fromisoformat(ended_at.replace("Z", "+00:00"))
            return (end - start).total_seconds()
        except (ValueError, AttributeError):
            return 0

    def update_run(self, run_id: str, updates: Optional[Dict[str, Any]] = None) -> bool:
        """
        Update an existing run record.

        Args:
            run_id: ID of the run to update
            updates: Dict of fields to update (status, ended_at, actions_completed, error_message)

        Returns:
            True if run was found and updated, False otherwise
        """
        if updates is None:
            updates = {}

        runs_data = self._load_existing_runs()

        # Find the run
        for run in runs_data["executions"]:
            if run["id"] == run_id:
                self._apply_run_updates(run, updates)
                self._save_runs(runs_data)
                return True

        return False

    def _apply_run_updates(self, run: Dict[str, Any], updates: Dict[str, Any]) -> None:
        """Apply updates to a run record."""
        if "status" in updates:
            run["status"] = updates["status"]
        if "ended_at" in updates:
            ended_at = updates["ended_at"]
            run["ended_at"] = ended_at
            # Recalculate duration
            try:
                start = datetime.fromisoformat(run["started_at"].replace("Z", "+00:00"))
                end = datetime.fromisoformat(ended_at.replace("Z", "+00:00"))
                run["duration_seconds"] = (end - start).total_seconds()
            except (ValueError, AttributeError):
                pass
        if "actions_completed" in updates:
            run["actions_completed"] = updates["actions_completed"]
        if "error_message" in updates:
            run["error_message"] = updates["error_message"]

    def start_workflow_run(
        self, *, workflow_id: str, workflow_name: str, actions_total: int
    ) -> str:
        """
        Start tracking a new workflow run with action-level tracking support.

        Args:
            workflow_id: Unique identifier for the workflow
            workflow_name: Human-readable workflow name
            actions_total: Total number of actions in workflow

        Returns:
            run_id: Unique identifier for this run (format: run_{workflow_id}_{count:03d})
        """
        # Ensure directory exists
        self.artefact_dir.mkdir(parents=True, exist_ok=True)

        # Create file if it doesn't exist
        if not self.runs_file.exists():
            with open(self.runs_file, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "metadata": {
                            "generated_at": datetime.now().isoformat(),
                            "total_runs": 0,
                            "schema_version": "1.0",
                        },
                        "workflow_metrics": {},
                        "executions": [],
                    },
                    f,
                )

        # Atomic read-modify-write with exclusive lock
        with portalocker.Lock(self.runs_file, "r+", timeout=10, flags=portalocker.LOCK_EX) as f:
            # Load existing data
            try:
                f.seek(0)
                runs_data = json.load(f)
            except (json.JSONDecodeError, IOError):
                # File is empty or corrupted, create new structure
                runs_data = {
                    "metadata": {
                        "generated_at": datetime.now().isoformat(),
                        "total_runs": 0,
                        "schema_version": "1.0",
                    },
                    "workflow_metrics": {},
                    "executions": [],
                }

            # Ensure workflow_metrics exists
            if "workflow_metrics" not in runs_data:
                runs_data["workflow_metrics"] = {}

            # Generate run ID
            run_count = len(runs_data["executions"]) + 1
            run_id = f"run_{workflow_id}_{run_count:03d}"

            # Create run record with action-level tracking support
            run_record = {
                "id": run_id,
                "workflow_id": workflow_id,
                "workflow_name": workflow_name,
                "status": "running",
                "started_at": datetime.now().isoformat(),
                "ended_at": None,
                "duration_seconds": 0,
                "total_actions": actions_total,
                "successful_actions": 0,
                "failed_actions": 0,
                "skipped_actions": 0,
                "total_tokens": 0,
                "error_message": None,
                "actions": {},  # Action-level metrics
            }

            # Add to executions list (prepend to show most recent first)
            runs_data["executions"].insert(0, run_record)

            # Keep only last 100 runs
            runs_data["executions"] = runs_data["executions"][:100]

            # Update metadata
            runs_data["metadata"]["generated_at"] = datetime.now().isoformat()
            runs_data["metadata"]["total_runs"] = len(runs_data["executions"])

            # Write back to file
            f.seek(0)
            f.truncate()
            json.dump(runs_data, f, indent=2)

        return run_id

    @retry(max_attempts=3, backoff=2.0, exceptions=(portalocker.exceptions.LockException,))
    def record_action_start(
        self, *, run_id: str, action_name: str, action_type: str, agent_config: Dict[str, Any]
    ) -> None:
        """
        Record when an action starts executing.

        Args:
            run_id: Workflow run identifier
            action_name: Name of the action
            action_type: 'llm' or 'tool'
            agent_config: Full agent configuration (for extracting model info)
        """
        # Atomic read-modify-write with exclusive lock and retry
        with portalocker.Lock(self.runs_file, "r+", timeout=10, flags=portalocker.LOCK_EX) as f:
            f.seek(0)
            runs_data = json.load(f)

            # Find the run
            for run in runs_data["executions"]:
                if run["id"] == run_id:
                    # Create action entry
                    action_entry = {
                        "status": "running",
                        "started_at": datetime.now().isoformat(),
                        "ended_at": None,
                        "duration_seconds": 0,
                        "type": action_type,
                    }

                    # Add model info for LLM actions
                    if action_type == "llm":
                        action_entry["vendor"] = agent_config.get("model_vendor")
                        action_entry["model"] = agent_config.get("model_name")
                    elif action_type == "tool":
                        # For tools, model_name contains implementation
                        action_entry["impl"] = agent_config.get("model_name")

                    # Add action to run
                    run["actions"][action_name] = action_entry

                    # Write back
                    f.seek(0)
                    f.truncate()
                    json.dump(runs_data, f, indent=2)
                    return

            # Run not found
            # If we get here, the run wasn't found - we don't retry for this logic error
            return

    @retry(max_attempts=3, backoff=2.0, exceptions=(portalocker.exceptions.LockException,))
    def record_action_complete(self, *, config: ActionCompleteConfig) -> None:
        """
        Record when an action completes.

        Args:
            config: ActionCompleteConfig containing action completion parameters
        """
        # Atomic read-modify-write with exclusive lock and retry
        with portalocker.Lock(self.runs_file, "r+", timeout=10, flags=portalocker.LOCK_EX) as f:
            f.seek(0)
            runs_data = json.load(f)

            # Find the run
            for run in runs_data["executions"]:
                if run["id"] == config.run_id:
                    self._update_action_entry(run, config)
                    self._update_workflow_counters(run, config.status)

                    # Write back
                    f.seek(0)
                    f.truncate()
                    json.dump(runs_data, f, indent=2)
                    return

            # Run not found
            return

    def _update_action_entry(self, run: Dict[str, Any], config: ActionCompleteConfig) -> None:
        """Update action entry in run data."""
        if config.action_name not in run["actions"]:
            return

        action_entry = run["actions"][config.action_name]
        action_entry["status"] = config.status
        action_entry["ended_at"] = datetime.now().isoformat()
        action_entry["duration_seconds"] = config.duration_seconds

        # Add optional fields
        if config.tokens:
            action_entry["tokens"] = config.tokens
            # Aggregate tokens to workflow level
            current_total = run.get("total_tokens", 0)
            token_total = config.tokens.get("total_tokens", 0)
            run["total_tokens"] = current_total + token_total

        if config.files_processed > 0:
            action_entry["files_processed"] = config.files_processed

        if config.skip_reason:
            action_entry["skip_reason"] = config.skip_reason

        if config.error:
            action_entry["error"] = config.error

    def _update_workflow_counters(self, run: Dict[str, Any], status: str) -> None:
        """Update workflow-level counters."""
        if status == "success":
            run["successful_actions"] = run.get("successful_actions", 0) + 1
        elif status == "failed":
            run["failed_actions"] = run.get("failed_actions", 0) + 1
        elif status == "skipped":
            run["skipped_actions"] = run.get("skipped_actions", 0) + 1

    @retry(max_attempts=3, backoff=2.0, exceptions=(portalocker.exceptions.LockException,))
    def finalize_workflow_run(
        self, *, run_id: str, status: str, error_message: Optional[str] = None
    ) -> None:
        """
        Finalize workflow run when it completes or fails.

        Args:
            run_id: Workflow run identifier
            status: 'SUCCESS', 'FAILED', 'PAUSED'
            error_message: Error description (if status='FAILED')
        """
        # Atomic read-modify-write with exclusive lock and retry
        with portalocker.Lock(self.runs_file, "r+", timeout=10, flags=portalocker.LOCK_EX) as f:
            f.seek(0)
            runs_data = json.load(f)

            # Find the run
            for run in runs_data["executions"]:
                if run["id"] == run_id:
                    # Update run status
                    run["status"] = status
                    run["ended_at"] = datetime.now().isoformat()

                    # Calculate duration
                    try:
                        start = datetime.fromisoformat(run["started_at"].replace("Z", "+00:00"))
                        end = datetime.fromisoformat(run["ended_at"].replace("Z", "+00:00"))
                        run["duration_seconds"] = (end - start).total_seconds()
                    except (ValueError, AttributeError):
                        pass

                    # Add error message if provided
                    if error_message:
                        run["error_message"] = error_message

                    # Recalculate workflow metrics
                    runs_data["workflow_metrics"] = self._calculate_workflow_metrics(runs_data)

                    # Write back
                    f.seek(0)
                    f.truncate()
                    json.dump(runs_data, f, indent=2)
                    return

            # Run not found
            # Logic fallthrough
            return

    def _calculate_workflow_metrics(self, runs_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Calculate aggregate metrics per workflow.

        Args:
            runs_data: Full runs data structure

        Returns:
            Dictionary of workflow metrics keyed by workflow_id
        """
        metrics = {}

        for run in runs_data["executions"]:
            wf_id = run["workflow_id"]

            if wf_id not in metrics:
                metrics[wf_id] = {
                    "total_runs": 0,
                    "successful_runs": 0,
                    "failed_runs": 0,
                    "total_duration": 0,
                    "total_tokens": 0,
                }

            # Increment counters
            metrics[wf_id]["total_runs"] += 1

            if run["status"] == "SUCCESS":
                metrics[wf_id]["successful_runs"] += 1
            elif run["status"] == "FAILED":
                metrics[wf_id]["failed_runs"] += 1

            metrics[wf_id]["total_duration"] += run.get("duration_seconds", 0)
            metrics[wf_id]["total_tokens"] += run.get("total_tokens", 0)

        # Calculate averages and rates
        for wf_id, data in metrics.items():
            total_runs = data["total_runs"]
            if total_runs > 0:
                data["success_rate"] = data["successful_runs"] / total_runs
                data["avg_duration_seconds"] = data["total_duration"] / total_runs
            else:
                data["success_rate"] = 0
                data["avg_duration_seconds"] = 0

            # Remove intermediate totals (keep only calculated metrics)
            del data["total_duration"]

        return metrics


# Convenience function for quick integration
def track_workflow_run(*, config: RunConfig) -> str:
    """
    Quick function to track a workflow run.

    Args:
        config: RunConfig containing run parameters

    Returns:
        Run ID of the recorded execution
    """
    tracker = RunTracker()
    return tracker.record_run(config=config)
