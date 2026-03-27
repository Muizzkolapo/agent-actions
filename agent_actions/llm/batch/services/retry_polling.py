"""Batch polling and validation module import utilities."""

import logging
import time

from agent_actions.llm.batch.core.batch_constants import BatchStatus
from agent_actions.llm.providers.batch_base import BaseBatchClient
from agent_actions.logging import fire_event
from agent_actions.logging.events import BatchProgressEvent
from agent_actions.utils.module_loader import load_module_from_path

logger = logging.getLogger(__name__)


def wait_for_batch_completion(
    provider: BaseBatchClient,
    batch_id: str,
    timeout_seconds: int = 3600,
    poll_interval: int = 30,
    total_items: int = 0,
) -> BatchStatus:
    """Wait for batch to complete with polling.

    Fires BatchProgressEvent at intervals:
    - Every 10% completion
    - Every 60 seconds (whichever comes first)

    Args:
        provider: Batch API client
        batch_id: Batch job ID
        timeout_seconds: Maximum time to wait (default 1 hour)
        poll_interval: Seconds between status checks
        total_items: Total items in batch (for progress tracking)

    Returns:
        Final batch status
    """
    start_time = time.time()
    last_progress_time = start_time
    last_progress_pct = 0
    progress_interval = 60  # Fire progress event at least every 60 seconds

    while (time.time() - start_time) < timeout_seconds:
        status = provider.check_status(batch_id)

        completed = 0
        failed = 0
        if hasattr(provider, "get_batch_progress"):
            try:
                progress = provider.get_batch_progress(batch_id)
                completed = progress.get("completed", 0)
                failed = progress.get("failed", 0)
            except Exception as e:
                logger.debug("Failed to get batch progress for %s: %s", batch_id, e, exc_info=True)

        current_pct = (completed / total_items * 100) if total_items > 0 else 0
        current_time = time.time()
        time_since_last_progress = current_time - last_progress_time

        should_fire_progress = (
            total_items > 0
            and (
                current_pct - last_progress_pct >= 10
                or time_since_last_progress >= progress_interval
            )
            and completed > 0
        )

        if should_fire_progress:
            fire_event(
                BatchProgressEvent(
                    batch_id=batch_id,
                    completed=completed,
                    total=total_items,
                    failed=failed,
                )
            )
            last_progress_time = current_time
            last_progress_pct = current_pct  # type: ignore[assignment]

        if status in (BatchStatus.COMPLETED, BatchStatus.FAILED, BatchStatus.CANCELLED):
            return status  # type: ignore[return-value]
        logger.debug("Retry batch %s status: %s, waiting...", batch_id, status)
        time.sleep(poll_interval)

    logger.warning("Retry batch %s timed out after %d seconds", batch_id, timeout_seconds)
    return provider.check_status(batch_id)  # type: ignore[return-value]


def import_validation_module(validation_module: str, validation_path: str | None) -> None:
    """Import validation module to register UDFs via decorators.

    Args:
        validation_module: Name of the Python module (without .py extension)
        validation_path: Path where the module is located (or None for PYTHONPATH)
    """
    try:
        module = load_module_from_path(
            module_name=validation_module,
            module_path=validation_path,
            execute=True,
            fallback_import=True,
            cache=True,
        )

        if module:
            logger.debug("Successfully imported validation module: %s", validation_module)
        else:
            logger.warning(
                "Could not import validation module '%s'. "
                "Ensure the module exists and validation_path is configured correctly.",
                validation_module,
            )
    except ImportError as e:
        from agent_actions.errors import ConfigurationError

        raise ConfigurationError(
            f"Cannot import validation module '{validation_module}': {e}",
            context={"validation_module": validation_module, "validation_path": validation_path},
            cause=e,
        ) from e
    except Exception as e:
        logger.warning("Failed to import validation module '%s': %s", validation_module, e)
