"""Batch processing service for managing batch job lifecycle and results."""

import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List, Union
from datetime import datetime

from agent_actions.logging.context import CorrelationContext
from agent_actions.llm_invocation.batch.loaders_batch_data_loader import BatchDataLoader
from agent_actions.io.file_writer import FileWriter
from agent_actions.utilities.path_utils import ensure_directory_exists, create_side_output_directory
from agent_actions.orchestration.dependency_injection import registry
from agent_actions.llm_invocation.providers.batch_client_base import BaseBatchClient, BatchResult
from agent_actions.errors import (
    ConfigValidationError,
    ExternalServiceError,
    ProcessingError,
)  # New modular pattern!
from agent_actions.llm_invocation.batch.batch_registry_manager import BatchRegistryManager
from agent_actions.llm_invocation.batch.batch_models import BatchJobEntry
from agent_actions.llm_invocation.batch.batch_passthrough_builder import BatchPassthroughBuilder
from agent_actions.llm_invocation.batch.batch_result_processor import BatchResultProcessor
from agent_actions.llm_invocation.batch.batch_task_preparator import BatchTaskPreparator
from agent_actions.llm_invocation.batch.batch_context_manager import BatchContextManager
from agent_actions.llm_invocation.batch.batch_side_output_handler import BatchSideOutputHandler
from agent_actions.llm_invocation.batch.batch_client_resolver import BatchClientResolver
from agent_actions.llm_invocation.batch.batch_retry_orchestrator import BatchRetryOrchestrator
from agent_actions.llm_invocation.batch.batch_retry_config import RetryConfig, get_retry_config
from agent_actions.llm_invocation.batch.batch_constants import BatchStatus

logger = logging.getLogger(__name__)


