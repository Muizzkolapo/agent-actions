"""
Cluster support tickets by their consensus topic category.
FILE granularity — receives all records at once and emits one record per cluster.
"""

from typing import Any

from agent_actions import udf_tool
from agent_actions.config.types import Granularity
from agent_actions.utils.udf_management.registry import FileUDFResult


@udf_tool(granularity=Granularity.FILE)
def cluster_tickets_by_topic(data: list[dict[str, Any]]) -> FileUDFResult:
    """
    Group tickets by consensus_category and produce one output record per cluster.

    For each cluster, collects ticket IDs and selects up to 3 representative
    problems and resolutions to characterise the group.

    Input (list of records, each with):
        - source_guid: Ticket identifier
        - consensus_category: Category assigned by vote aggregation
        - problem_summary / problem: Short description of the issue
        - resolution_summary / resolution: How it was resolved

    Output (one record per cluster):
        - cluster_topic: The shared category name
        - cluster_size: Number of tickets in this cluster
        - ticket_ids: List of source_guids belonging to the cluster
        - representative_problems: Up to 3 distinct problem descriptions
        - representative_resolutions: Up to 3 distinct resolution descriptions
    """
    # Build clusters keyed by consensus_category
    clusters: dict[str, list[dict[str, Any]]] = {}
    for record in data:
        content = record.get("content", record)
        category = content.get("consensus_category", "uncategorized")
        clusters.setdefault(category, []).append(content)

    outputs: list[dict[str, Any]] = []
    for category, records in sorted(clusters.items()):
        ticket_ids = [
            r.get("source_guid", r.get("ticket_id", "unknown")) for r in records
        ]

        # Collect unique problems and resolutions, keeping order
        problems: list[str] = []
        resolutions: list[str] = []
        for r in records:
            problem = r.get("problem_summary", r.get("problem", ""))
            if problem and problem not in problems:
                problems.append(problem)

            resolution = r.get("resolution_summary", r.get("resolution", ""))
            if resolution and resolution not in resolutions:
                resolutions.append(resolution)

        outputs.append(
            {
                "cluster_topic": category,
                "cluster_size": len(records),
                "ticket_ids": ticket_ids,
                "representative_problems": problems[:3],
                "representative_resolutions": resolutions[:3],
            }
        )

    return FileUDFResult(
        outputs=outputs,
        input_count=len(data),
    )
