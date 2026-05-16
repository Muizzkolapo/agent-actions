"""Shared test helpers for cascade/quarantine/retry tests.

Centralizes record construction, result collection, and action simulation
so cascade-related tests across unit/ and integration/ use one code path.
"""

from __future__ import annotations

from typing import Any

from agent_actions.processing.cascade_filter import partition_cascade_records
from agent_actions.processing.result_collector import ResultCollector
from agent_actions.processing.types import ProcessingResult


def make_record(
    source_guid: str,
    state: str | None = None,
    content: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a minimal pipeline record with optional _state and content."""
    r: dict[str, Any] = {
        "source_guid": source_guid,
        "content": content or {"upstream": {"val": source_guid}},
    }
    if state is not None:
        r["_state"] = state
    return r


def collect_results(
    results: list[ProcessingResult],
    action_name: str,
    storage_backend: Any = None,
):
    """Run results through the real ResultCollector."""
    return ResultCollector.collect_results(
        results,
        agent_config={"agent_type": action_name},
        agent_name=action_name,
        is_first_stage=False,
        storage_backend=storage_backend,
    )


def simulate_action(
    input_records: list[dict[str, Any]],
    action_name: str,
    failing_guids: set[str],
    storage_backend: Any = None,
) -> tuple[list[dict[str, Any]], Any]:
    """Simulate a processing action: partition → process → collect.

    Records whose source_guid is in failing_guids produce FAILED results.
    All others produce SUCCESS results. Uses real partition_cascade_records
    and ResultCollector — no mocks.
    """
    processable, quarantined = partition_cascade_records(input_records, action_name=action_name)

    results: list[ProcessingResult] = list(quarantined)

    for record in processable:
        guid = record.get("source_guid", "")
        if guid in failing_guids:
            results.append(
                ProcessingResult.failed(
                    error=f"Simulated failure for {guid}",
                    source_guid=guid,
                    input_record=record,
                )
            )
        else:
            output_data = dict(record)
            output_data["content"] = {
                **(record.get("content") or {}),
                action_name: {"processed": True, "source": guid},
            }
            results.append(
                ProcessingResult.success(
                    data=[output_data],
                    source_guid=guid,
                )
            )

    return collect_results(results, action_name, storage_backend)
