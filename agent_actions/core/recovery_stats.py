"""
Utility functions for calculating recovery statistics.

Analyzes recovery metadata from processed results to generate summary statistics
for manifest and status reporting.
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass


@dataclass
class RecoveryStats:
    """Summary statistics for recovery operations."""

    retry_count: int = 0  # Number of records that needed retry
    reprompt_count: int = 0  # Number of records that needed reprompt
    retry_succeeded: int = 0  # Number of records where retry succeeded
    reprompt_succeeded: int = 0  # Number of records where reprompt validation passed
    retry_exhausted: int = 0  # Number of records where retry exhausted
    reprompt_exhausted: int = 0  # Number of records where reprompt exhausted

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "retry_count": self.retry_count,
            "reprompt_count": self.reprompt_count,
            "retry_succeeded": self.retry_succeeded,
            "reprompt_succeeded": self.reprompt_succeeded,
            "retry_exhausted": self.retry_exhausted,
            "reprompt_exhausted": self.reprompt_exhausted,
        }

    def to_summary_dict(self) -> Dict[str, int]:
        """Convert to simplified summary for manifest (only counts, not breakdowns)."""
        return {
            "retry_count": self.retry_count,
            "reprompt_count": self.reprompt_count,
        }


def calculate_recovery_stats_from_results(results: List[Any]) -> RecoveryStats:
    """
    Calculate recovery statistics from a list of processing results.

    Analyzes recovery_metadata from ProcessingResult or BatchResult objects
    to generate summary statistics.

    Args:
        results: List of results with optional recovery_metadata

    Returns:
        RecoveryStats with calculated statistics

    Example:
        >>> results = process_batch(...)
        >>> stats = calculate_recovery_stats_from_results(results)
        >>> print(f"Retried: {stats.retry_count}, Reprompted: {stats.reprompt_count}")
    """
    stats = RecoveryStats()

    for result in results:
        # Get recovery metadata (handles both ProcessingResult and BatchResult)
        recovery_metadata = getattr(result, "recovery_metadata", None)

        if not recovery_metadata:
            continue

        # Count retry recovery
        if hasattr(recovery_metadata, "retry") and recovery_metadata.retry:
            stats.retry_count += 1
            if recovery_metadata.retry.succeeded:
                stats.retry_succeeded += 1
            else:
                stats.retry_exhausted += 1

        # Count reprompt recovery
        if hasattr(recovery_metadata, "reprompt") and recovery_metadata.reprompt:
            stats.reprompt_count += 1
            if recovery_metadata.reprompt.passed:
                stats.reprompt_succeeded += 1
            else:
                stats.reprompt_exhausted += 1

    return stats


def calculate_recovery_stats_from_output_data(output_data: List[Dict[str, Any]]) -> RecoveryStats:
    """
    Calculate recovery statistics from output JSON data.

    Analyzes _recovery fields in output records to generate statistics.
    Useful when processing already-written output files.

    Args:
        output_data: List of output records (dicts with optional _recovery key)

    Returns:
        RecoveryStats with calculated statistics

    Example:
        >>> with open("output.json") as f:
        ...     data = json.load(f)
        >>> stats = calculate_recovery_stats_from_output_data(data)
    """
    stats = RecoveryStats()

    for record in output_data:
        recovery = record.get("_recovery")

        if not recovery:
            continue

        # Count retry recovery
        if "retry" in recovery:
            retry = recovery["retry"]
            stats.retry_count += 1
            if retry.get("succeeded", False):
                stats.retry_succeeded += 1
            else:
                stats.retry_exhausted += 1

        # Count reprompt recovery
        if "reprompt" in recovery:
            reprompt = recovery["reprompt"]
            stats.reprompt_count += 1
            if reprompt.get("passed", False):
                stats.reprompt_succeeded += 1
            else:
                stats.reprompt_exhausted += 1

    return stats


def add_recovery_stats_to_manifest(
    manifest: Dict[str, Any], action_name: str, stats: RecoveryStats
) -> None:
    """
    Add recovery statistics to manifest structure.

    Updates manifest dict in-place with recovery stats for the specified action.

    Args:
        manifest: Manifest dictionary to update
        action_name: Name of the action
        stats: Recovery statistics to add

    Example:
        >>> manifest = {"actions": {"classify_genre": {"status": "completed"}}}
        >>> stats = RecoveryStats(retry_count=1, reprompt_count=2)
        >>> add_recovery_stats_to_manifest(manifest, "classify_genre", stats)
        >>> manifest["actions"]["classify_genre"]["recovery_stats"]
        {'retry_count': 1, 'reprompt_count': 2}
    """
    if "actions" not in manifest:
        manifest["actions"] = {}

    if action_name not in manifest["actions"]:
        manifest["actions"][action_name] = {}

    manifest["actions"][action_name]["recovery_stats"] = stats.to_summary_dict()


def add_recovery_stats_to_agent_status(
    status: Dict[str, Any], action_name: str, stats: RecoveryStats
) -> None:
    """
    Add recovery statistics to agent status structure.

    Updates status dict in-place with recovery info for the specified action.

    Args:
        status: Agent status dictionary to update
        action_name: Name of the action
        stats: Recovery statistics to add

    Example:
        >>> status = {"classify_genre": {"status": "completed"}}
        >>> stats = RecoveryStats(retry_count=1, reprompt_count=2)
        >>> add_recovery_stats_to_agent_status(status, "classify_genre", stats)
        >>> status["classify_genre"]["recovery"]
        {'retried': 1, 'reprompted': 2, 'failed': 0}
    """
    if action_name not in status:
        status[action_name] = {}

    # Calculate failed count (records that exhausted both retry and reprompt)
    failed = stats.retry_exhausted + stats.reprompt_exhausted

    status[action_name]["recovery"] = {
        "retried": stats.retry_count,
        "reprompted": stats.reprompt_count,
        "failed": failed,
    }


# Integration Guide:
#
# To integrate recovery statistics tracking into your workflow:
#
# 1. After batch processing completes:
#    ```python
#    results = batch_service.process_batch_results(...)
#    stats = calculate_recovery_stats_from_results(results)
#    ```
#
# 2. Update manifest:
#    ```python
#    manifest = load_manifest()
#    add_recovery_stats_to_manifest(manifest, action_name, stats)
#    save_manifest(manifest)
#    ```
#
# 3. Update agent status:
#    ```python
#    status = load_agent_status()
#    add_recovery_stats_to_agent_status(status, action_name, stats)
#    save_agent_status(status)
#    ```
