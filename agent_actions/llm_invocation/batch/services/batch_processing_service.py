"""Batch processing service for processing batch job results.

This service encapsulates all result processing functionality, extracted from
BatchService to follow Single Responsibility Principle.
"""

import logging
from pathlib import Path
from typing import Optional, Dict, Any, List, Callable

from agent_actions.io.file_writer import FileWriter
from agent_actions.utilities.path_utils import ensure_directory_exists, create_side_output_directory
from agent_actions.llm_invocation.batch.core.batch_constants import BatchStatus
from agent_actions.llm_invocation.batch.infrastructure.batch_context_manager import (
    BatchContextManager,
)
from agent_actions.llm_invocation.batch.infrastructure.batch_client_resolver import (
    BatchClientResolver,
)
from agent_actions.llm_invocation.batch.infrastructure.batch_registry_manager import (
    BatchRegistryManager,
)
from agent_actions.llm_invocation.batch.processing.batch_result_processor import (
    BatchResultProcessor,
)
from agent_actions.llm_invocation.batch.processing.batch_side_output_handler import (
    BatchSideOutputHandler,
)
from agent_actions.llm_invocation.batch.core.batch_models import BatchJobEntry
from agent_actions.llm_invocation.providers.batch_client_base import BaseBatchClient, BatchResult
from agent_actions.errors import ProcessingError

logger = logging.getLogger(__name__)


class BatchProcessingService:
    """Service for processing batch job results.

    Handles result retrieval, conversion, and output file generation.
    """

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def __init__(
        self,
        client_resolver: BatchClientResolver,
        context_manager: BatchContextManager,
        result_processor: BatchResultProcessor,
        registry_manager_factory: Callable[[str], BatchRegistryManager],
        source_handler: Optional[Any] = None,
    ):
        """Initialize processing service with dependencies.

        Args:
            client_resolver: Resolver for batch API clients
            context_manager: Manager for batch context persistence
            result_processor: Processor for batch results
            registry_manager_factory: Factory function to create registry managers
            source_handler: Optional handler for source data
        """
        self._client_resolver = client_resolver
        self._context_manager = context_manager
        self._result_processor = result_processor
        self._registry_manager_factory = registry_manager_factory
        self._source_handler = source_handler

    # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
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

            # Retrieve and process results
            batch_results = self._retrieve_results(
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
                    main_output, file_path, base_directory, output_directory
                )

            # Write output files
            output_file = Path(output_directory) / Path(file_path).relative_to(
                base_directory
            ).with_suffix(".json")
            ensure_directory_exists(output_file, is_file=True)
            FileWriter(str(output_file)).write_target(main_output)

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
        self, output_directory: str, agent_config: Optional[Dict[str, Any]] = None
    ) -> List[str]:
        """Process all completed batch jobs in the registry.

        Args:
            output_directory: Output directory path
            agent_config: Agent configuration

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
                )
                if output_file:
                    processed_files.append(output_file)
            except Exception as e:  # pylint: disable=broad-exception-caught
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
        except Exception:  # pylint: disable=broad-exception-caught
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
    ) -> None:
        """Write main and side output files.

        Args:
            output_file: Path to write main output
            main_output: Main output data to write
            side_output_data: Optional side output data
            output_directory: Directory for side output
        """
        ensure_directory_exists(output_file, is_file=True)
        FileWriter(str(output_file)).write_target(main_output)

        if side_output_data:
            side_output_dir = create_side_output_directory(output_directory)
            side_output_file = side_output_dir / output_file.name
            BatchSideOutputHandler.save(side_output_data, side_output_file)

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def _process_single_batch_file(
        self,
        batch_id: str,
        file_name: str,
        entry: BatchJobEntry,
        output_directory: str,
        agent_config: Optional[Dict[str, Any]],
        manager: BatchRegistryManager,
    ) -> Optional[str]:
        """Process a single batch file and return output path.

        Args:
            batch_id: The batch job ID
            file_name: Original file name
            entry: Batch job registry entry
            output_directory: Output directory path
            agent_config: Agent configuration
            manager: Registry manager instance

        Returns:
            Output file path if successful, None if no results
        """
        context_map = self._context_manager.load_batch_context_map(
            output_directory, file_name or "default"
        )
        provider = self._client_resolver.get_for_batch_id(batch_id, manager, output_directory)
        batch_results = self._retrieve_results(
            provider,
            batch_id,
            output_directory,
            context_map=context_map,
            record_count=entry.record_count,
            file_name=file_name,
        )

        if not batch_results:
            return None

        # Convert results to workflow format
        processed_data = self._convert_batch_results_to_workflow_format(
            batch_results,
            context_map=context_map,
            output_directory=output_directory,
            agent_config=agent_config,
        )
        main_output, side_output_data = BatchSideOutputHandler.separate(processed_data)

        # Determine output path and write files
        output_file = self._determine_output_path(output_directory, file_name, batch_id)
        self._write_batch_output(output_file, main_output, side_output_data, output_directory)

        # Log completion
        logger.info(
            "Batch job completed and processed",
            extra={
                "operation": "process_batch_results",
                "batch_id": batch_id,
                "file_name": file_name,
                "results_count": len(batch_results),
                "main_output_count": (len(main_output) if isinstance(main_output, list) else 1),
                "side_output_count": len(side_output_data) if side_output_data else 0,
                "output_file": str(output_file),
            },
        )

        return str(output_file)

    def _convert_batch_results_to_workflow_format(
        self,
        batch_results: List[BatchResult],
        *,
        context_map: Optional[Dict[str, Any]] = None,
        output_directory: Optional[str] = None,
        agent_config: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Convert batch results to workflow format.

        Args:
            batch_results: Raw batch results
            context_map: Context map for processing
            output_directory: Output directory path
            agent_config: Agent configuration

        Returns:
            Processed results in workflow format
        """
        return self._result_processor.process(
            batch_results=batch_results,
            context_map=context_map,
            output_directory=output_directory,
            agent_config=agent_config,
        )

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def _retrieve_results(
        self,
        provider: BaseBatchClient,
        batch_id: str,
        output_directory: Optional[str],
        *,
        context_map: Optional[Dict[str, Any]] = None,
        record_count: Optional[int] = None,
        file_name: Optional[str] = None,
    ) -> List[BatchResult]:
        """Retrieve batch results from provider and log reconciliation.

        Args:
            provider: Batch API client
            batch_id: Batch job ID
            output_directory: Output directory path
            context_map: Context map for reconciliation
            record_count: Expected record count
            file_name: Original file name

        Returns:
            List of batch results
        """
        # pylint: disable=import-outside-toplevel
        from agent_actions.llm_invocation.batch.processing.batch_result_reconciler import (
            BatchResultReconciler,
        )

        batch_results = provider.retrieve_results(batch_id, output_directory)

        # Log reconciliation
        expected = BatchResultReconciler.collect_expected_custom_ids(context_map or {})
        received = BatchResultReconciler.collect_result_custom_ids(batch_results)
        BatchResultReconciler.log_batch_reconciliation(
            batch_id=batch_id,
            expected_count=len(expected) or record_count or 0,
            received_count=len(received),
            file_name=file_name,
        )

        return batch_results
