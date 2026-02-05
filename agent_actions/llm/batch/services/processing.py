"""Batch processing service for processing batch job results.

This service encapsulates all result processing functionality, extracted from
BatchService to follow Single Responsibility Principle.

Retry and reprompt logic is delegated to BatchRetryService (retry.py).
Result retrieval with reconciliation is delegated to shared.retrieve_and_reconcile().
"""

import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Dict, Any, List, Callable

from agent_actions.logging import fire_event

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend
from agent_actions.logging.events import BatchCompleteEvent
from agent_actions.processing.types import RecoveryMetadata
from agent_actions.output.writer import FileWriter
from agent_actions.utils.path_utils import ensure_directory_exists, create_side_output_directory
from agent_actions.llm.batch.core.batch_constants import BatchStatus
from agent_actions.llm.batch.infrastructure.context import (
    BatchContextManager,
)
from agent_actions.llm.batch.infrastructure.batch_client_resolver import (
    BatchClientResolver,
)
from agent_actions.llm.batch.infrastructure.registry import (
    BatchRegistryManager,
)
from agent_actions.llm.batch.processing.result_processor import (
    BatchResultProcessor,
)
from agent_actions.llm.batch.processing.side_output import (
    BatchSideOutputHandler,
)
from agent_actions.llm.batch.core.batch_models import BatchJobEntry
from agent_actions.llm.batch.services.shared import retrieve_and_reconcile
from agent_actions.llm.batch.services.retry import BatchRetryService
from agent_actions.llm.providers.batch_base import BatchResult
from agent_actions.errors import ProcessingError

logger = logging.getLogger(__name__)