@registry.register_service("batch_service")
class BatchService:  # pylint: disable=too-many-instance-attributes
    """
    Pure orchestrator for batch processing.

    Delegates to specialized services for all operations.
    """

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def __init__(
        self,
        provider: Optional[BaseBatchClient] = None,
        agent_indices: Optional[Dict[str, int]] = None,
        dependency_configs: Optional[Dict[str, Dict]] = None,
        force_batch: bool = False,
        task_preparator: Optional[BatchTaskPreparator] = None,
        result_processor: Optional[BatchResultProcessor] = None,
        context_manager: Optional[BatchContextManager] = None,
        client_resolver: Optional[BatchClientResolver] = None,
        job_manager: Optional[Any] = None,  # BatchJobManager, uses Any to avoid circular import
        source_handler: Optional[Any] = None,  # BatchSourceHandler
        retry_orchestrator: Optional[BatchRetryOrchestrator] = None,
        default_retry_config: Optional[RetryConfig] = None,
    ):
        """Initialize batch service (pure orchestrator with dependency injection)."""
        # pylint: disable=import-outside-toplevel
        from agent_actions.llm_invocation.batch.batch_job_manager import BatchJobManager
        from agent_actions.llm_invocation.batch.batch_source_handler import BatchSourceHandler

        self.data_loader = BatchDataLoader()
        self.provider = provider
        self.force_batch = force_batch
        self._provider_cache = {}
        self.agent_indices = agent_indices or {}
        self.dependency_configs = dependency_configs or {}
        self._registry_manager = None
        self._task_preparator = task_preparator or BatchTaskPreparator(
            agent_indices=agent_indices, dependency_configs=dependency_configs
        )
        self._result_processor = result_processor or BatchResultProcessor()
        self._context_manager = context_manager or BatchContextManager()
        self._client_resolver = client_resolver or BatchClientResolver(
            client_cache=self._provider_cache, default_client=self.provider
        )
        self._job_manager = job_manager or BatchJobManager(client_resolver=self._client_resolver)
        self._source_handler = source_handler or BatchSourceHandler()
        self._default_retry_config = default_retry_config or RetryConfig.default()
        # Retry orchestrator is lazily initialized when registry_manager is available
        self._retry_orchestrator = retry_orchestrator

    def _get_retry_orchestrator(self, output_directory: str) -> BatchRetryOrchestrator:
        """Get or create retry orchestrator for output directory."""
        if self._retry_orchestrator is None:
            manager = self._get_registry_manager(output_directory)
            self._retry_orchestrator = BatchRetryOrchestrator(
                registry_manager=manager,
                client_resolver=self._client_resolver,
                task_preparator=self._task_preparator,
                context_manager=self._context_manager,
                retry_config=self._default_retry_config,
            )
        return self._retry_orchestrator

    def _get_registry_manager(self, output_directory: str) -> BatchRegistryManager:
        """Get or create registry manager for output directory."""
        if self._registry_manager is None and output_directory:
            self._registry_manager = BatchRegistryManager(
                Path(output_directory) / "batch" / ".batch_registry.json"
            )
            # Share registry manager with job manager
            self._job_manager.set_registry_manager(self._registry_manager)
        return self._registry_manager

    def prepare_batch_tasks(self, agent_config, data, output_directory=None, batch_name=None):
        """Prepare batch tasks from data (delegates to BatchTaskPreparator)."""
        provider = self._client_resolver.get_for_config(agent_config)
        prepared = self._task_preparator.prepare_tasks(
            agent_config=agent_config,
            data=data,
            provider=provider,
            output_directory=output_directory,
            batch_name=batch_name,
        )
        logger.debug(
            "Task preparation complete: %d tasks, %d filtered, %d skipped",
            prepared.task_count,
            prepared.stats.filtered_items,
            prepared.stats.skipped_items,
        )
        return prepared.tasks, prepared.context_map

    # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
    def submit_batch_job(self, agent_config, batch_name, data, output_directory=None, force=False):
        """Submit a batch job for processing."""
        force_submission = force or self.force_batch
        if not force_submission and output_directory:
            # Check for existing in-flight batch
            manager = self._get_registry_manager(output_directory)
            entry = manager.get_batch_job(batch_name or "default")
            if entry and entry.is_in_flight:
                logger.info(
                    "Found existing in-flight batch job for %s: %s", batch_name, entry.batch_id
                )
                logger.info(
                    "Skipping new batch submission. "
                    "Use --batch_continue to process completed batches."
                )
                return entry.batch_id

        tasks, context_map = self.prepare_batch_tasks(
            agent_config, data, output_directory, batch_name
        )
        if not tasks:
            where_config = agent_config.get("where_clause") or {}
            behavior = where_config.get("behavior", "filter")
            if behavior == "filter":
                return {"type": "passthrough", "data": [], "output_directory": output_directory}
            if behavior == "skip":
                return BatchPassthroughBuilder(output_directory).from_context(
                    context_map, reason="where_clause_not_matched"
                )
            return BatchPassthroughBuilder(output_directory).from_data(
                data, reason="conditional_clause_failed"
            )

        self._context_manager.save_batch_context_map(context_map, output_directory, batch_name)
        try:
            provider = self._client_resolver.get_for_config(agent_config)
            provider_type = agent_config.get("model_vendor")
            if not provider_type:
                raise ConfigValidationError(
                    "model_vendor", "Missing required field 'model_vendor' for batch processing."
                )
            provider_type = provider_type.lower()

            # Providers now return (batch_id, initial_status)
            batch_id, initial_status = provider.submit_batch(tasks, batch_name, output_directory)

            # Set batch_id in correlation context for tracking
            CorrelationContext.set_batch(batch_id)

            # Log batch submission with metrics
            logger.info(
                "Batch job submitted",
                extra={
                    "operation": "submit_batch_job",
                    "batch_id": batch_id,
                    "batch_name": batch_name,
                    "batch_size": len(tasks),
                    "provider": provider_type,
                    "initial_status": initial_status,
                },
            )

            # Save batch job to registry with initial status from provider
            if output_directory:
                manager = self._get_registry_manager(output_directory)

                entry = BatchJobEntry(
                    batch_id=batch_id,
                    status=initial_status,  # Use status from provider
                    timestamp=datetime.now().isoformat(),
                    provider=provider_type,
                    record_count=len(tasks),
                )
                manager.save_batch_job(batch_name or "default", entry)

            return batch_id
        except Exception as e:
            raise ExternalServiceError(
                provider_type, f"Failed to submit batch job: {e}", cause=e
            ) from e

    def check_status(self, batch_id: str, output_directory: str = None):
        """Check the status of a batch job."""
        try:
            manager = self._get_registry_manager(output_directory) if output_directory else None
            provider = self._client_resolver.get_for_batch_id(batch_id, manager, output_directory)
            return provider.check_status(batch_id)
        except Exception as e:
            vendor = (
                getattr(provider, "vendor_type", "unknown") if "provider" in locals() else "unknown"
            )
            raise ExternalServiceError(vendor, f"Failed to check batch status: {e}", cause=e) from e

    def retrieve_results(self, batch_id: str, output_dir: str, file_path: str = None):
        """Retrieve and save results from a completed batch job."""
        try:
            manager = self._get_registry_manager(output_dir)
            provider = self._client_resolver.get_for_batch_id(batch_id, manager, output_dir)

            # Get entry from registry
            entry = manager.get_batch_job_by_id(batch_id)
            file_name = entry.file_name if entry else None

            # Load context and retrieve results
            context_map = (
                self._context_manager.load_batch_context_map(output_dir, file_name or "default")
                if file_name
                else {}
            )
            batch_results = self._retrieve_results(
                provider,
                batch_id,
                output_dir,
                context_map=context_map,
                record_count=entry.record_count if entry else None,
                file_name=file_name,
            )

            # Write results to JSONL
            output_path = Path(output_dir)
            result_file = output_path / (
                f"{Path(file_path).stem}_results.jsonl"
                if file_path
                else f"{batch_id}_results.jsonl"
            )
            if not result_file.exists():
                ensure_directory_exists(output_path)
                with open(result_file, "w", encoding="utf-8") as f:
                    for result in batch_results:
                        raw_format = {
                            "custom_id": result.custom_id,
                            "response": {
                                "body": {
                                    "choices": [
                                        {"message": {"content": json.dumps(result.content)}}
                                    ],
                                    "usage": result.usage,
                                }
                            },
                        }
                        f.write(json.dumps(raw_format) + "\n")
            return result_file
        except Exception as e:
            vendor = (
                getattr(provider, "vendor_type", "unknown") if "provider" in locals() else "unknown"
            )
            raise ExternalServiceError(
                vendor, f"Failed to retrieve batch results: {e}", cause=e
            ) from e

    def process_batch_results(
        self,
        batch_id: str,
        output_directory: str,
        base_directory: str,
        file_path: str,
        agent_config: Optional[Dict[str, Any]] = None,
    ):
        """Process batch results and integrate them into workflow output system."""
        try:
            manager = self._get_registry_manager(output_directory)
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
                _agent_config=agent_config,
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
            self._save_task_source(main_output, file_path, base_directory, output_directory)

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
        except Exception as e:
            raise ProcessingError(
                f"Failed to process batch results to workflow output: {e}", cause=e
            ) from e

    def _convert_batch_results_to_workflow_format(
        self, batch_results, *, context_map=None, output_directory=None, agent_config=None
    ):
        """Convert batch results to workflow format (delegates to BatchResultProcessor)."""
        return self._result_processor.process(
            batch_results=batch_results,
            context_map=context_map,
            output_directory=output_directory,
            agent_config=agent_config,
        )

    def _is_batch_ready_for_processing(self, batch_id: str, output_directory: str) -> bool:
        """Check if batch is ready for processing (completed status).

        Args:
            batch_id: The batch job ID to check
            output_directory: Directory containing batch registry

        Returns:
            True if batch status is COMPLETED, False otherwise
        """
        try:
            status = self.check_status(batch_id, output_directory)
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
            _agent_config=agent_config,
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
                "main_output_count": len(main_output) if isinstance(main_output, list) else 1,
                "side_output_count": len(side_output_data) if side_output_data else 0,
                "output_file": str(output_file),
            },
        )

        return str(output_file)

    def process_all_batch_results(self, output_directory: str, agent_config: Dict[str, Any] = None):
        """Process all completed batch jobs in the registry to workflow output."""
        manager = self._get_registry_manager(output_directory)
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

    def _save_task_source(
        self,
        src_text: Union[Dict[str, Any], List[Dict[str, Any]]],
        file_path,
        base_directory,
        output_directory,
    ):
        """Save task source data (delegates to BatchSourceHandler)."""
        self._source_handler.save_task_source(src_text, file_path, base_directory, output_directory)

    def are_all_batch_jobs_completed(self, output_directory: str) -> bool:
        """Check if all batch jobs in the registry are completed (delegates to BatchJobManager)."""
        return self._job_manager.are_all_jobs_completed(output_directory)

    def get_batch_registry_status(self, output_directory: str) -> str:
        """Get overall status of all batch jobs in the registry."""
        return self._job_manager.get_registry_status(output_directory)

    def _retrieve_results(
        self,
        provider: BaseBatchClient,
        batch_id: str,
        output_directory: Optional[str],
        *,
        context_map: Optional[Dict[str, Any]] = None,
        _agent_config: Optional[Dict[str, Any]] = None,
        record_count: Optional[int] = None,
        file_name: Optional[str] = None,
    ) -> List[BatchResult]:
        """Retrieve batch results from provider and log reconciliation."""
        # pylint: disable=import-outside-toplevel
        from agent_actions.llm_invocation.batch.batch_result_reconciler import BatchResultReconciler

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

    def retry_batch_job(
        self,
        batch_id: str,
        output_directory: str,
        agent_config: Optional[Dict[str, Any]] = None,
        max_attempts: Optional[int] = None,
    ) -> Optional[str]:
        """
        Manually retry a batch job.

        Triggers the retry orchestration for a completed batch that has missing records.

        Args:
            batch_id: ID of the batch to retry
            output_directory: Output directory containing batch registry
            agent_config: Agent configuration (loaded from registry if not provided)
            max_attempts: Override max retry attempts

        Returns:
            Retry batch ID if retry was triggered, None otherwise
        """
        manager = self._get_registry_manager(output_directory)
        entry = manager.get_batch_job_by_id(batch_id)

        if not entry:
            raise ProcessingError(
                f"Batch job {batch_id} not found in registry",
                context={"batch_id": batch_id, "output_directory": output_directory},
            )

        if entry.status != BatchStatus.COMPLETED:
            raise ProcessingError(
                f"Batch job {batch_id} is not completed (status: {entry.status})",
                context={"batch_id": batch_id, "status": entry.status},
            )

        # Find file_name for this batch
        file_name = None
        for fname, e in manager.get_all_jobs().items():
            if e.batch_id == batch_id:
                file_name = fname
                break

        if not file_name:
            file_name = "default"

        # Load context map
        context_map = self._context_manager.load_batch_context_map(output_directory, file_name)

        # Get provider
        provider = self._client_resolver.get_for_batch_id(batch_id, manager, output_directory)

        # Retrieve results and reconcile
        batch_results = self._retrieve_results(
            provider,
            batch_id,
            output_directory,
            context_map=context_map,
            record_count=entry.record_count,
            file_name=file_name,
        )

        # Create reconciler to find missing records
        # pylint: disable=import-outside-toplevel
        from agent_actions.llm_invocation.batch.batch_result_reconciler import (
            BatchResultReconciler,
        )

        reconciler = BatchResultReconciler(context_map)
        for result in batch_results:
            reconciler.mark_processed(result.custom_id)
        reconciliation = reconciler.reconcile()

        if not reconciliation.missing_ids:
            logger.info("No missing records in batch %s, retry not needed", batch_id)
            return None

        # Build retry config
        retry_config = get_retry_config(agent_config, self._default_retry_config)
        if max_attempts is not None:
            retry_config = RetryConfig(enabled=True, max_attempts=max_attempts)

        # Get orchestrator and run retry chain
        orchestrator = self._get_retry_orchestrator(output_directory)

        result = orchestrator.orchestrate_retry_chain(
            original_batch_id=batch_id,
            initial_reconciliation=reconciliation,
            context_map=context_map,
            agent_config=agent_config or {},
            output_directory=output_directory,
            original_file_name=file_name,
            retry_config=retry_config,
        )

        logger.info(
            "Retry chain completed for %s: %d attempts, %d success, %d still missing",
            batch_id,
            result.total_attempts,
            result.final_success_count,
            result.final_missing_count,
        )

        return result.retry_batch_ids[-1] if result.retry_batch_ids else None
