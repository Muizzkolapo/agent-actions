"""Batch retrieval service for downloading batch job results."""

import json
import logging
from collections.abc import Callable
from pathlib import Path

from agent_actions.errors import ExternalServiceError
from agent_actions.llm.batch.infrastructure.batch_client_resolver import (
    BatchClientResolver,
)
from agent_actions.llm.batch.infrastructure.context import (
    BatchContextManager,
)
from agent_actions.llm.batch.infrastructure.registry import (
    BatchRegistryManager,
)
from agent_actions.llm.batch.services.shared import retrieve_and_reconcile
from agent_actions.llm.providers.batch_base import BatchResult
from agent_actions.utils.path_utils import ensure_directory_exists

logger = logging.getLogger(__name__)


class BatchRetrievalService:
    """Service for retrieving batch job results.

    Handles downloading results from batch API providers and saving to JSONL files.
    """

    def __init__(
        self,
        client_resolver: BatchClientResolver,
        context_manager: BatchContextManager,
        registry_manager_factory: Callable[[str], BatchRegistryManager],
    ):
        """Initialize retrieval service with dependencies.

        Args:
            client_resolver: Resolver for batch API clients
            context_manager: Manager for batch context persistence
            registry_manager_factory: Factory function to create registry managers
        """
        self._client_resolver = client_resolver
        self._context_manager = context_manager
        self._registry_manager_factory = registry_manager_factory

    def retrieve_results(
        self,
        batch_id: str,
        output_dir: str,
        file_path: str | None = None,
    ) -> Path:
        """Retrieve and save results from a completed batch job.

        Args:
            batch_id: ID of the batch job to retrieve results for
            output_dir: Directory to save results to
            file_path: Optional original file path for naming output

        Returns:
            Path to the saved results file

        Raises:
            ExternalServiceError: If retrieval fails
        """
        provider = None
        try:
            manager = self._registry_manager_factory(output_dir)
            provider = self._client_resolver.get_for_batch_id(batch_id, manager, output_dir)

            entry = manager.get_batch_job_by_id(batch_id)
            file_name = entry.file_name if entry else None

            context_map = (
                self._context_manager.load_batch_context_map(output_dir, file_name)
                if file_name
                else {}
            )
            batch_results = retrieve_and_reconcile(
                provider,
                batch_id,
                output_dir,
                context_map=context_map,
                record_count=entry.record_count if entry else None,
                file_name=file_name,
            )

            output_path = Path(output_dir)
            result_file = output_path / (
                f"{Path(file_path).stem}_results.jsonl"
                if file_path
                else f"{batch_id}_results.jsonl"
            )

            ensure_directory_exists(output_path)
            self._write_results_to_jsonl(result_file, batch_results)

            return result_file

        except Exception as e:
            vendor = (
                getattr(provider, "vendor_type", "unknown") if provider is not None else "unknown"
            )
            raise ExternalServiceError(
                f"Failed to retrieve batch results: {e}", context={"vendor": vendor}, cause=e
            ) from e

    def _write_results_to_jsonl(self, result_file: Path, batch_results: list[BatchResult]) -> None:
        """Write batch results to JSONL file.

        Args:
            result_file: Path to write results to
            batch_results: List of batch results to write
        """
        with open(result_file, "w", encoding="utf-8") as f:
            for result in batch_results:
                raw_format = {
                    "custom_id": result.custom_id,
                    "response": {
                        "body": {
                            "choices": [{"message": {"content": json.dumps(result.content)}}],
                            "usage": result.usage,
                        }
                    },
                }
                f.write(json.dumps(raw_format) + "\n")