class BatchProcessingService:
    """Service for processing batch job results.

    Handles result retrieval, conversion, and output file generation.
    Delegates retry/reprompt logic to BatchRetryService.
    """

    def __init__(
        self,
        client_resolver: BatchClientResolver,
        context_manager: BatchContextManager,
        result_processor: BatchResultProcessor,
        registry_manager_factory: Callable[[str], BatchRegistryManager],
        source_handler: Optional[Any] = None,
        agent_indices: Optional[Dict[str, int]] = None,
        dependency_configs: Optional[Dict[str, Dict]] = None,
        storage_backend: Optional["StorageBackend"] = None,
        node_name: Optional[str] = None,
    ):
        """Initialize processing service with dependencies.

        Args:
            client_resolver: Resolver for batch API clients
            context_manager: Manager for batch context persistence
            result_processor: Processor for batch results
            registry_manager_factory: Factory function to create registry managers
            source_handler: Optional handler for source data
            agent_indices: Dict mapping agent names to node indices (for reprompt)
            dependency_configs: Dict mapping dependency names to configs (for reprompt)
            storage_backend: Optional storage backend for database persistence
            node_name: Node name for backend writes (required if storage_backend provided)
        """
        self._client_resolver = client_resolver
        self._context_manager = context_manager
        self._result_processor = result_processor
        self._registry_manager_factory = registry_manager_factory
        self._source_handler = source_handler
        self._agent_indices = agent_indices or {}
        self._dependency_configs = dependency_configs or {}
        self._storage_backend = storage_backend
        self._node_name = node_name
        self._retry_service = BatchRetryService(
            agent_indices=self._agent_indices,
            dependency_configs=self._dependency_configs,
            storage_backend=self._storage_backend,
        )

    def process_batch_results(
        self,
        batch_id: str,
        output_directory: str,
        base_directory: str,
        file_path: str,
        agent_config: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Process batch results and integrate them into workflow output system.

        Args:
            batch_id: Batch job ID
            output_directory: Output directory path
            base_directory: Base directory for relative paths
            file_path: Original input file path
            agent_config: Agent configuration

        Returns:
            Path to output file

        Raises:
            ProcessingError: If batch not completed or processing fails
        """
        try:
            manager = self._registry_manager_factory(output_directory)
            provider = self._client_resolver.get_for_batch_id(batch_id, manager, output_directory)

            if provider.check_status(batch_id) != BatchStatus.COMPLETED:
                raise ProcessingError("Batch job is not completed", context={"batch_id": batch_id})

            # Get entry and load context
            entry = manager.get_batch_job_by_id(batch_id)
            file_name = entry.file_name if entry else None
            context_map = (
                self._context_manager.load_batch_context_map(
                    output_directory, file_name or "default"
                )
                if file_name
                else {}
            )
            agent_config = self._apply_workflow_session_id(agent_config, entry)

            # Retrieve and process results
            batch_results = retrieve_and_reconcile(
                provider,
                batch_id,
                output_directory,
                context_map=context_map,
                record_count=entry.record_count if entry else None,
                file_name=file_name,
            )
            processed_data = self._convert_batch_results_to_workflow_format(
                batch_results,
                context_map=context_map,
                output_directory=output_directory,
                agent_config=agent_config,
            )
            main_output, side_output_data = BatchSideOutputHandler.separate(processed_data)

            # Save source data before writing output
            if self._source_handler:
                self._source_handler.save_task_source(
                    main_output,
                    file_path,
                    base_directory,
                    output_directory,
                    storage_backend=self._storage_backend,
                )

            # Write output files
            output_file = Path(output_directory) / Path(file_path).relative_to(
                base_directory
            ).with_suffix(".json")
            # Only create directory if not using storage backend
            if self._storage_backend is None:
                ensure_directory_exists(output_file, is_file=True)
            FileWriter(
                str(output_file),
                storage_backend=self._storage_backend,
                node_name=self._node_name,
                output_directory=output_directory,
            ).write_target(main_output)

            if side_output_data:
                side_output_file = (
                    create_side_output_directory(output_directory)
                    / Path(file_path).relative_to(base_directory).name
                )
                BatchSideOutputHandler.save(side_output_data, side_output_file)

            return str(output_file)
        except ProcessingError:
            raise
        except Exception as e:
            raise ProcessingError(
                f"Failed to process batch results to workflow output: {e}", cause=e
            ) from e

    def process_all_batch_results(
        self,
        output_directory: str,
        agent_config: Optional[Dict[str, Any]] = None,
        node_name: Optional[str] = None,
    ) -> List[str]:
        """Process all completed batch jobs in the registry.

        Args:
            output_directory: Output directory path
            agent_config: Agent configuration
            node_name: Override node_name for storage backend writes (uses self._node_name if not provided)

        Returns:
            List of output file paths

        Raises:
            ProcessingError: If no registry found or no files processed
        """
        manager = self._registry_manager_factory(output_directory)
        all_jobs = manager.get_all_jobs()
        if not all_jobs:
            raise ProcessingError(
                "No batch registry found", context={"output_directory": output_directory}
            )

        # Use provided node_name or fall back to instance default
        effective_node_name = node_name or self._node_name

        processed_files = []
        for file_name, entry in all_jobs.items():
            batch_id = entry.batch_id
            if not batch_id:
                continue

            # Check status using helper method
            if not self._is_batch_ready_for_processing(batch_id, output_directory):
                continue

            # Process batch
            try:
                output_file = self._process_single_batch_file(
                    batch_id=batch_id,
                    file_name=file_name,
                    entry=entry,
                    output_directory=output_directory,
                    agent_config=agent_config,
                    manager=manager,
                    node_name=effective_node_name,
                )
                if output_file:
                    processed_files.append(output_file)
            except Exception as e:
                logger.exception(
                    "Failed to process batch %s (%s): %s",
                    batch_id,
                    file_name,
                    e,
                    extra={
                        "batch_id": batch_id,
                        "file_name": file_name,
                        "output_directory": output_directory,
                        "operation": "batch_result_processing",
                        "total_processed": len(processed_files),
                        "registry_size": len(all_jobs),
                    },
                )
                continue

        if not processed_files:
            raise ProcessingError(
                "No batch results were successfully processed",
                context={"output_directory": output_directory},
            )
        return processed_files

    def _is_batch_ready_for_processing(self, batch_id: str, output_directory: str) -> bool:
        """Check if batch is ready for processing (completed status).

        Args:
            batch_id: The batch job ID to check
            output_directory: Directory containing batch registry

        Returns:
            True if batch status is COMPLETED, False otherwise
        """
        try:
            manager = self._registry_manager_factory(output_directory)
            provider = self._client_resolver.get_for_batch_id(batch_id, manager, output_directory)
            status = provider.check_status(batch_id)
            return status == BatchStatus.COMPLETED
        except Exception:
            return False

    def _determine_output_path(
        self, output_directory: str, file_name: Optional[str], batch_id: str
    ) -> Path:
        """Determine the output file path for batch results.

        Args:
            output_directory: Base output directory
            file_name: Original file name (may be None or "default")
            batch_id: Batch job ID for fallback naming

        Returns:
            Path object for the output file
        """
        if file_name and file_name != "default":
            return Path(output_directory) / f"{Path(file_name).stem}.json"
        return Path(output_directory) / f"{batch_id}_processed_output.json"

    def _write_batch_output(
        self,
        output_file: Path,
        main_output: List[Dict[str, Any]],
        side_output_data: Optional[List[Dict[str, Any]]],
        output_directory: str,
        node_name: Optional[str] = None,
    ) -> None:
        """Write main and side output files.

        Args:
            output_file: Path to write main output
            main_output: Main output data to write
            side_output_data: Optional side output data
            output_directory: Directory for side output
            node_name: Override node_name for storage backend writes
        """
        # Only create directory if not using storage backend
        if self._storage_backend is None:
            ensure_directory_exists(output_file, is_file=True)
        FileWriter(
            str(output_file),
            storage_backend=self._storage_backend,
            node_name=node_name or self._node_name,
            output_directory=output_directory,
        ).write_target(main_output)

        if side_output_data:
            side_output_dir = create_side_output_directory(output_directory)
            side_output_file = side_output_dir / output_file.name
            BatchSideOutputHandler.save(side_output_data, side_output_file)

    def _process_single_batch_file(
        self,
        batch_id: str,
        file_name: str,
        entry: BatchJobEntry,
        output_directory: str,
        agent_config: Optional[Dict[str, Any]],
        manager: BatchRegistryManager,
        node_name: Optional[str] = None,
    ) -> Optional[str]:
        """Process a single batch file and return output path.

        Supports retry for missing records if retry is enabled in agent_config.

        Args:
            batch_id: The batch job ID
            file_name: Original file name
            entry: Batch job registry entry
            output_directory: Output directory path
            agent_config: Agent configuration (may include retry settings)
            manager: Registry manager instance
            node_name: Override node_name for storage backend writes

        Returns:
            Output file path if successful, None if no results
        """
        start_time = time.time()

        context_map = self._context_manager.load_batch_context_map(
            output_directory, file_name or "default"
        )
        agent_config = self._apply_workflow_session_id(agent_config, entry)
        provider = self._client_resolver.get_for_batch_id(batch_id, manager, output_directory)

        # Use retry-aware retrieval if agent_config has retry enabled
        retry_config = (agent_config or {}).get("retry")
        if retry_config and retry_config.get("enabled", True):
            batch_results, exhausted_recovery = self._retry_service.retrieve_results_with_retry(
                provider,
                batch_id,
                output_directory,
                context_map=context_map,
                record_count=entry.record_count,
                file_name=file_name,
                agent_config=agent_config,
            )
        else:
            batch_results = retrieve_and_reconcile(
                provider,
                batch_id,
                output_directory,
                context_map=context_map,
                record_count=entry.record_count,
                file_name=file_name,
            )
            exhausted_recovery = None

            # Run reprompt validation even when retry is disabled
            # retrieve_results_with_retry calls this internally, so only needed here
            batch_results = self._retry_service.validate_and_reprompt(
                results=batch_results,
                provider=provider,
                context_map=context_map,
                output_directory=output_directory,
                file_name=file_name,
                agent_config=agent_config,
                agent_indices=self._agent_indices,
                dependency_configs=self._dependency_configs,
            )

        # Convert results to workflow format
        # exhausted_recovery is a dict mapping custom_id -> RecoveryMetadata for records that never succeeded
        processed_data = self._convert_batch_results_to_workflow_format(
            batch_results,
            context_map=context_map,
            output_directory=output_directory,
            agent_config=agent_config,
            exhausted_recovery=exhausted_recovery,
        )

        # Recovery metadata is now handled per-record:
        # - Retried records: _process_successful_result adds _recovery from BatchResult.recovery_metadata
        # - Missing/passthrough records: _stage_6_merge_passthroughs adds _recovery from exhausted_recovery dict
        # - First-try successes: No _recovery (correct - they didn't need retry)

        main_output, side_output_data = BatchSideOutputHandler.separate(processed_data)

        # Determine output path and write files
        output_file = self._determine_output_path(output_directory, file_name, batch_id)
        self._write_batch_output(
            output_file, main_output, side_output_data, output_directory, node_name
        )

        # Calculate completion statistics
        elapsed_time = time.time() - start_time
        total_count = len(batch_results)
        successful_count = sum(1 for r in batch_results if r.success)
        failed_count = total_count - successful_count

        # Fire batch complete event (B003)
        fire_event(
            BatchCompleteEvent(
                batch_id=batch_id,
                agent_name=file_name or "default",
                total=total_count,
                completed=successful_count,
                failed=failed_count,
                elapsed_time=elapsed_time,
            )
        )

        # Update registry status to completed
        manager.update_status(batch_id, BatchStatus.COMPLETED)

        return str(output_file)

    def _convert_batch_results_to_workflow_format(
        self,
        batch_results: List[BatchResult],
        *,
        context_map: Optional[Dict[str, Any]] = None,
        output_directory: Optional[str] = None,
        agent_config: Optional[Dict[str, Any]] = None,
        exhausted_recovery: Optional[Dict[str, RecoveryMetadata]] = None,
    ) -> List[Dict[str, Any]]:
        """Convert batch results to workflow format.

        Args:
            batch_results: Raw batch results
            context_map: Context map for processing
            output_directory: Output directory path
            agent_config: Agent configuration
            exhausted_recovery: Per-record recovery metadata for exhausted records (custom_id -> RecoveryMetadata)

        Returns:
            Processed results in workflow format
        """
        return self._result_processor.process(
            batch_results=batch_results,
            context_map=context_map,
            output_directory=output_directory,
            agent_config=agent_config,
            exhausted_recovery=exhausted_recovery,
        )

    @staticmethod
    def _apply_workflow_session_id(
        agent_config: Optional[Dict[str, Any]],
        entry: Optional[BatchJobEntry],
    ) -> Optional[Dict[str, Any]]:
        """
        Preserve workflow context used at batch submission time.

        Ensures deterministic version correlation across resumed batch processing
        by restoring workflow_session_id, is_versioned_agent, and version_base_name.
        """
        if not entry:
            return agent_config

        # Create config if None (batch collect mode without agent_config)
        updated_config = agent_config.copy() if agent_config else {}

        # Restore workflow session ID
        if entry.workflow_session_id:
            updated_config["workflow_session_id"] = entry.workflow_session_id

        # Restore version context for loop correlation
        if entry.is_versioned_agent is not None:
            updated_config["is_versioned_agent"] = entry.is_versioned_agent
        if entry.version_base_name is not None:
            updated_config["version_base_name"] = entry.version_base_name

        return updated_config if updated_config else None
