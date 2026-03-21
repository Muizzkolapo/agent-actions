"""Run tracking for the documentation system."""

import functools
import json
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import portalocker

from agent_actions.config.path_config import resolve_project_root

logger = logging.getLogger(__name__)

from agent_actions.config.defaults import LockDefaults
from agent_actions.utils.constants import DEFAULT_ACTION_KIND


def _empty_runs_data(*, extended: bool = False) -> dict[str, Any]:
    """Create empty runs data structure, optionally with workflow_metrics fields."""
    runs: dict[str, Any] = {
        "metadata": {"generated_at": datetime.now(UTC).isoformat(), "total_runs": 0},
        "executions": [],
    }
    if extended:
        runs["metadata"]["schema_version"] = "1.0"
        runs["workflow_metrics"] = {}
    return runs


def retry(
    max_attempts: int = 3,
    backoff: float = 2.0,
    exceptions: tuple[type[Exception], ...] = (Exception,),
):
    """Simple retry decorator for file locking operations."""

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_attempts - 1:
                        time.sleep(backoff * (attempt + 1))
            if last_exception is None:
                raise RuntimeError("retry exhausted without capturing an exception")
            raise last_exception

        return wrapper

    return decorator


@dataclass
class RunConfig:
    """Configuration for recording a workflow run."""

    workflow_id: str
    workflow_name: str
    status: str
    started_at: str
    ended_at: str | None = None
    duration_seconds: float | None = None
    actions_completed: int = 0
    actions_total: int = 0
    error_message: str | None = None
    metadata: dict[str, Any] | None = None


@dataclass
class ActionCompleteConfig:
    """Configuration for recording action completion."""

    run_id: str
    action_name: str
    status: str
    duration_seconds: float
    tokens: dict[str, int] | None = None
    files_processed: int = 0
    skip_reason: str | None = None
    error: str | None = None


