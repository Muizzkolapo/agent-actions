"""
Batch job lifecycle management module.

Handles batch job status checking, registry management, and result processing.
Extracted from agent_workflow.py to consolidate batch handling logic.
"""

import logging
from pathlib import Path
from typing import Tuple, Optional, Dict, Any
from rich.console import Console
from agent_actions.errors import ProcessingError
from agent_actions.logging.core import fire_event
from agent_actions.logging.events import (
    BatchProcessingCompleteEvent,
    BatchResultsProcessedEvent,
    BatchErrorEvent,
    BatchPassthroughEvent,
    BatchStatusEvent,
)

logger = logging.getLogger(__name__)


class BatchLifecycleManager:
    """
    Manages batch job lifecycle and result processing.

    Responsibilities:
    - Check batch job status via registry
    - Process completed batch results
    - Handle passthrough scenarios (all filtered)
    - Provide unified batch status reporting
    """

    def __init__(self, batch_service, console: Optional[Console] = None):
        """
        Initialize batch lifecycle manager.

        Args:
            batch_service: BatchService instance for registry/result operations
            console: Rich console for output
        """
        self.batch_service = batch_service
        self.console = console or Console()

    def handle_batch_agent(
        self, agent_name: str, output_directory: str, agent_config: Optional[Dict[str, Any]] = None
    ) -> Tuple[Optional[str], str]:
        """
        Handle batch agent status checking and result processing.

        Args:
            agent_name: Name of the agent
            output_directory: Path to agent output directory
            agent_config: Agent configuration (optional, for processing)

        Returns:
            Tuple of (output_folder, batch_status)
            - output_folder: Path to output folder if completed, None otherwise
            - batch_status: 'completed', 'in_progress', or 'failed'
        """
        registry_status = self.batch_service.get_batch_registry_status(output_directory)

        # Case 1: All batches completed
        if registry_status == "completed":
            fire_event(BatchProcessingCompleteEvent(agent_name=agent_name))
            self._process_batch_results(output_directory, agent_config, agent_name)
            fire_event(BatchResultsProcessedEvent(agent_name=agent_name))
            return (output_directory, "completed")

        # Case 2: Batches in progress or partial failure
        if registry_status in ["in_progress", "partial_failed"]:
            if self.batch_service.are_all_batch_jobs_completed(output_directory):
                fire_event(BatchProcessingCompleteEvent(agent_name=agent_name))
                self._process_batch_results(output_directory, agent_config, agent_name)
                fire_event(BatchResultsProcessedEvent(agent_name=agent_name))
                return (output_directory, "completed")
            return (None, "in_progress")

        # Case 3: No batches found, check for passthrough
        if registry_status == "no_batches":
            passthrough_marker = Path(output_directory) / ".passthrough_processed"
            if passthrough_marker.exists():
                fire_event(BatchPassthroughEvent(agent_name=agent_name))
                return (output_directory, "completed")
            fire_event(
                BatchStatusEvent(
                    agent_name=agent_name,
                    status_message=f"No batch jobs found for {agent_name}",
                    status_type="warning",
                )
            )
            return (None, "failed")

        # Case 4: Failed status
        return (None, "failed")

    def _process_batch_results(
        self, output_directory: str, agent_config: Optional[Dict[str, Any]], agent_name: str
    ):
        """
        Process all completed batch job results.

        Args:
            output_directory: Path to output directory
            agent_config: Agent configuration
            agent_name: Name of agent (for storage backend writes and error messages)

        Raises:
            ProcessingError: If result processing fails
        """
        try:
            processed_files = self.batch_service.process_all_batch_results(
                output_directory, agent_config=agent_config, node_name=agent_name
            )

            if not processed_files:
                raise ProcessingError("No batch results were successfully processed")

        except ProcessingError as e:
            fire_event(
                BatchErrorEvent(
                    agent_name=agent_name,
                    error_message="Could not process batch results",
                    error_type="ProcessingError",
                )
            )
            raise
        except Exception as e:
            fire_event(
                BatchErrorEvent(
                    agent_name=agent_name,
                    error_message=f"Could not process batch results: {str(e)}",
                    error_type=type(e).__name__,
                )
            )
            raise

    def check_batch_submission(
        self, agent_name: str, agent_idx: int, agent_io_path: Path
    ) -> Optional[str]:
        """
        Check if batch jobs were submitted for an agent.

        Args:
            agent_name: Name of the agent
            agent_idx: Index of the agent
            agent_io_path: Path to agent I/O folder

        Returns:
            Status string: 'batch_submitted', 'passthrough', 'no_batches', or None
        """
        # Use simple directory name (no index prefix)
        node_output_dir = agent_io_path / "target" / agent_name
        registry_file = node_output_dir / "batch" / ".batch_registry.json"
        passthrough_marker = node_output_dir / ".passthrough_processed"

        if registry_file.exists():
            return "batch_submitted"
        if passthrough_marker.exists():
            return "passthrough"
        if node_output_dir.exists():
            # Output dir exists but no batch registry or passthrough
            return "no_batches"
        return None

    def cleanup_passthrough_marker(self, output_dir: Path):
        """
        Remove passthrough marker after processing.

        Args:
            output_dir: Path to output directory
        """
        passthrough_marker = output_dir / ".passthrough_processed"
        try:
            if passthrough_marker.exists():
                passthrough_marker.unlink()
        except FileNotFoundError:
            pass  # Already removed
        except (OSError, PermissionError) as e:
            logger.warning(
                "Could not remove passthrough file %s: %s",
                passthrough_marker,
                e,
                exc_info=True,
                extra={
                    "passthrough_marker": str(passthrough_marker),
                    "operation": "cleanup_passthrough_marker",
                },
            )
