"""
Run tracking for documentation system.

Records workflow execution data to artefact/runs.json for the docs UI.
"""
import json
import portalocker
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional


class RunTracker:
    """Track workflow execution runs for documentation."""

    def __init__(self, artefact_dir: Optional[Path] = None):
        """
        Initialize run tracker.

        Args:
            artefact_dir: Directory to store runs.json (defaults to ./artefact)
        """
        self.artefact_dir = artefact_dir or Path.cwd() / 'artefact'
        self.runs_file = self.artefact_dir / 'runs.json'

    def _load_existing_runs(self) -> Dict[str, Any]:
        """Load existing runs data or create new structure with file locking."""
        if self.runs_file.exists():
            try:
                with portalocker.Lock(self.runs_file, 'r', timeout=5) as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError, portalocker.exceptions.LockException):
                # If file is corrupted or locked, start fresh
                pass

        # Return empty structure
        return {
            'metadata': {
                'generated_at': datetime.now().isoformat(),
                'total_runs': 0
            },
            'executions': []
        }

    def _save_runs(self, runs_data: Dict[str, Any]) -> None:
        """Save runs data to file with file locking to prevent concurrent write issues."""
        # Ensure directory exists
        self.artefact_dir.mkdir(parents=True, exist_ok=True)

        # Update metadata
        runs_data['metadata']['generated_at'] = datetime.now().isoformat()
        runs_data['metadata']['total_runs'] = len(runs_data['executions'])

        # Write to file with exclusive lock
        with portalocker.Lock(self.runs_file, 'w', timeout=5) as f:
            json.dump(runs_data, f, indent=2)

    def record_run(
        self,
        workflow_id: str,
        workflow_name: str,
        status: str,
        started_at: str,
        ended_at: Optional[str] = None,
        duration_seconds: Optional[float] = None,
        actions_completed: int = 0,
        actions_total: int = 0,
        error_message: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Record a workflow execution run with atomic file locking.

        This method ensures thread-safe and process-safe appending to runs.json
        by holding an exclusive lock during the entire read-modify-write operation.

        Args:
            workflow_id: Unique identifier for the workflow
            workflow_name: Human-readable workflow name
            status: Execution status (SUCCESS, FAILED, RUNNING, PAUSED)
            started_at: ISO format timestamp when run started
            ended_at: ISO format timestamp when run ended (optional)
            duration_seconds: Total execution time in seconds (optional)
            actions_completed: Number of actions completed
            actions_total: Total number of actions in workflow
            error_message: Error message if failed (optional)
            metadata: Additional metadata (optional)

        Returns:
            Run ID of the recorded execution
        """
        # Ensure directory exists
        self.artefact_dir.mkdir(parents=True, exist_ok=True)

        # Create file if it doesn't exist
        if not self.runs_file.exists():
            with open(self.runs_file, 'w') as f:
                json.dump({
                    'metadata': {'generated_at': datetime.now().isoformat(), 'total_runs': 0},
                    'executions': []
                }, f)

        # Atomic read-modify-write with exclusive lock
        with portalocker.Lock(self.runs_file, 'r+', timeout=10, flags=portalocker.LOCK_EX) as f:
            # Load existing data
            try:
                f.seek(0)
                runs_data = json.load(f)
            except (json.JSONDecodeError, IOError):
                # File is empty or corrupted, create new structure
                runs_data = {
                    'metadata': {
                        'generated_at': datetime.now().isoformat(),
                        'total_runs': 0
                    },
                    'executions': []
                }

            # Generate run ID
            run_count = len(runs_data['executions']) + 1
            run_id = f"run_{workflow_id}_{run_count:03d}"

            # Calculate duration if not provided
            if duration_seconds is None and started_at and ended_at:
                try:
                    start = datetime.fromisoformat(started_at.replace('Z', '+00:00'))
                    end = datetime.fromisoformat(ended_at.replace('Z', '+00:00'))
                    duration_seconds = (end - start).total_seconds()
                except (ValueError, AttributeError):
                    duration_seconds = 0

            # Create run record
            run_record = {
                'id': run_id,
                'workflow_id': workflow_id,
                'workflow_name': workflow_name,
                'status': status,
                'started_at': started_at,
                'ended_at': ended_at,
                'duration_seconds': duration_seconds or 0,
                'actions_completed': actions_completed,
                'actions_total': actions_total
            }

            # Add optional fields
            if error_message:
                run_record['error_message'] = error_message

            if metadata:
                run_record['metadata'] = metadata

            # Add to executions list (prepend to show most recent first)
            runs_data['executions'].insert(0, run_record)

            # Keep only last 100 runs to avoid file getting too large
            runs_data['executions'] = runs_data['executions'][:100]

            # Update metadata
            runs_data['metadata']['generated_at'] = datetime.now().isoformat()
            runs_data['metadata']['total_runs'] = len(runs_data['executions'])

            # Write back to file (atomically within the lock)
            f.seek(0)
            f.truncate()
            json.dump(runs_data, f, indent=2)

        return run_id

    def update_run(
        self,
        run_id: str,
        status: Optional[str] = None,
        ended_at: Optional[str] = None,
        actions_completed: Optional[int] = None,
        error_message: Optional[str] = None
    ) -> bool:
        """
        Update an existing run record.

        Args:
            run_id: ID of the run to update
            status: New status (optional)
            ended_at: End timestamp (optional)
            actions_completed: Updated action count (optional)
            error_message: Error message (optional)

        Returns:
            True if run was found and updated, False otherwise
        """
        runs_data = self._load_existing_runs()

        # Find the run
        for run in runs_data['executions']:
            if run['id'] == run_id:
                # Update fields
                if status is not None:
                    run['status'] = status
                if ended_at is not None:
                    run['ended_at'] = ended_at
                    # Recalculate duration
                    try:
                        start = datetime.fromisoformat(run['started_at'].replace('Z', '+00:00'))
                        end = datetime.fromisoformat(ended_at.replace('Z', '+00:00'))
                        run['duration_seconds'] = (end - start).total_seconds()
                    except (ValueError, AttributeError):
                        pass
                if actions_completed is not None:
                    run['actions_completed'] = actions_completed
                if error_message is not None:
                    run['error_message'] = error_message

                # Save and return
                self._save_runs(runs_data)
                return True

        return False


# Convenience function for quick integration
def track_workflow_run(
    workflow_id: str,
    workflow_name: str,
    status: str,
    started_at: str,
    ended_at: Optional[str] = None,
    duration_seconds: Optional[float] = None,
    actions_completed: int = 0,
    actions_total: int = 0,
    error_message: Optional[str] = None
) -> str:
    """
    Quick function to track a workflow run.

    Args:
        workflow_id: Unique identifier for the workflow
        workflow_name: Human-readable workflow name
        status: Execution status (SUCCESS, FAILED, RUNNING, PAUSED)
        started_at: ISO format timestamp when run started
        ended_at: ISO format timestamp when run ended (optional)
        duration_seconds: Total execution time in seconds (optional)
        actions_completed: Number of actions completed
        actions_total: Total number of actions in workflow
        error_message: Error message if failed (optional)

    Returns:
        Run ID of the recorded execution
    """
    tracker = RunTracker()
    return tracker.record_run(
        workflow_id=workflow_id,
        workflow_name=workflow_name,
        status=status,
        started_at=started_at,
        ended_at=ended_at,
        duration_seconds=duration_seconds,
        actions_completed=actions_completed,
        actions_total=actions_total,
        error_message=error_message
    )
