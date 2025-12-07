"""
Batch job lifecycle management module.

Handles batch job status checking, registry management, and result processing.
Extracted from agent_workflow.py to consolidate batch handling logic.
"""

import logging
from pathlib import Path
from typing import Tuple, Optional, Dict, Any
from rich.console import Console

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
        self,
        agent_name: str,
        agent_idx: int,
        output_directory: str,
        agent_config: Optional[Dict[str, Any]] = None
    ) -> Tuple[Optional[str], str]:
        """
        Handle batch agent status checking and result processing.

        Args:
            agent_name: Name of the agent
            agent_idx: Index of the agent in execution order
            output_directory: Path to agent output directory
            agent_config: Agent configuration (optional, for processing)

        Returns:
            Tuple of (output_folder, batch_status)
            - output_folder: Path to output folder if completed, None otherwise
            - batch_status: 'completed', 'in_progress', or 'failed'
        """
        registry_status = self.batch_service._get_batch_registry_status(output_directory)

        # Case 1: All batches completed
        if registry_status == 'completed':
            self.console.print(f'[green]All batch jobs are completed. Processing results...[/green]')
            self._process_batch_results(output_directory, agent_config, agent_name)
            self.console.print(f'[green]✅ Processed all batch results for {agent_name}[/green]')
            return (output_directory, 'completed')

        # Case 2: Batches in progress or partial failure
        elif registry_status in ['in_progress', 'partial_failed']:
            if self.batch_service._are_all_batch_jobs_completed(output_directory):
                self.console.print(f'[green]All batch jobs are now completed. Processing results...[/green]')
                self._process_batch_results(output_directory, agent_config, agent_name)
                self.console.print(f'[green]✅ Processed all batch results for {agent_name}[/green]')
                return (output_directory, 'completed')
            else:
                return (None, 'in_progress')

        # Case 3: No batches found, check for passthrough
        elif registry_status == 'no_batches':
            passthrough_marker = Path(output_directory) / '.passthrough_processed'
            if passthrough_marker.exists():
                self.console.print(
                    f'[green]All items filtered by conditional clause - passthrough data processed for {agent_name}[/green]'
                )
                return (output_directory, 'completed')
            else:
                self.console.print(f'[yellow]No batch jobs found for {agent_name}[/yellow]')
                return (None, 'failed')

        # Case 4: Failed status
        else:
            return (None, 'failed')

    def _process_batch_results(
        self,
        output_directory: str,
        agent_config: Optional[Dict[str, Any]],
        agent_name: str
    ):
        """
        Process all completed batch job results.

        Args:
            output_directory: Path to output directory
            agent_config: Agent configuration
            agent_name: Name of agent (for error messages)

        Raises:
            ProcessingError: If result processing fails
        """
        try:
            processed_files = self.batch_service.process_all_batch_results(
                output_directory,
                agent_config=agent_config
            )

            if not processed_files:
                from agent_actions.errors import ProcessingError  # New modular pattern!
                raise ProcessingError('No batch results were successfully processed')

        except Exception as e:
            self.console.print(f'[red]Error: Could not process batch results for {agent_name}: {e}[/red]')
            raise

    def check_batch_submission(
        self,
        agent_name: str,
        agent_idx: int,
        agent_io_path: Path
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
        node_output_dir = agent_io_path / 'target' / f'node_{agent_idx}_{agent_name}'
        registry_file = node_output_dir / 'batch' / '.batch_registry.json'
        passthrough_marker = node_output_dir / '.passthrough_processed'

        if registry_file.exists():
            return 'batch_submitted'
        elif passthrough_marker.exists():
            return 'passthrough'
        elif node_output_dir.exists():
            # Output dir exists but no batch registry or passthrough
            return 'no_batches'
        else:
            return None

    def cleanup_passthrough_marker(self, output_dir: Path):
        """
        Remove passthrough marker after processing.

        Args:
            output_dir: Path to output directory
        """
        passthrough_marker = output_dir / '.passthrough_processed'
        try:
            if passthrough_marker.exists():
                passthrough_marker.unlink()
        except FileNotFoundError:
            pass  # Already removed
        except Exception as e:
            logger.warning(
                "Could not remove passthrough file %s: %s",
                passthrough_marker, e,
                exc_info=True,
                extra={
                    'passthrough_marker': str(passthrough_marker),
                    'operation': 'cleanup_passthrough_marker'
                }
            )
