"""Batch job lifecycle and registry status management."""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from agent_actions.llm_invocation.batch.infrastructure.batch_registry_manager import (
    BatchRegistryManager,
)
from agent_actions.llm_invocation.batch.infrastructure.batch_client_resolver import (
    BatchClientResolver,
)
from agent_actions.llm_invocation.batch.core.batch_models import BatchJobEntry
from agent_actions.llm_invocation.batch.core.batch_constants import BatchStatus

logger = logging.getLogger(__name__)


@dataclass
class RetryChainStatus:
    """Status summary for a batch retry chain."""

    original_batch_id: str
    total_attempts: int  # Number of retry batches (0 = no retries)
    current_status: str  # Status of the most recent batch in chain
    all_batch_ids: List[str] = field(default_factory=list)
    total_records: int = 0
    completed_records: int = 0
    missing_records: int = 0

    @property
    def is_complete(self) -> bool:
        """Check if the retry chain is fully complete."""
        return self.current_status in BatchStatus.terminal_states()

    @property
    def has_retries(self) -> bool:
        """Check if any retries were performed."""
        return self.total_attempts > 0


class BatchJobManager:
    """
    Manages batch job lifecycle and registry status.

    Handles checking job completion status and aggregating registry state.
    """

    def __init__(
        self,
        client_resolver: BatchClientResolver,
        registry_manager: Optional[BatchRegistryManager] = None,
    ):
        """Initialize batch job manager.

        Args:
            client_resolver: Resolver for getting batch clients
            registry_manager: Optional registry manager (can be set later)
        """
        self._client_resolver = client_resolver
        self._registry_manager = registry_manager

    def set_registry_manager(self, registry_manager: BatchRegistryManager) -> None:
        """Set the registry manager (for lazy initialization)."""
        self._registry_manager = registry_manager

    def _check_status(self, batch_id: str, output_directory: str) -> str:
        """Check status of a batch job via client."""
        manager = self._registry_manager
        client = self._client_resolver.get_for_batch_id(batch_id, manager, output_directory)
        return client.check_status(batch_id)

    def are_all_jobs_completed(self, output_directory: str) -> bool:
        """Check if all batch jobs in the registry are completed.

        Args:
            output_directory: Directory containing the batch registry

        Returns:
            True if all jobs are completed, False otherwise
        """
        if not output_directory:
            return True

        registry_file = Path(output_directory) / "batch" / ".batch_registry.json"
        if not registry_file.exists():
            return True

        try:
            with open(registry_file, "r", encoding="utf-8") as f:
                registry = json.load(f)

            if not registry:
                return True

            for file_name, entry in registry.items():
                batch_id = entry.get("batch_id")
                if not batch_id:
                    continue

                try:
                    actual_status = self._check_status(batch_id, str(output_directory))
                    if actual_status != entry.get("status"):
                        entry["status"] = actual_status

                    if actual_status not in BatchStatus.terminal_states():
                        return False

                except Exception as e:
                    logger.warning(
                        "Failed to check status for batch %s in registry: %s",
                        batch_id,
                        e,
                        exc_info=True,
                        extra={
                            "batch_id": batch_id,
                            "file_name": file_name,
                            "output_directory": output_directory,
                            "operation": "registry_status_check",
                        },
                    )
                    return False

            # Update registry file with new statuses
            with open(registry_file, "w", encoding="utf-8") as f:
                json.dump(registry, f, indent=2)

            return True

        except (json.JSONDecodeError, KeyError):
            return True

    def get_registry_status(self, output_directory: str) -> str:
        """Get the overall status of all batch jobs in the registry.

        Args:
            output_directory: Directory containing the batch registry

        Returns:
            Status string: 'completed', 'in_progress', 'partial_failed',
                          'no_batches', 'error', or 'unknown'
        """
        if not output_directory:
            return "no_batches"

        registry_file = Path(output_directory) / "batch" / ".batch_registry.json"
        if not registry_file.exists():
            return "no_batches"

        try:
            with open(registry_file, "r", encoding="utf-8") as f:
                registry = json.load(f)

            if not registry:
                return "no_batches"

            completed_count = 0
            failed_count = 0
            in_progress_count = 0

            for file_name, entry in registry.items():
                batch_id = entry.get("batch_id")
                if not batch_id:
                    continue

                try:
                    actual_status = self._check_status(batch_id, str(output_directory))
                    if actual_status == BatchStatus.COMPLETED:
                        completed_count += 1
                    elif actual_status in (BatchStatus.FAILED, BatchStatus.CANCELLED):
                        failed_count += 1
                    else:
                        in_progress_count += 1

                except Exception as e:
                    logger.debug(
                        "Could not check status for batch %s, treating as in_progress: %s",
                        batch_id,
                        e,
                        extra={
                            "batch_id": batch_id,
                            "file_name": file_name,
                            "operation": "status_aggregation",
                        },
                    )
                    in_progress_count += 1

            total_jobs = len(registry)
            if completed_count == total_jobs:
                return "completed"
            if failed_count > 0:
                return "partial_failed"
            if in_progress_count > 0:
                return "in_progress"
            return "unknown"

        except (json.JSONDecodeError, KeyError):
            return "error"

    def get_batch_children(self, batch_id: str, output_directory: str) -> List[BatchJobEntry]:
        """
        Get all retry batches for a parent batch.

        Args:
            batch_id: Parent batch ID
            output_directory: Directory containing batch registry

        Returns:
            List of BatchJobEntry for retry batches
        """
        if not self._registry_manager:
            registry_file = Path(output_directory) / "batch" / ".batch_registry.json"
            if not registry_file.exists():
                return []
            self._registry_manager = BatchRegistryManager(registry_file)

        all_jobs = self._registry_manager.get_all_jobs()
        children = []

        for entry in all_jobs.values():
            if entry.parent_batch_id == batch_id:
                children.append(entry)

        # Sort by retry_attempt
        children.sort(key=lambda e: e.retry_attempt)
        return children

    def get_batch_lineage(self, batch_id: str, output_directory: str) -> List[BatchJobEntry]:
        """
        Get full chain from original batch to all retries.

        Walks up to find root, then collects all descendants.

        Args:
            batch_id: Any batch ID in the chain
            output_directory: Directory containing batch registry

        Returns:
            List of BatchJobEntry from original through all retries, in order
        """
        if not self._registry_manager:
            registry_file = Path(output_directory) / "batch" / ".batch_registry.json"
            if not registry_file.exists():
                return []
            self._registry_manager = BatchRegistryManager(registry_file)

        all_jobs = self._registry_manager.get_all_jobs()

        # Build lookup by batch_id
        batch_lookup = {entry.batch_id: entry for entry in all_jobs.values()}

        if batch_id not in batch_lookup:
            return []

        # Walk up to find root
        current = batch_lookup[batch_id]
        while current.parent_batch_id and current.parent_batch_id in batch_lookup:
            current = batch_lookup[current.parent_batch_id]

        root_id = current.batch_id

        # Now collect all batches in the chain
        lineage = [current]
        to_process = [root_id]
        processed = {root_id}

        while to_process:
            parent_id = to_process.pop(0)
            for entry in all_jobs.values():
                if entry.parent_batch_id == parent_id and entry.batch_id not in processed:
                    lineage.append(entry)
                    processed.add(entry.batch_id)
                    to_process.append(entry.batch_id)

        # Sort by retry_attempt
        lineage.sort(key=lambda e: e.retry_attempt)
        return lineage

    def get_retry_chain_status(self, batch_id: str, output_directory: str) -> RetryChainStatus:
        """
        Get aggregated status for a batch retry chain.

        Args:
            batch_id: Any batch ID in the chain
            output_directory: Directory containing batch registry

        Returns:
            RetryChainStatus with chain summary
        """
        lineage = self.get_batch_lineage(batch_id, output_directory)

        if not lineage:
            return RetryChainStatus(
                original_batch_id=batch_id,
                total_attempts=0,
                current_status="unknown",
            )

        original = lineage[0]
        latest = lineage[-1]

        total_records = original.record_count or 0
        retry_count = len(lineage) - 1  # Exclude original

        return RetryChainStatus(
            original_batch_id=original.batch_id,
            total_attempts=retry_count,
            current_status=latest.status,
            all_batch_ids=[e.batch_id for e in lineage],
            total_records=total_records,
        )