class RunTracker:
    """Track workflow execution runs for documentation."""

    def __init__(self, artefact_dir: Path | None = None, project_root: Path | None = None):
        """Initialize run tracker."""
        self.artefact_dir = artefact_dir or resolve_project_root(project_root) / "artefact"
        self.runs_file = self.artefact_dir / "runs.json"

    def record_run(self, *, config: RunConfig) -> str:
        """Record a workflow execution run with atomic file locking."""
        # Ensure directory exists
        self.artefact_dir.mkdir(parents=True, exist_ok=True)

        # Create file atomically — touch is safe under concurrent access
        self.runs_file.touch(exist_ok=True)

        # Atomic read-modify-write with exclusive non-blocking lock + timeout
        try:
            with portalocker.Lock(
                self.runs_file,
                "r+",
                timeout=LockDefaults.ATOMIC_LOCK_TIMEOUT_SECONDS,
                flags=portalocker.LOCK_EX | portalocker.LOCK_NB,
            ) as f:
                runs_data = self._load_runs_data_from_file(f)
                run_id = self._create_run_record(runs_data, config)
                self._write_runs_data_to_file(f, runs_data)
        except portalocker.exceptions.LockException:
            logger.warning("Could not acquire lock on %s within timeout", self.runs_file)
            raise

        return run_id

    def _load_runs_data_from_file(self, f) -> dict[str, Any]:
        """Load runs data from file handle."""
        try:
            f.seek(0)
            result: dict[str, Any] = json.load(f)
            return result
        except (OSError, json.JSONDecodeError):
            # File is empty or corrupted, create new structure
            return _empty_runs_data()

    def _create_run_record(self, runs_data: dict[str, Any], config: RunConfig) -> str:
        """Create run record and add to runs_data."""
        run_id = f"run_{config.workflow_id}_{uuid.uuid4().hex[:8]}"

        calc_duration = config.duration_seconds
        if calc_duration is None and config.started_at and config.ended_at:
            calc_duration = self._calculate_duration(config.started_at, config.ended_at)

        run_record: dict[str, Any] = {
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

        if config.error_message:
            run_record["error_message"] = config.error_message

        if config.metadata:
            run_record["metadata"] = config.metadata

        runs_data["executions"].insert(0, run_record)
        runs_data["executions"] = runs_data["executions"][:100]

        return run_id

    def _write_runs_data_to_file(self, f, runs_data: dict[str, Any]) -> None:
        """Write runs data to file handle."""
        runs_data["metadata"]["generated_at"] = datetime.now(UTC).isoformat()
        runs_data["metadata"]["total_runs"] = len(runs_data["executions"])
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

    def update_run(self, run_id: str, updates: dict[str, Any] | None = None) -> bool:
        """Update an existing run record with atomic file locking."""
        if updates is None:
            updates = {}

        if not self.runs_file.exists():
            return False

        # Atomic read-modify-write with exclusive lock.
        # LOCK_NB lets portalocker retry until timeout instead of blocking
        # indefinitely at the OS level.
        try:
            with portalocker.Lock(
                self.runs_file,
                "r+",
                timeout=LockDefaults.ATOMIC_LOCK_TIMEOUT_SECONDS,
                flags=portalocker.LOCK_EX | portalocker.LOCK_NB,
            ) as f:
                runs_data = self._load_runs_data_from_file(f)

                # Find the run
                for run in runs_data["executions"]:
                    if run["id"] == run_id:
                        self._apply_run_updates(run, updates)
                        self._write_runs_data_to_file(f, runs_data)
                        return True
        except portalocker.exceptions.LockException:
            logger.warning("Could not acquire lock on %s within timeout", self.runs_file)
            return False

        return False

    def _apply_run_updates(self, run: dict[str, Any], updates: dict[str, Any]) -> None:
        """Apply updates to a run record."""
        if "status" in updates:
            run["status"] = updates["status"]
        if "ended_at" in updates:
            ended_at = updates["ended_at"]
            run["ended_at"] = ended_at
            run["duration_seconds"] = self._calculate_duration(run["started_at"], ended_at)
        if "actions_completed" in updates:
            run["actions_completed"] = updates["actions_completed"]
        if "error_message" in updates:
            run["error_message"] = updates["error_message"]

    def start_workflow_run(
        self, *, workflow_id: str, workflow_name: str, actions_total: int
    ) -> str:
        """Start tracking a new workflow run with action-level metrics."""
        self.artefact_dir.mkdir(parents=True, exist_ok=True)

        # Create file atomically before acquiring the lock — avoids TOCTOU race
        self.runs_file.touch(exist_ok=True)

        try:
            with portalocker.Lock(
                self.runs_file,
                "r+",
                timeout=LockDefaults.ATOMIC_LOCK_TIMEOUT_SECONDS,
                flags=portalocker.LOCK_EX | portalocker.LOCK_NB,
            ) as f:
                try:
                    f.seek(0)
                    runs_data = json.load(f)
                except (OSError, json.JSONDecodeError):
                    # File is empty or corrupted, create new structure
                    runs_data = _empty_runs_data(extended=True)

                if "workflow_metrics" not in runs_data:
                    runs_data["workflow_metrics"] = {}

                run_id = f"run_{workflow_id}_{uuid.uuid4().hex[:8]}"

                run_record: dict[str, Any] = {
                    "id": run_id,
                    "workflow_id": workflow_id,
                    "workflow_name": workflow_name,
                    "status": "running",
                    "started_at": datetime.now(UTC).isoformat(),
                    "ended_at": None,
                    "duration_seconds": 0,
                    "total_actions": actions_total,
                    "successful_actions": 0,
                    "failed_actions": 0,
                    "skipped_actions": 0,
                    "total_tokens": 0,
                    "error_message": None,
                    "actions": {},
                }

                runs_data["executions"].insert(0, run_record)
                runs_data["executions"] = runs_data["executions"][:100]

                runs_data["metadata"]["generated_at"] = datetime.now(UTC).isoformat()
                runs_data["metadata"]["total_runs"] = len(runs_data["executions"])

                f.seek(0)
                f.truncate()
                json.dump(runs_data, f, indent=2)

        except portalocker.exceptions.LockException:
            logger.warning("Could not acquire lock on %s within timeout", self.runs_file)
            raise

        return run_id

    @retry(max_attempts=3, backoff=2.0, exceptions=(portalocker.exceptions.LockException,))
    def record_action_start(
        self, *, run_id: str, action_name: str, action_type: str, action_config: dict[str, Any]
    ) -> None:
        """Record when an action starts executing."""
        with portalocker.Lock(
            self.runs_file,
            "r+",
            timeout=LockDefaults.ATOMIC_LOCK_TIMEOUT_SECONDS,
            flags=portalocker.LOCK_EX | portalocker.LOCK_NB,
        ) as f:
            f.seek(0)
            runs_data = json.load(f)

            for run in runs_data["executions"]:
                if run["id"] == run_id:
                    action_entry = {
                        "status": "running",
                        "started_at": datetime.now(UTC).isoformat(),
                        "ended_at": None,
                        "duration_seconds": 0,
                        "type": action_type,
                    }

                    if action_type == DEFAULT_ACTION_KIND:
                        action_entry["vendor"] = action_config.get("model_vendor")
                        action_entry["model"] = action_config.get("model_name")
                    elif action_type == "tool":
                        action_entry["impl"] = action_config.get("model_name")

                    if "actions" not in run:
                        run["actions"] = {}
                    run["actions"][action_name] = action_entry

                    f.seek(0)
                    f.truncate()
                    json.dump(runs_data, f, indent=2)
                    return

            return

    @retry(max_attempts=3, backoff=2.0, exceptions=(portalocker.exceptions.LockException,))
    def record_action_complete(self, *, config: ActionCompleteConfig) -> None:
        """Record when an action completes."""
        with portalocker.Lock(
            self.runs_file,
            "r+",
            timeout=LockDefaults.ATOMIC_LOCK_TIMEOUT_SECONDS,
            flags=portalocker.LOCK_EX | portalocker.LOCK_NB,
        ) as f:
            f.seek(0)
            runs_data = json.load(f)

            for run in runs_data["executions"]:
                if run["id"] == config.run_id:
                    self._update_action_entry(run, config)
                    self._update_workflow_counters(run, config.status)

                    f.seek(0)
                    f.truncate()
                    json.dump(runs_data, f, indent=2)
                    return

            return

    def _update_action_entry(self, run: dict[str, Any], config: ActionCompleteConfig) -> None:
        """Update action entry in run data."""
        if config.action_name not in run["actions"]:
            return

        action_entry = run["actions"][config.action_name]
        action_entry["status"] = config.status
        action_entry["ended_at"] = datetime.now(UTC).isoformat()
        action_entry["duration_seconds"] = config.duration_seconds

        if config.tokens:
            action_entry["tokens"] = config.tokens
            current_total = run.get("total_tokens", 0)
            token_total = config.tokens.get("total_tokens", 0)
            run["total_tokens"] = current_total + token_total

        if config.files_processed > 0:
            action_entry["files_processed"] = config.files_processed

        if config.skip_reason:
            action_entry["skip_reason"] = config.skip_reason

        if config.error:
            action_entry["error"] = config.error

    def _update_workflow_counters(self, run: dict[str, Any], status: str) -> None:
        """Update workflow-level counters."""
        if status == "success":
            run["successful_actions"] = run.get("successful_actions", 0) + 1
        elif status == "failed":
            run["failed_actions"] = run.get("failed_actions", 0) + 1
        elif status == "skipped":
            run["skipped_actions"] = run.get("skipped_actions", 0) + 1

    @retry(max_attempts=3, backoff=2.0, exceptions=(portalocker.exceptions.LockException,))
    def finalize_workflow_run(
        self, *, run_id: str, status: str, error_message: str | None = None
    ) -> None:
        """Finalize workflow run when it completes or fails."""
        with portalocker.Lock(
            self.runs_file,
            "r+",
            timeout=LockDefaults.ATOMIC_LOCK_TIMEOUT_SECONDS,
            flags=portalocker.LOCK_EX | portalocker.LOCK_NB,
        ) as f:
            f.seek(0)
            runs_data = json.load(f)

            for run in runs_data["executions"]:
                if run["id"] == run_id:
                    run["status"] = status
                    run["ended_at"] = datetime.now(UTC).isoformat()
                    run["duration_seconds"] = self._calculate_duration(
                        run["started_at"], run["ended_at"]
                    )

                    if error_message:
                        run["error_message"] = error_message

                    runs_data["workflow_metrics"] = self._calculate_workflow_metrics(runs_data)

                    f.seek(0)
                    f.truncate()
                    json.dump(runs_data, f, indent=2)
                    return

            return

    def _calculate_workflow_metrics(self, runs_data: dict[str, Any]) -> dict[str, Any]:
        """Calculate aggregate metrics per workflow."""
        metrics: dict[str, dict[str, Any]] = {}

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

            metrics[wf_id]["total_runs"] += 1

            status_lower = run["status"].lower() if isinstance(run["status"], str) else ""
            if status_lower == "success":
                metrics[wf_id]["successful_runs"] += 1
            elif status_lower == "failed":
                metrics[wf_id]["failed_runs"] += 1

            metrics[wf_id]["total_duration"] += run.get("duration_seconds", 0)
            metrics[wf_id]["total_tokens"] += run.get("total_tokens", 0)

        for _wf_id, data in metrics.items():
            total_runs = data["total_runs"]
            if total_runs > 0:
                data["success_rate"] = data["successful_runs"] / total_runs
                data["avg_duration_seconds"] = data["total_duration"] / total_runs
            else:
                data["success_rate"] = 0
                data["avg_duration_seconds"] = 0

            del data["total_duration"]

        return metrics


def track_workflow_run(*, config: RunConfig) -> str:
    """Track a workflow run and return its run ID."""
    tracker = RunTracker()
    return tracker.record_run(config=config)
