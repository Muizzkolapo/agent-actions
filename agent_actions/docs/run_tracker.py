"""
Run tracking for documentation system.

Records workflow execution data to artefact/runs.json for the docs UI.
"""
import json
import portalocker
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional
from agent_actions.utilities.retry import retry


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

    def start_workflow_run(
        self,
        workflow_id: str,
        workflow_name: str,
        actions_total: int
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
            with open(self.runs_file, 'w') as f:
                json.dump({
                    'metadata': {
                        'generated_at': datetime.now().isoformat(),
                        'total_runs': 0,
                        'schema_version': '1.0'
                    },
                    'workflow_metrics': {},
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
                        'total_runs': 0,
                        'schema_version': '1.0'
                    },
                    'workflow_metrics': {},
                    'executions': []
                }

            # Ensure workflow_metrics exists
            if 'workflow_metrics' not in runs_data:
                runs_data['workflow_metrics'] = {}

            # Generate run ID
            run_count = len(runs_data['executions']) + 1
            run_id = f"run_{workflow_id}_{run_count:03d}"

            # Create run record with action-level tracking support
            run_record = {
                'id': run_id,
                'workflow_id': workflow_id,
                'workflow_name': workflow_name,
                'status': 'running',
                'started_at': datetime.now().isoformat(),
                'ended_at': None,
                'duration_seconds': 0,
                'total_actions': actions_total,
                'successful_actions': 0,
                'failed_actions': 0,
                'skipped_actions': 0,
                'total_tokens': 0,
                'error_message': None,
                'actions': {}  # Action-level metrics
            }

            # Add to executions list (prepend to show most recent first)
            runs_data['executions'].insert(0, run_record)

            # Keep only last 100 runs
            runs_data['executions'] = runs_data['executions'][:100]

            # Update metadata
            runs_data['metadata']['generated_at'] = datetime.now().isoformat()
            runs_data['metadata']['total_runs'] = len(runs_data['executions'])

            # Write back to file
            f.seek(0)
            f.truncate()
            json.dump(runs_data, f, indent=2)

        return run_id

    @retry(max_attempts=3, backoff=2.0, exceptions=(portalocker.exceptions.LockException,))
    def record_action_start(
        self,
        run_id: str,
        action_name: str,
        action_type: str,
        agent_config: Dict[str, Any]
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
        with portalocker.Lock(self.runs_file, 'r+', timeout=10, flags=portalocker.LOCK_EX) as f:
            f.seek(0)
            runs_data = json.load(f)

            # Find the run
            for run in runs_data['executions']:
                if run['id'] == run_id:
                    # Create action entry
                    action_entry = {
                        'status': 'running',
                        'started_at': datetime.now().isoformat(),
                        'ended_at': None,
                        'duration_seconds': 0,
                        'type': action_type
                    }

                    # Add model info for LLM actions
                    if action_type == 'llm':
                        action_entry['model_vendor'] = agent_config.get('model_vendor')
                        action_entry['model_name'] = agent_config.get('model_name')
                    elif action_type == 'tool':
                        action_entry['impl'] = agent_config.get('model_name')  # For tools, model_name contains impl

                    # Add action to run
                    run['actions'][action_name] = action_entry

                    # Write back
                    f.seek(0)
                    f.truncate()
                    json.dump(runs_data, f, indent=2)
                    return

            # Run not found
            # If we get here, the run wasn't found - we don't retry for this logic error
            return

    @retry(max_attempts=3, backoff=2.0, exceptions=(portalocker.exceptions.LockException,))
    def record_action_complete(
        self,
        run_id: str,
        action_name: str,
        status: str,
        duration_seconds: float,
        tokens: Optional[Dict[str, int]] = None,
        files_processed: int = 0,
        skip_reason: Optional[str] = None,
        error: Optional[str] = None
    ) -> None:
        """
        Record when an action completes.

        Args:
            run_id: Workflow run identifier
            action_name: Name of the action
            status: 'success', 'failed', 'skipped', 'batch_submitted'
            duration_seconds: Execution time
            tokens: Token usage dict (input_tokens, output_tokens, total_tokens)
            files_processed: Number of files processed
            skip_reason: Reason for skip (if status='skipped')
            error: Error message (if status='failed')
        """
        # Atomic read-modify-write with exclusive lock and retry
        with portalocker.Lock(self.runs_file, 'r+', timeout=10, flags=portalocker.LOCK_EX) as f:
            f.seek(0)
            runs_data = json.load(f)

            # Find the run
            for run in runs_data['executions']:
                if run['id'] == run_id:
                    # Update action entry
                    if action_name in run['actions']:
                        action_entry = run['actions'][action_name]
                        action_entry['status'] = status
                        action_entry['ended_at'] = datetime.now().isoformat()
                        action_entry['duration_seconds'] = duration_seconds

                        # Add optional fields
                        if tokens:
                            action_entry['tokens'] = tokens
                            # Aggregate tokens to workflow level
                            run['total_tokens'] = run.get('total_tokens', 0) + tokens.get('total_tokens', 0)

                        if files_processed > 0:
                            action_entry['files_processed'] = files_processed

                        if skip_reason:
                            action_entry['skip_reason'] = skip_reason

                        if error:
                            action_entry['error'] = error

                    # Update workflow-level counters
                    if status == 'success':
                        run['successful_actions'] = run.get('successful_actions', 0) + 1
                    elif status == 'failed':
                        run['failed_actions'] = run.get('failed_actions', 0) + 1
                    elif status == 'skipped':
                        run['skipped_actions'] = run.get('skipped_actions', 0) + 1

                    # Write back
                    f.seek(0)
                    f.truncate()
                    json.dump(runs_data, f, indent=2)
                    return

            # Run not found
            # No retry needed if logic falls through
            return

    @retry(max_attempts=3, backoff=2.0, exceptions=(portalocker.exceptions.LockException,))
    def finalize_workflow_run(
        self,
        run_id: str,
        status: str,
        error_message: Optional[str] = None
    ) -> None:
        """
        Finalize workflow run when it completes or fails.

        Args:
            run_id: Workflow run identifier
            status: 'SUCCESS', 'FAILED', 'PAUSED'
            error_message: Error description (if status='FAILED')
        """
        # Atomic read-modify-write with exclusive lock and retry
        with portalocker.Lock(self.runs_file, 'r+', timeout=10, flags=portalocker.LOCK_EX) as f:
            f.seek(0)
            runs_data = json.load(f)

            # Find the run
            for run in runs_data['executions']:
                if run['id'] == run_id:
                    # Update run status
                    run['status'] = status
                    run['ended_at'] = datetime.now().isoformat()

                    # Calculate duration
                    try:
                        start = datetime.fromisoformat(run['started_at'].replace('Z', '+00:00'))
                        end = datetime.fromisoformat(run['ended_at'].replace('Z', '+00:00'))
                        run['duration_seconds'] = (end - start).total_seconds()
                    except (ValueError, AttributeError):
                        pass

                    # Add error message if provided
                    if error_message:
                        run['error_message'] = error_message

                    # Recalculate workflow metrics
                    runs_data['workflow_metrics'] = self._calculate_workflow_metrics(runs_data)

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

        for run in runs_data['executions']:
            wf_id = run['workflow_id']

            if wf_id not in metrics:
                metrics[wf_id] = {
                    'total_runs': 0,
                    'successful_runs': 0,
                    'failed_runs': 0,
                    'total_duration': 0,
                    'total_tokens': 0
                }

            # Increment counters
            metrics[wf_id]['total_runs'] += 1

            if run['status'] == 'SUCCESS':
                metrics[wf_id]['successful_runs'] += 1
            elif run['status'] == 'FAILED':
                metrics[wf_id]['failed_runs'] += 1

            metrics[wf_id]['total_duration'] += run.get('duration_seconds', 0)
            metrics[wf_id]['total_tokens'] += run.get('total_tokens', 0)

        # Calculate averages and rates
        for wf_id, data in metrics.items():
            total_runs = data['total_runs']
            if total_runs > 0:
                data['success_rate'] = data['successful_runs'] / total_runs
                data['avg_duration_seconds'] = data['total_duration'] / total_runs
            else:
                data['success_rate'] = 0
                data['avg_duration_seconds'] = 0

            # Remove intermediate totals (keep only calculated metrics)
            del data['total_duration']

        return metrics


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
